#!/usr/bin/env python3
"""Reference ERP transactional core. Oracle for the hidden verifier AND the calibration kernel.

Everything is integer arithmetic in minor currency units and whole pieces. If this file ever needs
a float, the spec has been misread.

Three places are deliberately subtle, because they are the traps set for the candidate, which makes
them exactly the places an oracle is most likely to get wrong too:

  1. moving average truncates toward zero, and the lost remainder is CARRIED, so that
     inventory account == sum(qty * unit_cost) + carried_remainder holds after every document.
  2. a goods issue that would go negative is rejected atomically: nothing is posted, no stock
     moves, and the books must look exactly as if the document were absent.
  3. MRP drives a component's gross requirement from its parent's planned order RELEASE day,
     not the parent's requirement day.

usage: ref_erp.py <scenario.json> <out.json>
"""
import json
import math
import pathlib
import sys

EQUITY_CLOSE = "3999"
DEBIT_NORMAL = ("asset", "expense")


class Books:
    def __init__(self, scenario):
        self.accounts = {a["id"]: a for a in scenario["accounts"]}
        self.bal = {a: 0 for a in self.accounts}          # signed, debit positive
        for acc, amt in scenario.get("opening", {}).get("accounts", {}).items():
            self.bal[acc] = self._signed(acc, amt)
        self.stock = {}                                    # material -> {qty, unit_cost}
        self.remainder = 0                                 # carried rounding remainder
        for row in scenario.get("opening", {}).get("stock", []):
            self.stock[row["material"]] = {"qty": row["qty"], "unit_cost": row["unit_cost"]}
        # The opening books must themselves balance AND already satisfy the inventory identity,
        # because the first invariant check runs on them, before document one. Loading opening
        # stock without debiting 1401 leaves `inventory account != layers` from the outset, which
        # would have been baked into every reference answer and failed every candidate.
        if EQUITY_CLOSE not in self.accounts:
            raise ValueError(f"scenario must declare equity account {EQUITY_CLOSE}")
        self.bal["1401"] = self.bal.get("1401", 0) + self.inventory_value()
        self.bal[EQUITY_CLOSE] -= sum(self.bal.values())   # equity absorbs the remaining imbalance
        self.rejected = []
        self.fx = scenario.get("fx", {})
        self.violations = []

    # --- helpers ---------------------------------------------------------
    def _signed(self, acc, amount):
        """Store balances debit-positive internally regardless of the account's normal side."""
        return amount if self.accounts[acc]["type"] in DEBIT_NORMAL else -amount

    def post(self, lines):
        """lines: [{account, debit, credit}] — must balance; raises if it does not."""
        d = sum(l.get("debit", 0) for l in lines)
        c = sum(l.get("credit", 0) for l in lines)
        if d != c:
            raise ValueError(f"unbalanced posting: debit {d} != credit {c}")
        for l in lines:
            acc = l["account"]
            if acc not in self.accounts:
                raise ValueError(f"posting to undeclared account {acc}")
            self.bal[acc] += l.get("debit", 0) - l.get("credit", 0)

    def inventory_value(self):
        return sum(s["qty"] * s["unit_cost"] for s in self.stock.values())

    def check_invariants(self, tag):
        """Run after EVERY document. Returns a list of violation strings."""
        bad = []
        # debits == credits, i.e. the signed balances sum to zero
        total = sum(self.bal.values())
        if total != 0:
            bad.append(f"{tag}: books out of balance by {total}")
        inv = self.bal.get("1401", 0)
        if inv != self.inventory_value() + self.remainder:
            bad.append(f"{tag}: inventory account {inv} != layers "
                       f"{self.inventory_value()} + remainder {self.remainder}")
        for m, s in self.stock.items():
            if s["qty"] < 0:
                bad.append(f"{tag}: negative stock {m} = {s['qty']}")
        return bad

    # --- documents -------------------------------------------------------
    def goods_receipt(self, doc):
        m, qty, cost = doc["material"], doc["qty"], doc["unit_cost"]
        s = self.stock.setdefault(m, {"qty": 0, "unit_cost": 0})
        total_before = s["qty"] * s["unit_cost"]
        added = qty * cost
        new_qty = s["qty"] + qty
        exact = total_before + added
        new_avg = int(exact / new_qty) if new_qty else 0        # truncate toward zero
        # carry what truncation dropped, so the account identity keeps holding
        self.remainder += exact - new_avg * new_qty
        s["qty"], s["unit_cost"] = new_qty, new_avg
        self.post([{"account": "1401", "debit": added}, {"account": "2101", "credit": added}])

    def goods_issue(self, doc, extra_lines=()):
        m, qty = doc["material"], doc["qty"]
        s = self.stock.get(m, {"qty": 0, "unit_cost": 0})
        if s["qty"] - qty < 0:
            self.rejected.append(doc["id"])                     # atomic reject: nothing changes
            return False
        value = qty * s["unit_cost"]
        s["qty"] -= qty
        self.post([{"account": "5001", "debit": value}, {"account": "1401", "credit": value},
                   *extra_lines])
        return True

    def sale(self, doc):
        proceeds = doc["qty"] * doc["price"]
        return self.goods_issue(doc, extra_lines=[
            {"account": "1001", "debit": proceeds}, {"account": "4001", "credit": proceeds}])

    def revaluation(self, doc):
        m, new_cost = doc["material"], doc["new_unit_cost"]
        s = self.stock.setdefault(m, {"qty": 0, "unit_cost": 0})
        delta = s["qty"] * (new_cost - s["unit_cost"])
        s["unit_cost"] = new_cost
        if delta > 0:
            self.post([{"account": "1401", "debit": delta}, {"account": "5001", "credit": delta}])
        elif delta < 0:
            self.post([{"account": "5001", "debit": -delta}, {"account": "1401", "credit": -delta}])

    def fx_journal(self, doc):
        # The rate is minor units of the book currency per 1 UNIT of the foreign currency, and the
        # line amounts are in whole units of that foreign currency, so the conversion is a plain
        # multiplication. An earlier version divided by an undocumented 100000 and produced
        # reference answers that three independent candidate implementations all contradicted
        # identically — they were right and the oracle was wrong (defect #22).
        rate = self.fx[doc["fx_currency"]][doc["period"]]
        conv = []
        for l in doc["lines"]:
            c = {"account": l["account"]}
            if l.get("debit"):
                c["debit"] = l["debit"] * rate
            if l.get("credit"):
                c["credit"] = l["credit"] * rate
            conv.append(c)
        self.post(conv)

    def period_close(self, doc):
        total = 0
        for acc, a in self.accounts.items():
            if a["type"] in ("income", "expense"):
                total += self.bal[acc]
                self.bal[acc] = 0
        # `total` is debit-positive: net expense > 0 reduces equity
        self.bal[EQUITY_CLOSE] = self.bal.get(EQUITY_CLOSE, 0) + total

    def apply(self, doc):
        t = doc["type"]
        if t == "journal":
            self.post(doc["lines"])
        elif t == "goods_receipt":
            self.goods_receipt(doc)
        elif t == "goods_issue":
            self.goods_issue(doc)
        elif t == "sale":
            self.sale(doc)
        elif t == "revaluation":
            self.revaluation(doc)
        elif t == "fx_journal":
            self.fx_journal(doc)
        elif t == "period_close":
            self.period_close(doc)
        else:
            raise ValueError(f"unknown document type {t!r}")


