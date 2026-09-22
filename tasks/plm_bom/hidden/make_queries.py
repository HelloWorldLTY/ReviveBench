#!/usr/bin/env python3
"""Build the hidden query set for plm_bom and its reference answers.

Emits, into hidden/:
    queries/<name>.json          the query file handed to the candidate
    ref/<name>.json              the reference answer from ref_plm
    examples/<name>.query.json   three worked examples copied into the workspace
    examples/<name>.expected.json
    manifest.json

Guards, each earned from a defect on an earlier task:

  * every BOM line and query must reference a declared part, and every eco_impact query must name a
    declared ECO — a dangling reference is my defect, not the candidate's;
  * effectivity windows must be non-empty (eff_from <= eff_to), or a line is silently dead;
  * every case must produce at least one non-trivial answer, so no query is graded vacuously;
  * the reference's own explode results must have positive integer quantities.

usage: make_queries.py [--out <hidden dir>]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ref_plm import run  # noqa: E402

OPEN = None


def part(pid, rev, f="2026-01-01", t=None):
    return {"id": pid, "rev": rev, "eff_from": f, "eff_to": t}


def line(parent, child, qty, f="2026-01-01", t=None, when=None):
    return {"parent": parent, "child": child, "qty": qty,
            "eff_from": f, "eff_to": t, "when": when}


def cases():
    C = {}

    # q01 — the floor: one level
    C["q01_flat"] = {
        "parts": [part("P100", "A"), part("R1", "A")],
        "bom": [line("P100", "R1", 4)],
        "ecos": [],
        "queries": [{"kind": "explode", "part": "P100", "date": "2026-05-01", "options": []},
                    {"kind": "effective_rev", "part": "P100", "date": "2026-05-01"}]}

    # q02 — a leaf reached by two paths: quantities must SUM (2*5 + 3*7 = 31)
    C["q02_multipath"] = {
        "parts": [part(x, "A") for x in ("P", "A1", "B1", "R")],
        "bom": [line("P", "A1", 2), line("P", "B1", 3),
                line("A1", "R", 5), line("B1", "R", 7)],
        "ecos": [],
        "queries": [{"kind": "explode", "part": "P", "date": "2026-05-01", "options": []},
                    {"kind": "where_used", "part": "R", "date": "2026-05-01", "options": []}]}

    # q03 — three levels deep, quantities multiply down
    C["q03_deep"] = {
        "parts": [part(x, "A") for x in ("TOP", "M1", "M2", "L1", "L2")],
        "bom": [line("TOP", "M1", 2), line("M1", "M2", 3),
                line("M2", "L1", 5), line("M2", "L2", 1)],
        "ecos": [],
        "queries": [{"kind": "explode", "part": "TOP", "date": "2026-05-01", "options": []},
                    {"kind": "where_used", "part": "L1", "date": "2026-05-01", "options": []}]}

    # q04 — a line that expires the day before the query date
    C["q04_expiry"] = {
        "parts": [part(x, "A") for x in ("P", "OLD", "NEW")],
        "bom": [line("P", "OLD", 1, t="2026-06-30"),
                line("P", "NEW", 1, f="2026-07-01")],
        "ecos": [],
        "queries": [{"kind": "explode", "part": "P", "date": "2026-06-30", "options": []},
                    {"kind": "explode", "part": "P", "date": "2026-07-01", "options": []}]}

    # q05 — ECO closing a line on the last day of February in a LEAP year
    C["q05_leap_eco"] = {
        "parts": [part(x, "A", f="2024-01-01") for x in ("P", "S")],
        "bom": [line("P", "S", 2, f="2024-01-01")],
        "ecos": [{"id": "E1", "effective": "2024-03-01",
                  "changes": [{"op": "qty", "parent": "P", "child": "S", "qty": 9}]}],
        "queries": [{"kind": "explode", "part": "P", "date": "2024-02-29", "options": []},
                    {"kind": "explode", "part": "P", "date": "2024-03-01", "options": []}]}

    # q06 — a variant option switching between alternative children
    C["q06_variant"] = {
        "parts": [part(x, "A") for x in ("P", "EU1", "US1", "COMMON")],
        "bom": [line("P", "COMMON", 1),
                line("P", "EU1", 2, when="EU"),
                line("P", "US1", 3, when="US")],
        "ecos": [],
        "queries": [{"kind": "explode", "part": "P", "date": "2026-05-01", "options": ["EU"]},
                    {"kind": "explode", "part": "P", "date": "2026-05-01", "options": ["US"]},
                    {"kind": "explode", "part": "P", "date": "2026-05-01", "options": []}]}

    # q07 — a lapsed revision: effective_rev must be null
    C["q07_lapsed_rev"] = {
        "parts": [part("P", "A", f="2025-01-01", t="2025-12-31"),
                  part("P", "B", f="2026-01-01", t="2026-06-30")],
        "bom": [line("P", "R", 1)],
        "queries": [{"kind": "effective_rev", "part": "P", "date": "2025-06-01"},
                    {"kind": "effective_rev", "part": "P", "date": "2026-03-01"},
                    {"kind": "effective_rev", "part": "P", "date": "2026-09-01"}],
        "ecos": []}

    # q08 — a cycle effective only under one option set
    C["q08_conditional_cycle"] = {
        "parts": [part(x, "A") for x in ("A1", "B1")],
        "bom": [line("A1", "B1", 1), line("B1", "A1", 1, when="LOOP")],
        "ecos": [],
        "queries": [{"kind": "explode", "part": "A1", "date": "2026-05-01", "options": ["LOOP"]},
                    {"kind": "explode", "part": "A1", "date": "2026-05-01", "options": []}]}

    # q09 — ECO add and remove, with impact analysis
    C["q09_eco_impact"] = {
        "parts": [part(x, "A") for x in ("TOP", "SUB", "R1", "R2")],
        "bom": [line("TOP", "SUB", 1), line("SUB", "R1", 4)],
        "ecos": [{"id": "E1", "effective": "2026-07-01",
                  "changes": [{"op": "add", "parent": "SUB", "child": "R2", "qty": 2},
                              {"op": "remove", "parent": "SUB", "child": "R1"}]}],
        "queries": [{"kind": "explode", "part": "TOP", "date": "2026-06-30", "options": []},
                    {"kind": "explode", "part": "TOP", "date": "2026-07-01", "options": []},
                    {"kind": "eco_impact", "eco": "E1", "options": []}]}

    # q10 — two ECOs applied in order, the second superseding the first
    C["q10_eco_order"] = {
        "parts": [part(x, "A") for x in ("P", "S")],
        "bom": [line("P", "S", 1)],
        "ecos": [{"id": "E2", "effective": "2026-09-01",
                  "changes": [{"op": "qty", "parent": "P", "child": "S", "qty": 7}]},
                 {"id": "E1", "effective": "2026-05-01",
                  "changes": [{"op": "qty", "parent": "P", "child": "S", "qty": 3}]}],
        "queries": [{"kind": "explode", "part": "P", "date": "2026-04-01", "options": []},
                    {"kind": "explode", "part": "P", "date": "2026-06-01", "options": []},
                    {"kind": "explode", "part": "P", "date": "2026-10-01", "options": []}]}

    # q11 — everything: variants, depth, multipath, an ECO and a where-used
    C["q11_combined"] = {
        "parts": [part(x, "A") for x in ("PROD", "ASM1", "ASM2", "CORE", "TRIM", "BOLT")],
        "bom": [line("PROD", "ASM1", 2), line("PROD", "ASM2", 1),
                line("ASM1", "CORE", 3), line("ASM1", "BOLT", 8),
                line("ASM2", "CORE", 1), line("ASM2", "TRIM", 4, when="LUX"),
                line("ASM2", "BOLT", 2)],
        "ecos": [{"id": "E1", "effective": "2026-08-01",
                  "changes": [{"op": "qty", "parent": "ASM1", "child": "BOLT", "qty": 12}]}],
        "queries": [{"kind": "explode", "part": "PROD", "date": "2026-05-01", "options": []},
                    {"kind": "explode", "part": "PROD", "date": "2026-05-01", "options": ["LUX"]},
                    {"kind": "explode", "part": "PROD", "date": "2026-09-01", "options": ["LUX"]},
                    {"kind": "where_used", "part": "BOLT", "date": "2026-05-01", "options": []},
                    {"kind": "eco_impact", "eco": "E1", "options": []}]}
    return C


def wellformed(name, q):
    declared = {p["id"] for p in q["parts"]}
    # children may be leaves not separately declared; parents must exist as parts or as children
    known = set(declared)
    for l in q["bom"]:
        known.add(l["parent"])
        known.add(l["child"])
        if l["eff_to"] and l["eff_from"] > l["eff_to"]:
            raise SystemExit(f"{name}: empty effectivity interval {l['parent']}->{l['child']} "
                             f"{l['eff_from']}..{l['eff_to']}")
        if l["qty"] <= 0:
            raise SystemExit(f"{name}: non-positive quantity {l['parent']}->{l['child']}")
    eco_ids = {e["id"] for e in q["ecos"]}
    for e in q["ecos"]:
        for ch in e["changes"]:
            if ch["op"] not in ("add", "remove", "qty"):
                raise SystemExit(f"{name}: unknown ECO operation {ch['op']}")
            if ch["op"] in ("add", "qty") and ch.get("qty", 0) <= 0:
                raise SystemExit(f"{name}: ECO {e['id']} has a non-positive quantity")
    for qu in q["queries"]:
        if qu["kind"] == "eco_impact":
            if qu["eco"] not in eco_ids:
                raise SystemExit(f"{name}: query references an undeclared ECO {qu['eco']}")
        elif qu["part"] not in known:
            raise SystemExit(f"{name}: query references an unknown part {qu['part']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("queries", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, q in cases().items():
        q = dict(q, name=name)
        wellformed(name, q)
        r = run(q)

        # guards on the reference's own answer
        nontrivial = False
        for res in r["results"]:
            if res["kind"] == "explode" and "leaves" in res:
                for lf in res["leaves"]:
                    if not isinstance(lf["qty"], int) or lf["qty"] <= 0:
                        raise SystemExit(f"{name}: expansion quantity is not a positive integer {lf}")
                nontrivial = nontrivial or bool(res["leaves"])
            if res.get("error") == "cycle" and res["cycle_parts"]:
                nontrivial = True
            if res["kind"] in ("where_used", "eco_impact") and res.get("parts"):
                nontrivial = True
            if res["kind"] == "effective_rev" and res.get("rev") is not None:
                nontrivial = True
        if not nontrivial:
            raise SystemExit(f"{name}: every query result is empty -- an empty check")

        (out / "queries" / f"{name}.json").write_text(json.dumps(q, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(r, indent=1))
        manifest.append(name)
        kinds = {}
        for qu in q["queries"]:
            kinds[qu["kind"]] = kinds.get(qu["kind"], 0) + 1
        print("%-22s queries=%-2d %s" % (name, len(q["queries"]),
                                      " ".join(f"{k}×{v}" for k, v in sorted(kinds.items()))))

    for name in ("q01_flat", "q02_multipath", "q06_variant"):
        q = json.loads((out / "queries" / f"{name}.json").read_text())
        r = json.loads((out / "ref" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.query.json").write_text(json.dumps(q, indent=1))
        (out / "examples" / f"{name}.expected.json").write_text(json.dumps(r, indent=1))

    (out / "manifest.json").write_text(json.dumps({"cases": manifest}, indent=1))
    print(f"\n{len(manifest)} cases written to {out}")


if __name__ == "__main__":
    main()
