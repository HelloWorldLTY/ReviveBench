#!/usr/bin/env python3
"""Build the hidden scenario set for erp_ledger and compute reference answers with ref_erp.

Emits, into hidden/:
    scenarios/<name>.json          the scenario handed to the candidate
    ref/<name>.json                the reference answer
    examples/<name>.scenario.json  three worked examples copied into the workspace
    examples/<name>.expected.json  ... with their answers
    manifest.json                  the scenario list

Every scenario is replayed through the reference implementation's own per-document invariant
checks. If any scenario violates an invariant, this aborts rather than writing it: an asset whose
reference answer is internally inconsistent would fail every candidate, and that failure would look
exactly like the candidate's fault.

usage: make_scenarios.py [--out <hidden dir>]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ref_erp import run  # noqa: E402

ACCOUNTS = [
    {"id": "1001", "name": "Cash", "type": "asset"},
    {"id": "1401", "name": "Inventory", "type": "asset"},
    {"id": "1501", "name": "Prepaid", "type": "asset"},
    {"id": "2101", "name": "Accounts Payable", "type": "liability"},
    {"id": "2201", "name": "Accrued Liabilities", "type": "liability"},
    {"id": "3999", "name": "Equity", "type": "equity"},
    {"id": "4001", "name": "Revenue", "type": "income"},
    {"id": "5001", "name": "COGS", "type": "expense"},
    {"id": "5201", "name": "Operating Expense", "type": "expense"},
]


def base(name, **kw):
    s = {"name": name, "currency": "CNY", "fx": {}, "accounts": ACCOUNTS, "materials": [],
         "opening": {"accounts": {}, "stock": []}, "documents": [],
         "mrp": {"horizon": 30, "demand": []}}
    s.update(kw)
    return s


def scenarios():
    S = {}

    # s01 — plain journals only: the floor case, tests opening equity absorption
    S["s01_journals"] = base(
        "s01_journals",
        opening={"accounts": {"1001": 50000000}, "stock": []},
        documents=[
            {"id": "D01", "type": "journal", "period": "2026-01",
             "lines": [{"account": "5201", "debit": 125000}, {"account": "1001", "credit": 125000}]},
            {"id": "D02", "type": "journal", "period": "2026-01",
             "lines": [{"account": "1501", "debit": 60000}, {"account": "1001", "credit": 60000}]},
            {"id": "D03", "type": "journal", "period": "2026-01",
             "lines": [{"account": "5201", "debit": 20000}, {"account": "2201", "credit": 20000}]},
        ])

    # s02 — moving average that does NOT divide evenly, twice over
    S["s02_moving_avg"] = base(
        "s02_moving_avg",
        opening={"accounts": {"1001": 10000000}, "stock": [{"material": "M200", "qty": 100, "unit_cost": 1250}]},
        documents=[
            {"id": "D01", "type": "goods_receipt", "material": "M200", "qty": 3, "unit_cost": 1000, "period": "2026-01"},
            {"id": "D02", "type": "goods_receipt", "material": "M200", "qty": 7, "unit_cost": 1333, "period": "2026-01"},
            {"id": "D03", "type": "goods_issue", "material": "M200", "qty": 11, "period": "2026-01"},
        ])

    # s03 — an issue that must be rejected, and postings that continue afterwards
    S["s03_reject"] = base(
        "s03_reject",
        opening={"accounts": {"1001": 5000000}, "stock": [{"material": "M200", "qty": 10, "unit_cost": 900}]},
        documents=[
            {"id": "D01", "type": "goods_issue", "material": "M200", "qty": 4, "period": "2026-01"},
            {"id": "D02", "type": "goods_issue", "material": "M200", "qty": 999, "period": "2026-01"},
            {"id": "D03", "type": "goods_issue", "material": "M999", "qty": 1, "period": "2026-01"},
            {"id": "D04", "type": "sale", "material": "M200", "qty": 6, "price": 2500, "period": "2026-01"},
            {"id": "D05", "type": "sale", "material": "M200", "qty": 1, "price": 2500, "period": "2026-01"},
        ])

    # s04 — revaluation of partially issued stock, both directions
    S["s04_revalue"] = base(
        "s04_revalue",
        opening={"accounts": {"1001": 8000000}, "stock": [{"material": "M300", "qty": 40, "unit_cost": 2000}]},
        documents=[
            {"id": "D01", "type": "goods_issue", "material": "M300", "qty": 15, "period": "2026-01"},
            {"id": "D02", "type": "revaluation", "material": "M300", "new_unit_cost": 2350, "period": "2026-01"},
            {"id": "D03", "type": "goods_issue", "material": "M300", "qty": 5, "period": "2026-01"},
            {"id": "D04", "type": "revaluation", "material": "M300", "new_unit_cost": 1800, "period": "2026-01"},
        ])

    # s05 — multi-currency across a rate change
    S["s05_fx"] = base(
        "s05_fx",
        fx={"USD": {"2026-01": 712340, "2026-02": 709880}},
        opening={"accounts": {"1001": 20000000}, "stock": []},
        documents=[
            {"id": "D01", "type": "fx_journal", "fx_currency": "USD", "period": "2026-01",
             "lines": [{"account": "5201", "debit": 15}, {"account": "2101", "credit": 15}]},
            {"id": "D02", "type": "fx_journal", "fx_currency": "USD", "period": "2026-02",
             "lines": [{"account": "5201", "debit": 15}, {"account": "2101", "credit": 15}]},
            {"id": "D03", "type": "journal", "period": "2026-02",
             "lines": [{"account": "2101", "debit": 100000}, {"account": "1001", "credit": 100000}]},
        ])

    # s06 — period close, then further postings into the next period
    S["s06_close"] = base(
        "s06_close",
        opening={"accounts": {"1001": 30000000}, "stock": [{"material": "M200", "qty": 50, "unit_cost": 1100}]},
        documents=[
            {"id": "D01", "type": "sale", "material": "M200", "qty": 20, "price": 2600, "period": "2026-01"},
            {"id": "D02", "type": "journal", "period": "2026-01",
             "lines": [{"account": "5201", "debit": 42000}, {"account": "1001", "credit": 42000}]},
            {"id": "D03", "type": "period_close", "period": "2026-01"},
            {"id": "D04", "type": "sale", "material": "M200", "qty": 10, "price": 2700, "period": "2026-02"},
            {"id": "D05", "type": "period_close", "period": "2026-02"},
        ])

    # s07 — three-level BOM with a component shared by two parents
    S["s07_bom3"] = base(
        "s07_bom3",
        materials=[
            {"id": "P100", "name": "assembly", "lead_time": 4, "lot_size": 25, "safety_stock": 0,
             "bom": [{"component": "S200", "qty": 2}, {"component": "C900", "qty": 3}]},
            {"id": "S200", "name": "subassembly", "lead_time": 2, "lot_size": 40, "safety_stock": 10,
             "bom": [{"component": "C900", "qty": 4}]},
            {"id": "C900", "name": "screw", "lead_time": 1, "lot_size": 100, "safety_stock": 50, "bom": []},
        ],
        opening={"accounts": {"1001": 1000000}, "stock": [{"material": "C900", "qty": 120, "unit_cost": 15}]},
        mrp={"horizon": 40, "demand": [{"material": "P100", "qty": 60, "day": 20}]})

    # s08 — cyclic BOM: must be detected, not followed
    S["s08_cycle"] = base(
        "s08_cycle",
        materials=[
            {"id": "A100", "lead_time": 1, "lot_size": 10, "safety_stock": 0,
             "bom": [{"component": "B200", "qty": 1}]},
            {"id": "B200", "lead_time": 1, "lot_size": 10, "safety_stock": 0,
             "bom": [{"component": "C300", "qty": 1}]},
            {"id": "C300", "lead_time": 1, "lot_size": 10, "safety_stock": 0,
             "bom": [{"component": "A100", "qty": 1}]},
            {"id": "D400", "lead_time": 2, "lot_size": 5, "safety_stock": 0, "bom": []},
        ],
        mrp={"horizon": 20, "demand": [{"material": "D400", "qty": 12, "day": 8}]})

    # s09 — MRP with safety stock and on-hand covering part of the demand
    S["s09_safety"] = base(
        "s09_safety",
        materials=[
            {"id": "M500", "lead_time": 5, "lot_size": 30, "safety_stock": 25, "bom": []},
        ],
        opening={"accounts": {"1001": 500000}, "stock": [{"material": "M500", "qty": 40, "unit_cost": 700}]},
        mrp={"horizon": 30, "demand": [{"material": "M500", "qty": 10, "day": 6},
                                       {"material": "M500", "qty": 45, "day": 14},
                                       {"material": "M500", "qty": 20, "day": 22}]})

    # s10 — the mixed scenario: ledger, inventory, rejection and MRP together
    S["s10_mixed"] = base(
        "s10_mixed",
        fx={"USD": {"2026-01": 712340}},
        materials=[
            {"id": "M100", "lead_time": 3, "lot_size": 50, "safety_stock": 20,
             "bom": [{"component": "M200", "qty": 2}, {"component": "M300", "qty": 1}]},
            {"id": "M200", "lead_time": 2, "lot_size": 25, "safety_stock": 0, "bom": []},
            {"id": "M300", "lead_time": 1, "lot_size": 10, "safety_stock": 5, "bom": []},
        ],
        opening={"accounts": {"1001": 40000000},
                 "stock": [{"material": "M200", "qty": 30, "unit_cost": 1250},
                           {"material": "M300", "qty": 8, "unit_cost": 640}]},
        documents=[
            {"id": "D01", "type": "goods_receipt", "material": "M200", "qty": 7, "unit_cost": 1310, "period": "2026-01"},
            {"id": "D02", "type": "fx_journal", "fx_currency": "USD", "period": "2026-01",
             "lines": [{"account": "5201", "debit": 8}, {"account": "2101", "credit": 8}]},
            {"id": "D03", "type": "goods_issue", "material": "M200", "qty": 100, "period": "2026-01"},
            {"id": "D04", "type": "sale", "material": "M300", "qty": 3, "price": 1900, "period": "2026-01"},
            {"id": "D05", "type": "revaluation", "material": "M200", "new_unit_cost": 1290, "period": "2026-01"},
            {"id": "D06", "type": "period_close", "period": "2026-01"},
        ],
        mrp={"horizon": 40, "demand": [{"material": "M100", "qty": 90, "day": 15}]})

    return S


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("scenarios", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, s in scenarios().items():
        r = run(s)
        # Magnitude guard: no account balance may sit more than an order of magnitude from the opening asset
        # scale. After defect #22 fixed the conversion, foreign-currency amounts written at the old scale were
        # not updated and s10_mixed's equity became -5.6 billion minor units: the reference answer was
        # self-consistent and the scenario absurd. Self-consistent is not the same as sane.
        opening_scale = max(abs(v) for v in s["opening"]["accounts"].values()) if s["opening"]["accounts"] else 10**7
        for acc, bal in r["trial_balance"].items():
            if abs(bal) > 100 * opening_scale:
                raise SystemExit(
                    f"make_scenarios: {name} account {acc} balance {bal} exceeds 100x the opening scale {opening_scale}, "
                    f"so the magnitude is probably wrong; fix the scenario before generating the reference answer")
        if r["_violations"]:
            raise SystemExit(
                f"make_scenarios: {name} violates its own invariants -> "
                f"{r['_violations'][:3]}. Fix the asset before grading anyone against it.")
        answer = {k: v for k, v in r.items() if not k.startswith("_")}
        (out / "scenarios" / f"{name}.json").write_text(json.dumps(s, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(answer, indent=1))
        manifest.append(name)
        print("%-16s accounts=%-3d rejected=%-2d planned=%-3d cycle=%-8s equity=%d" % (
            name, len(answer["trial_balance"]), len(answer["rejected"]),
            len(answer["planned_orders"]), answer["bom_cycles"] or "-",
            answer["equity_after_close"]))

    # three worked examples: one ledger-only, one inventory, one MRP
    for name in ("s01_journals", "s02_moving_avg", "s07_bom3"):
        s = json.loads((out / "scenarios" / f"{name}.json").read_text())
        ref = json.loads((out / "ref" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.scenario.json").write_text(json.dumps(s, indent=1))
        (out / "examples" / f"{name}.expected.json").write_text(json.dumps(ref, indent=1))

    (out / "manifest.json").write_text(json.dumps({"scenarios": manifest}, indent=1))
    print(f"\n{len(manifest)} scenarios written to {out}")


if __name__ == "__main__":
    main()