# ------------------------------------------------------------------ MRP


def find_cycles(materials):
    """Return sorted material ids that participate in a BOM cycle."""
    colour, cyclic = {}, set()

    def walk(mid, stack):
        if colour.get(mid) == 1:                    # back edge -> everything on the stack cycles
            cyclic.update(stack[stack.index(mid):])
            return
        if colour.get(mid) == 2:
            return
        colour[mid] = 1
        for comp in materials.get(mid, {}).get("bom", []):
            walk(comp["component"], stack + [mid])
        colour[mid] = 2

    for mid in materials:
        walk(mid, [])
    return sorted(cyclic)


def mrp(scenario, on_hand):
    materials = {m["id"]: m for m in scenario["materials"]}
    cycles = set(find_cycles(materials))
    plan = []
    # gross requirements per (material, day); seeded by independent demand
    gross = {}
    for d in scenario.get("mrp", {}).get("demand", []):
        gross.setdefault(d["material"], {}).setdefault(d["day"], 0)
        gross[d["material"]][d["day"]] += d["qty"]

    # level-by-level: a component is only planned once every parent has been planned
    order, seen = [], set()

    def depth(mid, guard):
        if mid in cycles or mid in guard:
            return 0
        kids = materials.get(mid, {}).get("bom", [])
        return 1 + max([depth(k["component"], guard | {mid}) for k in kids], default=0)

    for mid in materials:
        if mid not in cycles:
            order.append(mid)
    order.sort(key=lambda m: -depth(m, set()))

    for mid in order:
        if mid not in gross:
            continue
        m = materials[mid]
        lot = m.get("lot_size", 1) or 1
        lead = m.get("lead_time", 0)
        safety = m.get("safety_stock", 0)
        avail = on_hand.get(mid, {}).get("qty", 0)
        for day in sorted(gross[mid]):
            need = gross[mid][day]
            projected = avail - need
            net = safety - projected
            if net <= 0:
                avail = projected
                continue
            qty = math.ceil(net / lot) * lot
            release = day - lead
            plan.append({"material": mid, "qty": qty, "release_day": release, "due_day": day})
            avail = projected + qty
            # component demand hangs off the parent's RELEASE day, not its requirement day
            for comp in m.get("bom", []):
                if comp["component"] in cycles:
                    continue
                g = gross.setdefault(comp["component"], {})
                g[release] = g.get(release, 0) + qty * comp["qty"]

    plan.sort(key=lambda p: (p["release_day"], p["material"]))
    return plan, sorted(cycles)


def run(scenario):
    b = Books(scenario)
    violations = b.check_invariants("opening")
    for doc in scenario["documents"]:
        b.apply(doc)
        violations += b.check_invariants(doc.get("id", doc["type"]))
    plan, cycles = mrp(scenario, b.stock)
    trial = {}
    for acc, a in b.accounts.items():
        v = b.bal[acc]
        trial[acc] = v if a["type"] in DEBIT_NORMAL else -v
    stock_out = [{"material": m, "qty": s["qty"], "unit_cost": s["unit_cost"],
                  "value": s["qty"] * s["unit_cost"]}
                 for m, s in sorted(b.stock.items())]
    return {"trial_balance": trial, "stock": stock_out, "rejected": b.rejected,
            "planned_orders": plan, "bom_cycles": cycles,
            "equity_after_close": trial.get(EQUITY_CLOSE, 0),
            "_violations": violations, "_remainder": b.remainder}


def main():
    scenario = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out = run(scenario)
    pathlib.Path(sys.argv[2]).write_text(json.dumps(
        {k: v for k, v in out.items() if not k.startswith("_")}, indent=1))


if __name__ == "__main__":
    main()
