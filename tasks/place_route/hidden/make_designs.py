#!/usr/bin/env python3
"""Build the hidden design set for place_route and the reference solutions.

Emits, into hidden/:
    designs/<name>.json            the design handed to the candidate
    ref/<name>.json                the reference solution's metrics (hpwl, routed_len)
    examples/<name>.design.json    three worked examples copied into the workspace
    examples/<name>.solution.json  ... with a legal reference layout
    manifest.json                  the design list

Three guards, each earned from a defect on an earlier task:

  * every design must be solvable by the reference flow, and the resulting layout must pass the
    independent checker — otherwise the asset is unsolvable and every candidate fails for my
    reason, not theirs;
  * every cell's pins must satisfy the SPEC's interior-offset rule (1 <= px <= w-1), which is what
    makes pin collisions impossible when cells abut;
  * capacity sanity: total cell width must fit in the rows that blockages leave free, so a design
    is never impossible by arithmetic.

usage: make_designs.py [--out <hidden dir>]
"""
import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ref_pnr import check_layout, solve  # noqa: E402

# Interior pins only: 1 <= px <= w-1. See SPEC §2.
LIB = {
    "INV":  {"w": 3, "h": 10, "pins": {"A": [1, 5], "Y": [2, 5]}},
    "BUF":  {"w": 3, "h": 10, "pins": {"A": [1, 3], "Y": [2, 7]}},
    "ND2":  {"w": 4, "h": 10, "pins": {"A": [1, 3], "B": [1, 7], "Y": [3, 5]}},
    "NR2":  {"w": 4, "h": 10, "pins": {"A": [1, 7], "B": [1, 3], "Y": [3, 5]}},
    "AOI":  {"w": 6, "h": 10, "pins": {"A": [1, 3], "B": [1, 7], "C": [3, 5], "Y": [5, 5]}},
    "DFF":  {"w": 8, "h": 10, "pins": {"D": [1, 5], "CK": [3, 1], "Q": [7, 5]}},
}


def chain(name, die, insts, nets, blockages=(), site=1):
    return {"name": name, "die": die, "row_height": 10, "site_width": site,
            "cells": LIB, "instances": insts, "blockages": list(blockages),
            "nets": nets, "layers": 2}


def line_of(cells, prefix="u"):
    return [{"id": f"{prefix}{i+1}", "cell": c} for i, c in enumerate(cells)]


def pairwise_nets(insts, out_pin="Y", in_pin="A", prefix="n"):
    nets = []
    for i in range(len(insts) - 1):
        a, b = insts[i], insts[i + 1]
        if out_pin in LIB[a["cell"]]["pins"] and in_pin in LIB[b["cell"]]["pins"]:
            nets.append({"name": f"{prefix}{i+1}",
                         "pins": [[a["id"], out_pin], [b["id"], in_pin]]})
    return nets


