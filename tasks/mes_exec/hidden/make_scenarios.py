#!/usr/bin/env python3
"""Build the hidden scenario set for mes_exec and its reference answers.

Emits, into hidden/:
    scenarios/<name>.json          the scenario handed to the candidate
    ref/<name>.json                the reference answer from ref_mes
    examples/<name>.scenario.json  three worked examples copied into the workspace
    examples/<name>.expected.json
    manifest.json

Guards, each earned from a defect on an earlier task in this suite:

  * the material balance must close on the reference's own answer — an asset whose own numbers do
    not satisfy `received - consumed = remaining` would fail every candidate for my reason;
  * the schedule must already be in the order the spec mandates, and no two operations may overlap
    on one work centre (finite capacity is the whole point);
  * every routing, lot and work order must reference declared entities;
  * a scenario must exercise something — one that schedules nothing and consumes nothing is a
    vacuous check.

usage: make_scenarios.py [--out <hidden dir>]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ref_mes import run  # noqa: E402


def base(name, **kw):
    s = {"name": name, "horizon_min": 960,
         "work_centres": [{"id": "WC1", "available_min": 480}],
         "routings": {}, "lots": [], "work_orders": []}
    s.update(kw)
    return s


def op(n, wc, setup, per_unit, ppm=0, consumes=()):
    return {"op": n, "wc": wc, "setup_min": setup, "run_min_per_unit": per_unit,
            "scrap_ppm": ppm, "consumes": list(consumes)}


def scenarios():
    S = {}

    # m01 — the floor: one order, one operation
    S["m01_single"] = base("m01_single",
        routings={"P100": [op(10, "WC1", 20, 2)]},
        work_orders=[{"id": "WO1", "product": "P100", "qty": 50, "release_min": 0, "priority": 1}])

    # m02 — two orders contend for one centre; the dispatch key decides
    S["m02_contention"] = base("m02_contention",
        routings={"P100": [op(10, "WC1", 10, 1)]},
        work_orders=[{"id": "WO2", "product": "P100", "qty": 40, "release_min": 0, "priority": 1},
                     {"id": "WO1", "product": "P100", "qty": 30, "release_min": 0, "priority": 1}])

    # m03 — priority overrides id order
    S["m03_priority"] = base("m03_priority",
        routings={"P100": [op(10, "WC1", 10, 1)]},
        work_orders=[{"id": "WO1", "product": "P100", "qty": 30, "release_min": 0, "priority": 9},
                     {"id": "WO2", "product": "P100", "qty": 20, "release_min": 0, "priority": 1}])

    # m04 — multi-operation routing across two centres, so op n+1 waits on op n
    S["m04_routing"] = base("m04_routing",
        work_centres=[{"id": "WC1", "available_min": 480}, {"id": "WC2", "available_min": 480}],
        routings={"P200": [op(10, "WC1", 15, 1), op(20, "WC2", 10, 2)]},
        work_orders=[{"id": "WO1", "product": "P200", "qty": 25, "release_min": 0, "priority": 1},
                     {"id": "WO2", "product": "P200", "qty": 15, "release_min": 0, "priority": 1}])

    # m05 — scrap where floor differs from rounding (1.5 -> 1, not 2)
    S["m05_scrap_floor"] = base("m05_scrap_floor",
        routings={"P100": [op(10, "WC1", 0, 1, ppm=15000)]},
        work_orders=[{"id": "WO1", "product": "P100", "qty": 100, "release_min": 0, "priority": 1}])

    # m06 — scrap compounding across two operations
    S["m06_scrap_chain"] = base("m06_scrap_chain",
        work_centres=[{"id": "WC1", "available_min": 480}, {"id": "WC2", "available_min": 480}],
        routings={"P300": [op(10, "WC1", 5, 1, ppm=50000), op(20, "WC2", 5, 1, ppm=50000)]},
        work_orders=[{"id": "WO1", "product": "P300", "qty": 200, "release_min": 0, "priority": 1}])

    # m07 — one operation must draw from three lots, FIFO by (received, id)
    S["m07_fifo_lots"] = base("m07_fifo_lots",
        routings={"P100": [op(10, "WC1", 0, 1, consumes=[{"material": "R1", "qty_per_unit": 1}])]},
        lots=[{"id": "LC", "material": "R1", "qty": 100, "received": 2},
              {"id": "LA", "material": "R1", "qty": 100, "received": 0},
              {"id": "LB", "material": "R1", "qty": 100, "received": 1}],
        work_orders=[{"id": "WO1", "product": "P100", "qty": 250, "release_min": 0, "priority": 1}])

    # m08 — a starved order stalls while a lower-priority one proceeds
    S["m08_stall"] = base("m08_stall",
        routings={"P100": [op(10, "WC1", 0, 1, consumes=[{"material": "R1", "qty_per_unit": 1}])]},
        lots=[{"id": "L1", "material": "R1", "qty": 100, "received": 0}],
        work_orders=[{"id": "WO1", "product": "P100", "qty": 500, "release_min": 0, "priority": 1},
                     {"id": "WO2", "product": "P100", "qty": 60, "release_min": 0, "priority": 2}])

    # m09 — staggered releases: a centre idles, then picks up the later order
    S["m09_release"] = base("m09_release",
        routings={"P100": [op(10, "WC1", 10, 1)]},
        work_orders=[{"id": "WO1", "product": "P100", "qty": 20, "release_min": 0, "priority": 1},
                     {"id": "WO2", "product": "P100", "qty": 20, "release_min": 200, "priority": 1}])

    # m10 — setup overhead dominates, dragging performance well below 1
    S["m10_setup_heavy"] = base("m10_setup_heavy",
        work_centres=[{"id": "WC1", "available_min": 200}],
        routings={"P100": [op(10, "WC1", 40, 1)]},
        work_orders=[{"id": f"WO{i}", "product": "P100", "qty": 10, "release_min": 0,
                      "priority": 1} for i in range(1, 4)])

    # m11 — everything: two centres, two products, scrap, materials, a stall
    S["m11_combined"] = base("m11_combined",
        work_centres=[{"id": "WC1", "available_min": 600}, {"id": "WC2", "available_min": 600}],
        routings={"P100": [op(10, "WC1", 15, 1, ppm=20000,
                              consumes=[{"material": "R1", "qty_per_unit": 2}]),
                           op(20, "WC2", 10, 1)],
                  "P200": [op(10, "WC2", 20, 2,
                              consumes=[{"material": "R2", "qty_per_unit": 1}])]},
        lots=[{"id": "L1", "material": "R1", "qty": 150, "received": 0},
              {"id": "L2", "material": "R1", "qty": 150, "received": 1},
              {"id": "L3", "material": "R2", "qty": 40, "received": 0}],
        work_orders=[{"id": "WO1", "product": "P100", "qty": 100, "release_min": 0, "priority": 1},
                     {"id": "WO2", "product": "P200", "qty": 30, "release_min": 0, "priority": 2},
                     {"id": "WO3", "product": "P100", "qty": 80, "release_min": 50, "priority": 1}])
    return S


def wellformed(name, s):
    wcs = {w["id"] for w in s["work_centres"]}
    for prod, route in s["routings"].items():
        seen = set()
        for o in route:
            if o["wc"] not in wcs:
                raise SystemExit(f"{name}: routing {prod} references an undeclared work centre {o['wc']}")
            if o["op"] in seen:
                raise SystemExit(f"{name}: routing {prod} operation number {o['op']} is repeated")
            seen.add(o["op"])
            if o["setup_min"] < 0 or o["run_min_per_unit"] < 0:
                raise SystemExit(f"{name}: routing {prod} has a negative operation time")
        if route != sorted(route, key=lambda x: x["op"]):
            raise SystemExit(f"{name}: routing {prod} operations are not in ascending order")
    for wo in s["work_orders"]:
        if wo["product"] not in s["routings"]:
            raise SystemExit(f"{name}: order {wo['id']} has a product with no routing")
        if wo["qty"] <= 0:
            raise SystemExit(f"{name}: order {wo['id']} has a non-positive quantity")
    ids = [w["id"] for w in s["work_orders"]]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{name}: duplicate order numbers; the dispatch key could not order them")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("scenarios", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, s in scenarios().items():
        wellformed(name, s)
        r = run(s)

        # guard: material balance must close on the reference's own numbers
        for inv in r["inventory"]:
            if inv["received"] - inv["consumed"] != inv["remaining"]:
                raise SystemExit(f"{name}: the reference answer itself does not balance materials {inv}")
        # guard: schedule order and finite capacity
        sch = r["schedule"]
        if sch != sorted(sch, key=lambda x: (x["start_min"], x["wc"], x["wo"])):
            raise SystemExit(f"{name}: the reference schedule is not sorted per the specification")
        by_wc = {}
        for x in sch:
            by_wc.setdefault(x["wc"], []).append((x["start_min"], x["end_min"], x["wo"]))
        for wc, ivs in by_wc.items():
            ivs.sort()
            for i in range(len(ivs) - 1):
                if ivs[i][1] > ivs[i + 1][0]:
                    raise SystemExit(f"{name}: on work centre {wc}, {ivs[i][2]} overlaps {ivs[i+1][2]}, "
                                     f"violating finite capacity")
        if not sch and not r["stalled"]:
            raise SystemExit(f"{name}: neither schedule nor stalls -- an empty check")

        (out / "scenarios" / f"{name}.json").write_text(json.dumps(s, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(r, indent=1))
        manifest.append(name)
        print("%-18s operations=%-3d stalls=%-2d materials=%-2d work centres=%d" % (
            name, len(sch), len(r["stalled"]), len(r["inventory"]), len(r["oee"])))

    for name in ("m01_single", "m05_scrap_floor", "m07_fifo_lots"):
        s = json.loads((out / "scenarios" / f"{name}.json").read_text())
        r = json.loads((out / "ref" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.scenario.json").write_text(json.dumps(s, indent=1))
        (out / "examples" / f"{name}.expected.json").write_text(json.dumps(r, indent=1))

    (out / "manifest.json").write_text(json.dumps({"scenarios": manifest}, indent=1))
    print(f"\n{len(manifest)} scenarios written to {out}")


if __name__ == "__main__":
    main()
