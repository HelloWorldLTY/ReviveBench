#!/usr/bin/env python3
"""Reference PLM core — oracle for plm_bom and the calibration kernel.

Pure set and integer logic over dates, so the reference answer is not an approximation: it is the
spec's answer. As on scada_dcs and mes_exec, the burden is on the spec being unambiguous and this
file matching it, which is why the self-test beside it checks hand-computed explosions and closures
rather than merely re-running this code.

The five subtle points, and therefore the five to read carefully:

  * effectivity is INCLUSIVE at both ends, and `eff_to: null` means open-ended;
  * a leaf reached by several paths ACCUMULATES quantity — the single most common error, and the
    reason `explode` sums rather than overwrites;
  * a variant condition `when` gates a line on an option code being present in the query's options;
  * ECO `remove`/`qty` close the old line on the calendar day BEFORE the ECO date, which in a leap
    year means 2026-03-01 closes on 2026-02-28 but 2024-03-01 closes on 2024-02-29;
  * cycles are detected per (date, options), because a cycle can exist under one option set and not
    another.

usage: ref_plm.py <query.json> <out.json>
"""
import datetime
import json
import pathlib
import sys


def day_before(iso):
    d = datetime.date.fromisoformat(iso)
    return (d - datetime.timedelta(days=1)).isoformat()


def effective(line, date):
    """Inclusive at both ends; eff_to None means open-ended."""
    if line.get("eff_from") and date < line["eff_from"]:
        return False
    if line.get("eff_to") and date > line["eff_to"]:
        return False
    return True


def apply_ecos(bom, ecos):
    """Apply ECOs in (effective, id) order, returning a new BOM list."""
    out = [dict(l) for l in bom]
    for eco in sorted(ecos, key=lambda e: (e["effective"], e["id"])):
        when = eco["effective"]
        for ch in eco["changes"]:
            par, ch_id = ch["parent"], ch["child"]
            if ch["op"] in ("remove", "qty"):
                for l in out:
                    if l["parent"] == par and l["child"] == ch_id:
                        # close only lines still open on the ECO date
                        if not l.get("eff_to") or l["eff_to"] >= when:
                            l["eff_to"] = day_before(when)
            if ch["op"] in ("add", "qty"):
                out.append({"parent": par, "child": ch_id, "qty": ch["qty"],
                            "eff_from": when, "eff_to": None,
                            "when": ch.get("when")})
    return out


class Model:
    def __init__(self, q):
        self.parts = q.get("parts", [])
        self.bom = apply_ecos(q.get("bom", []), q.get("ecos", []))
        self.ecos = {e["id"]: e for e in q.get("ecos", [])}

    def children(self, parent, date, options):
        opts = set(options or [])
        out = []
        for l in self.bom:
            if l["parent"] != parent or not effective(l, date):
                continue
            cond = l.get("when")
            if cond is not None and cond not in opts:
                continue
            out.append((l["child"], l["qty"]))
        return out

    def find_cycle(self, root, date, options):
        """Return the sorted set of parts on a cycle reachable from root, or []."""
        colour, onstack, found = {}, [], set()

        def walk(p):
            colour[p] = 1
            onstack.append(p)
            for (c, _) in self.children(p, date, options):
                if colour.get(c) == 1:
                    found.update(onstack[onstack.index(c):])
                elif colour.get(c) != 2:
                    walk(c)
            onstack.pop()
            colour[p] = 2

        walk(root)
        return sorted(found)

    def explode(self, root, date, options):
        """Flat leaf quantities; a leaf on several paths accumulates."""
        leaves = {}

        def walk(p, mult):
            kids = self.children(p, date, options)
            if not kids:
                leaves[p] = leaves.get(p, 0) + mult
                return
            for (c, q) in kids:
                walk(c, mult * q)

        walk(root, 1)
        # A part that is itself a leaf explodes to one of itself. The first draft silently dropped
        # it and returned [], which is a semantic choice the SPEC never stated — an unstated choice
        # inside an oracle is precisely how this suite's false negatives have been born.
        return [{"part": p, "qty": n} for p, n in sorted(leaves.items())]

    def where_used(self, part, date, options):
        """Transitive ancestors of `part`, excluding it."""
        parents = {}
        for l in self.bom:
            if not effective(l, date):
                continue
            cond = l.get("when")
            if cond is not None and cond not in set(options or []):
                continue
            parents.setdefault(l["child"], set()).add(l["parent"])
        seen, stack = set(), [part]
        while stack:
            cur = stack.pop()
            for p in parents.get(cur, ()):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        seen.discard(part)
        return sorted(seen)

    def effective_rev(self, part, date):
        for p in self.parts:
            if p["id"] == part and effective(p, date):
                return p["rev"]
        return None

    def eco_impact(self, eco_id, options):
        eco = self.ecos[eco_id]
        date = eco["effective"]
        named = set()
        for ch in eco["changes"]:
            named.add(ch["parent"])
            named.add(ch["child"])
        impact = set()
        for n in named:
            impact.update(self.where_used(n, date, options))
        # the named parents themselves are impacted; named children only if also ancestors
        for ch in eco["changes"]:
            impact.add(ch["parent"])
        return sorted(impact)


def run(q):
    m = Model(q)
    results = []
    for i, query in enumerate(q.get("queries", [])):
        kind = query["kind"]
        opts = query.get("options") or []
        if kind == "explode":
            cyc = m.find_cycle(query["part"], query["date"], opts)
            if cyc:
                results.append({"query": i, "kind": kind, "error": "cycle", "cycle_parts": cyc})
            else:
                results.append({"query": i, "kind": kind,
                                "leaves": m.explode(query["part"], query["date"], opts)})
        elif kind == "where_used":
            results.append({"query": i, "kind": kind,
                            "parts": m.where_used(query["part"], query["date"], opts)})
        elif kind == "effective_rev":
            results.append({"query": i, "kind": kind,
                            "rev": m.effective_rev(query["part"], query["date"])})
        elif kind == "eco_impact":
            results.append({"query": i, "kind": kind,
                            "parts": m.eco_impact(query["eco"], opts)})
        else:
            raise SystemExit(f"ref_plm: unknown query kind {kind!r}")
    return {"results": results}


def main():
    q = json.loads(pathlib.Path(sys.argv[1]).read_text())
    pathlib.Path(sys.argv[2]).write_text(json.dumps(run(q), indent=1))


if __name__ == "__main__":
    main()