def free_pins(insts, nets, want):
    """Pick `want` instance pins that no existing net already claims.

    SPEC §2 allows each instance pin in at most one net. Hand-enumerating the leftovers works for a
    fixed cell list but not for d12, whose cells are drawn at random — and getting it wrong there
    produced exactly the violation the generator's guard now rejects. Picking programmatically makes
    the property hold by construction instead of by my inspection.
    """
    used = {(iid, pin) for n in nets for (iid, pin) in n["pins"]}
    out = [[it["id"], p] for it in insts for p in LIB[it["cell"]]["pins"]
           if (it["id"], p) not in used]
    if len(out) < want:
        raise SystemExit(f"make_designs: only {len(out)} free pins available, fewer than the {want} needed")
    # Sample across instances so the extra nets really cross the layout instead of bunching up
    step = max(1, len(out) // want)
    return [out[k * step] for k in range(want)]


def designs():
    D = {}
    rng = random.Random(20260910)

    # d01 — the floor: two cells, one net
    i = line_of(["INV", "ND2"])
    D["d01_pair"] = chain("d01_pair", {"w": 30, "h": 20}, i, pairwise_nets(i))

    # d02 — a single row, several cells in a chain
    i = line_of(["INV", "BUF", "ND2", "INV", "NR2"])
    D["d02_row"] = chain("d02_row", {"w": 40, "h": 10}, i, pairwise_nets(i))

    # d03 — two rows, chain wraps across the row boundary (forces layer-2 travel)
    i = line_of(["INV", "ND2", "BUF", "NR2", "INV", "ND2"])
    D["d03_tworow"] = chain("d03_tworow", {"w": 22, "h": 20}, i, pairwise_nets(i))

    # d04 — blockage splits a row into two segments
    i = line_of(["INV", "BUF", "INV", "ND2", "NR2"])
    D["d04_split"] = chain("d04_split", {"w": 50, "h": 20}, i, pairwise_nets(i),
                           blockages=[{"x": 18, "y": 0, "w": 14, "h": 10}])

    # d05 — a 6-pin net
    i = line_of(["INV"] * 6)
    nets = [{"name": "big", "pins": [[f"u{k}", "A"] for k in range(1, 7)]}]
    nets += [{"name": "t1", "pins": [["u1", "Y"], ["u2", "Y"]]}]
    D["d05_multipin"] = chain("d05_multipin", {"w": 40, "h": 30}, i, nets)

    # d06 — site_width 2, so x must be even
    i = line_of(["INV", "ND2", "INV", "BUF"])
    D["d06_site2"] = chain("d06_site2", {"w": 40, "h": 20}, i, pairwise_nets(i), site=2)

    # d07 — DFF cells (widest) mixed with small ones: greedy packing must not strand them
    i = line_of(["DFF", "INV", "DFF", "ND2", "INV", "DFF"])
    nets = [{"name": "q1", "pins": [["u1", "Q"], ["u2", "A"]]},
            {"name": "q2", "pins": [["u3", "Q"], ["u4", "A"]]},
            {"name": "q3", "pins": [["u6", "Q"], ["u5", "A"]]},
            {"name": "clk", "pins": [["u1", "CK"], ["u3", "CK"], ["u6", "CK"]]}]
    D["d07_dff"] = chain("d07_dff", {"w": 40, "h": 30}, i, nets)

    # d08 — exactly full rows: total width == die width * rows, zero slack
    i = line_of(["INV", "INV", "ND2", "INV", "INV", "ND2"])   # 3+3+4+3+3+4 = 20
    D["d08_tight"] = chain("d08_tight", {"w": 10, "h": 20}, i, pairwise_nets(i))

    # d09 — two blockages, one per row, staggered
    i = line_of(["INV", "BUF", "ND2", "NR2", "INV", "BUF"])
    D["d09_blockages"] = chain("d09_blockages", {"w": 46, "h": 20}, i, pairwise_nets(i),
                               blockages=[{"x": 10, "y": 0, "w": 8, "h": 10},
                                          {"x": 28, "y": 10, "w": 8, "h": 10}])

    # d10 — congested: many nets crossing in a narrow die, forces detours
    i = line_of(["INV", "ND2", "INV", "ND2", "INV", "ND2", "INV", "ND2"])
    nets = pairwise_nets(i)
    # Extra cross-connect nets take pins the chain leaves free, chosen programmatically (see free_pins)
    extra = free_pins(i, nets, 4)
    nets += [{"name": "x1", "pins": [extra[0], extra[3]]},
             {"name": "x2", "pins": [extra[1], extra[2]]}]
    D["d10_congested"] = chain("d10_congested", {"w": 32, "h": 30}, i, nets)

    # d11 — AOI cells with four pins each, three rows
    i = line_of(["AOI", "AOI", "INV", "AOI", "BUF", "ND2"])
    nets = [{"name": "a1", "pins": [["u1", "Y"], ["u2", "A"]]},
            {"name": "a2", "pins": [["u2", "Y"], ["u3", "A"]]},
            {"name": "a3", "pins": [["u3", "Y"], ["u4", "B"]]},
            {"name": "a4", "pins": [["u4", "Y"], ["u5", "A"]]},
            {"name": "a5", "pins": [["u5", "Y"], ["u6", "A"]]},
            {"name": "a6", "pins": [["u1", "C"], ["u4", "C"], ["u6", "B"]]}]
    D["d11_aoi"] = chain("d11_aoi", {"w": 34, "h": 30}, i, nets)

    # d12 — the largest: 12 instances, 4 rows, mixed library, one blockage
    cells = [rng.choice(["INV", "BUF", "ND2", "NR2", "AOI"]) for _ in range(12)]
    i = line_of(cells)
    nets = pairwise_nets(i)
    nets.append({"name": "spine", "pins": free_pins(i, nets, 3)})
    D["d12_mixed"] = chain("d12_mixed", {"w": 44, "h": 40}, i, nets,
                           blockages=[{"x": 20, "y": 20, "w": 10, "h": 10}])
    return D


def capacity_ok(d):
    """Total cell width must fit the row space blockages leave free."""
    rh = d["row_height"]
    rows = d["die"]["h"] // rh
    free = 0
    for k in range(rows):
        y0, y1 = k * rh, (k + 1) * rh
        blocked = sum(b["w"] for b in d["blockages"]
                      if b["y"] < y1 and y0 < b["y"] + b["h"])
        free += d["die"]["w"] - blocked
    need = sum(d["cells"][it["cell"]]["w"] for it in d["instances"])
    return need <= free, need, free


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("designs", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    # guard: the library itself must satisfy the interior-pin rule
    for cname, c in LIB.items():
        for pname, (px, py) in c["pins"].items():
            if not (1 <= px <= c["w"] - 1):
                raise SystemExit(f"make_designs: {cname}.{pname} offset {px} violates pin interiority "
                                 f"(1..{c['w']-1}); pins of adjacent cells would coincide")
            if not (0 <= py < c["h"]):
                raise SystemExit(f"make_designs: {cname}.{pname} y offset {py} exceeds the cell height")

    manifest = []
    for name, d in designs().items():
        # Guard: SPEC §2 says an instance pin belongs to at most one net. d10 first gave u7.A to both the
        # chain net and an extra net, while the reference flow reported coincident pins, which misled a
        # round of debugging.
        seen = {}
        for net in d["nets"]:
            for (iid, pin) in net["pins"]:
                if (iid, pin) in seen:
                    raise SystemExit(f"make_designs: {name} pin {iid}.{pin} belongs to both "
                                     f"{seen[(iid,pin)]} and {net['name']}, violating SPEC §2")
                seen[(iid, pin)] = net["name"]
        ok, need, free = capacity_ok(d)
        if not ok:
            raise SystemExit(f"make_designs: {name} lacks capacity, needs {need} with {free} available; the design is unplaceable")
        sol = solve(d)                      # the reference flow must be able to solve it
        probs, met = check_layout(d, sol)   # and the solution must pass the independent checker
        if probs:
            raise SystemExit(f"make_designs: {name} reference solution violates the rules -> {probs[:2]}, "
                             f"fix the asset before generating the reference answer")
        (out / "designs" / f"{name}.json").write_text(json.dumps(d, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(
            {"name": name, "hpwl": met["hpwl"], "routed_len": met["routed_len"],
             "n_instances": len(d["instances"]), "n_nets": len(d["nets"])}, indent=1))
        manifest.append(name)
        print("%-16s cells=%-3d nets=%-3d used=%d/%d  hpwl=%-5d routed=%d" % (
            name, len(d["instances"]), len(d["nets"]), need, free,
            met["hpwl"], met["routed_len"]))

    for name in ("d01_pair", "d04_split", "d05_multipin"):
        d = json.loads((out / "designs" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.design.json").write_text(json.dumps(d, indent=1))
        (out / "examples" / f"{name}.solution.json").write_text(json.dumps(solve(d), indent=1))

    (out / "manifest.json").write_text(json.dumps({"designs": manifest}, indent=1))
    print(f"\n{len(manifest)} designs written to {out}")


if __name__ == "__main__":
    main()
