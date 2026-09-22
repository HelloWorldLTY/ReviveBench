#!/usr/bin/env python3
"""Reference MES core — oracle for mes_exec and the calibration kernel.

Deterministic integer-timed discrete-event scheduling, so the reference answer is not an
approximation of the truth, it *is* the truth as the spec defines it. As with scada_dcs, that puts
the whole burden on the spec being unambiguous and this file matching it, which is why the self-test
beside it checks hand-computed schedules and material balances rather than merely re-running this.

The four subtle points, and therefore the four to read carefully:

  * the dispatch key is (priority, release_min, wo_id, op) and it is consulted at every moment a
    work centre frees up — not once at release;
  * setup is incurred on EVERY run, with no carry-over between consecutive orders of one product,
    which is what drags `performance` below 1;
  * scrap uses floor(qty_in * ppm / 1e6), so a rate that would round up must still floor down;
  * lots are consumed FIFO by (received, lot id) and one operation may draw from several lots; if
    material is short the work order stalls and schedules nothing further.

usage: ref_mes.py <scenario.json> <out.json>
"""
import json
import math
import pathlib
import sys


def run(scen):
    wcs = {w["id"]: dict(w) for w in scen["work_centres"]}
    routings = scen["routings"]
    lots = sorted((dict(l) for l in scen["lots"]), key=lambda l: (l["received"], l["id"]))
    for l in lots:
        l["remaining"] = l["qty"]

    received = {}
    for l in lots:
        received[l["material"]] = received.get(l["material"], 0) + l["qty"]
    consumed = {m: 0 for m in received}

    # per work order: current op index, quantity in hand, ready time
    wo_state = {}
    for wo in scen["work_orders"]:
        wo_state[wo["id"]] = {"wo": dict(wo), "idx": 0, "qty": wo["qty"],
                              "ready": wo["release_min"], "stalled": False, "done": False}

    wc_free = {w: 0 for w in wcs}
    schedule, genealogy, stalled = [], {w["id"]: [] for w in scen["work_orders"]}, []
    busy = {w: {"setup": 0, "run": 0, "ideal": 0, "in": 0, "good": 0} for w in wcs}

    def take_material(material, need, wo_id, dry_run=False):
        """FIFO by (received, id). Returns list of (lot_id, qty) or None when short."""
        picks, left = [], need
        for l in lots:
            if l["material"] != material or l["remaining"] <= 0:
                continue
            take = min(l["remaining"], left)
            picks.append((l["id"], take))
            left -= take
            if left == 0:
                break
        if left > 0:
            return None
        if not dry_run:
            for (lid, q) in picks:
                for l in lots:
                    if l["id"] == lid:
                        l["remaining"] -= q
                        break
                consumed[material] = consumed.get(material, 0) + q
                genealogy[wo_id].append({"lot": lid, "material": material, "qty": q})
        return picks

    while True:
        # candidate operations: not done, not stalled, routing remaining
        cands = []
        for wid, st in wo_state.items():
            if st["done"] or st["stalled"]:
                continue
            route = routings[st["wo"]["product"]]
            if st["idx"] >= len(route):
                st["done"] = True
                continue
            op = route[st["idx"]]
            start = max(st["ready"], wc_free[op["wc"]])
            cands.append((st["wo"]["priority"], st["wo"]["release_min"], wid, op["op"],
                          start, op, st))
        if not cands:
            break

        # the machine that frees earliest decides; among operations that could start then,
        # the dispatch key picks. Sorting by (start, key) reproduces exactly that.
        cands.sort(key=lambda c: (c[4], c[0], c[1], c[2], c[3]))
        _, _, wid, opno, start, op, st = cands[0]

        # materials first — a shortage stalls the order without occupying the machine
        short = False
        for req in op.get("consumes", []):
            need = st["qty"] * req["qty_per_unit"]
            if take_material(req["material"], need, wid, dry_run=True) is None:
                short = True
                break
        if short:
            st["stalled"] = True
            stalled.append(wid)
            continue
        for req in op.get("consumes", []):
            take_material(req["material"], st["qty"] * req["qty_per_unit"], wid)

        qty_in = st["qty"]
        run_min = math.ceil(qty_in) * op["run_min_per_unit"]
        dur = op["setup_min"] + run_min
        end = start + dur
        scrapped = (qty_in * op.get("scrap_ppm", 0)) // 1_000_000
        qty_out = qty_in - scrapped

        schedule.append({"wo": wid, "op": opno, "wc": op["wc"], "start_min": start,
                         "end_min": end, "qty_in": qty_in, "qty_out": qty_out})
        b = busy[op["wc"]]
        b["setup"] += op["setup_min"]
        b["run"] += dur
        b["ideal"] += run_min
        b["in"] += qty_in
        b["good"] += qty_out

        wc_free[op["wc"]] = end
        st["ready"] = end
        st["qty"] = qty_out
        st["idx"] += 1
        if st["idx"] >= len(routings[st["wo"]["product"]]):
            st["done"] = True

    schedule.sort(key=lambda s: (s["start_min"], s["wc"], s["wo"]))
    inventory = [{"material": m, "received": received[m], "consumed": consumed.get(m, 0),
                  "remaining": received[m] - consumed.get(m, 0)}
                 for m in sorted(received)]
    oee = []
    for w in sorted(wcs):
        b = busy[w]
        avail = wcs[w]["available_min"]
        a = b["run"] / avail if avail else 0.0
        p = b["ideal"] / b["run"] if b["run"] else 0.0
        q = b["good"] / b["in"] if b["in"] else 0.0
        oee.append({"wc": w, "availability": a, "performance": p, "quality": q,
                    "oee": a * p * q})
    return {"schedule": schedule,
            "genealogy": [{"wo": w, "consumed": genealogy[w]} for w in sorted(genealogy)],
            "stalled": sorted(stalled), "inventory": inventory, "oee": oee}


def main():
    scen = json.loads(pathlib.Path(sys.argv[1]).read_text())
    pathlib.Path(sys.argv[2]).write_text(json.dumps(run(scen), indent=1))


if __name__ == "__main__":
    main()
