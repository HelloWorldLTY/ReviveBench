#!/usr/bin/env python3
"""Build the hidden case set for cfd_solver and its reference answers.

Emits, into hidden/:
    cases/<name>.json           the case handed to the candidate
    ref/<name>.json             the reference answer, from closed form (or the Ghia table)
    examples/<name>.case.json   three worked examples copied into the workspace
    examples/<name>.expected.json
    manifest.json

Every reference here comes from `analytic.py`, which is algebra and one published table rather than
a solver of mine. That is deliberate: across the earlier tasks in this suite the oracle was a
program I wrote, and several of the defects found were mine rather than the candidates'. The one
residual risk is that a *case* is ill-posed rather than that the formula is wrong, so the guards
below check well-posedness — the shock must still be inside the domain, stretches must be positive,
viscosities non-zero, and every reference value finite.

usage: make_cases.py [--out <hidden dir>]
"""
import argparse
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from analytic import reference, shock_position  # noqa: E402


def cases():
    C = {}

    # --- steady analytic flows: a second-order scheme is EXACT on a quadratic profile,
    #     so the tolerance is tight and the coarse grid is not a handicap but a probe.
    C["c01_poiseuille"] = {
        "kind": "poiseuille", "params": {"H": 1.0, "mu": 0.1, "dpdx": -2.0, "ny": 129},
        "probe_y": [0.125, 0.25, 0.5, 0.75, 0.875],
        "report": ["u_at_probe_y", "u_center", "Q"]}

    C["c02_poiseuille_coarse"] = {
        "kind": "poiseuille", "params": {"H": 1.0, "mu": 0.1, "dpdx": -2.0, "ny": 9},
        "probe_y": [0.125, 0.375, 0.5, 0.625, 0.875],
        "report": ["u_at_probe_y", "u_center", "Q"]}

    C["c03_poiseuille_thick"] = {
        "kind": "poiseuille", "params": {"H": 2.0, "mu": 0.35, "dpdx": -1.7, "ny": 65},
        "probe_y": [0.25, 0.75, 1.0, 1.25, 1.75],
        "report": ["u_at_probe_y", "u_center", "Q"]}

    C["c04_couette_pg"] = {
        "kind": "couette_pg",
        "params": {"H": 2.0, "mu": 0.35, "dpdx": -1.7, "U": 1.3, "ny": 65},
        "probe_y": [0.25, 0.75, 1.0, 1.5, 1.75],
        "report": ["u_at_probe_y", "u_center"]}

    C["c05_couette_adverse"] = {   # adverse gradient: profile reverses near the lower wall
        "kind": "couette_pg",
        "params": {"H": 1.0, "mu": 0.2, "dpdx": 1.5, "U": 1.0, "ny": 65},
        "probe_y": [0.125, 0.25, 0.5, 0.75, 0.875],
        "report": ["u_at_probe_y", "u_center"]}

    # --- unsteady: the long case punishes a first-order-in-time scheme
    # Probe points must sit on grid nodes. Off-node values can only be interpolated, and at n=64 bilinear
    # interpolation is off by about 1e-2, far beyond the stated 2e-3 threshold -- the same cause as the
    # Poiseuille failures.
    _TGN = 64
    probe = [[2 * math.pi * i / _TGN, 2 * math.pi * j / _TGN]
             for (i, j) in ((8, 4), (16, 12), (24, 24), (36, 16), (44, 40))]
    C["c06_taylor_green"] = {
        "kind": "taylor_green", "params": {"nu": 0.05, "t_end": 0.5, "n": 64},
        "probe_xy": probe, "report": ["u_at_probe", "v_at_probe", "kinetic_energy", "max_div"]}

    C["c07_taylor_green_long"] = {
        "kind": "taylor_green", "params": {"nu": 0.02, "t_end": 4.0, "n": 64},
        "probe_xy": probe, "report": ["u_at_probe", "v_at_probe", "kinetic_energy", "max_div"]}

    # --- nonlinear transport
    C["c08_burgers_viscous"] = {
        "kind": "burgers_viscous",
        "params": {"L": 10.0, "u_l": 1.0, "u_r": 0.2, "nu": 0.05, "t_end": 2.0, "nx": 401,
                   "x0": 5.0},
        "probe_x": [3.0, 4.5, 6.0, 7.0, 8.0], "report": ["u_at_probe_x"]}

    C["c09_burgers_thin"] = {      # thinner internal layer: needs the resolution it is given
        "kind": "burgers_viscous",
        "params": {"L": 10.0, "u_l": 1.0, "u_r": 0.2, "nu": 0.02, "t_end": 1.5, "nx": 801,
                   "x0": 5.0},
        "probe_x": [4.0, 5.0, 5.9, 6.5, 7.5], "report": ["u_at_probe_x"]}

    # --- shock: a non-conservative scheme puts it in the wrong place
    C["c10_burgers_shock"] = {
        "kind": "burgers_shock",
        "params": {"L": 10.0, "u_l": 1.0, "u_r": 0.2, "x0": 3.0, "t_end": 2.0, "nx": 800},
        "report": ["shock_position", "u_left", "u_right", "integral_u"]}

    C["c11_burgers_shock_strong"] = {
        "kind": "burgers_shock",
        "params": {"L": 12.0, "u_l": 2.0, "u_r": -0.5, "x0": 4.0, "t_end": 3.0, "nx": 1200},
        "report": ["shock_position", "u_left", "u_right", "integral_u"]}

    # --- finite strain: pure algebra, tightest tolerance in the suite
    C["c12_hyperelastic_tension"] = {
        "kind": "hyperelastic_bar", "params": {"mu": 0.8, "lambda": 1.6},
        "report": ["P_nominal", "sigma_cauchy", "W"]}

    C["c13_hyperelastic_compression"] = {
        "kind": "hyperelastic_bar", "params": {"mu": 2.5, "lambda": 0.7},
        "report": ["P_nominal", "sigma_cauchy", "W"]}

    return C


def wellposed(name, c):
    """Guards against an ill-posed case, which would fail every correct solver."""
    p = c["params"]
    k = c["kind"]
    if k in ("poiseuille", "couette_pg"):
        if p["mu"] <= 0 or p["H"] <= 0:
            raise SystemExit(f"{name}: mu and H must be positive")
        if p["ny"] < 5 or p["ny"] % 2 == 0:
            raise SystemExit(f"{name}: ny={p['ny']} must be an odd number >=5 so the centreline lands on a grid node")
    if k == "taylor_green":
        if p["nu"] <= 0 or p["t_end"] <= 0:
            raise SystemExit(f"{name}: nu and t_end must be positive")
    if k == "burgers_viscous":
        if p["nu"] <= 0:
            raise SystemExit(f"{name}: nu must be positive for a viscous case")
        # the inner-layer thickness ~ 4 nu/(u_l-u_r) needs several grid points to be resolved
        thick = 4.0 * p["nu"] / (p["u_l"] - p["u_r"])
        dx = p["L"] / (p["nx"] - 1)
        if thick < 3 * dx:
            raise SystemExit(f"{name}: inner-layer thickness {thick:.4f} is under 3 cells {dx:.4f}; the case is under-resolved")
    if k == "burgers_shock":
        if p["u_l"] <= p["u_r"]:
            raise SystemExit(f"{name}: a shock forms only when u_l > u_r")
        xs = shock_position(p["x0"], p["t_end"], p["u_l"], p["u_r"])
        if not (0.0 < xs < p["L"]):
            raise SystemExit(f"{name}: at t_end the shock sits at {xs:.3f}, outside [0,{p['L']}], "
                             f"so the flux-balance identity no longer applies")
    if k == "hyperelastic_bar":
        if p["lambda"] <= 0 or p["mu"] <= 0:
            raise SystemExit(f"{name}: lambda and mu must be positive")
    if k in ("poiseuille", "couette_pg"):
        dy = p["H"] / (p["ny"] - 1)
        for y in c["probe_y"]:
            if abs(y / dy - round(y / dy)) > 1e-9:
                raise SystemExit(f"{name}: probe y={y} is not on a grid node (dy={dy}), "
                                 f"so interpolation would add O(dy^2) error and 1e-6 would be unreachable")
    if k == "taylor_green":
        d = 2.0 * math.pi / p["n"]
        for (x, y) in c["probe_xy"]:
            if abs(x / d - round(x / d)) > 1e-9 or abs(y / d - round(y / d)) > 1e-9:
                raise SystemExit(f"{name}: probe ({x:.4f},{y:.4f}) is not on a grid node (d={d:.6f}), "
                                 f"so the interpolation error would exceed 2e-3")
    if k == "burgers_shock":
        dx = p["L"] / p["nx"]
        if abs(p["x0"] / dx - round(p["x0"] / dx)) > 1e-9:
            raise SystemExit(f"{name}: x0={p['x0']} is not on a grid face (dx={dx}), "
                             f"so the initial discrete integral differs from the analytic value by ~dx and flux balance 1e-8 is unreachable")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("cases", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, c in cases().items():
        c = dict(c, name=name)
        wellposed(name, c)
        ref = reference(c)
        # Guard: every reference value must be finite, and every key named in report must exist
        for group in ("fields", "scalars"):
            for k, v in ref.get(group, {}).items():
                vals = v if isinstance(v, list) else [v]
                if any(not math.isfinite(float(x)) for x in vals):
                    raise SystemExit(f"{name}: reference quantity {k} contains a non-finite value")
        missing = [k for k in c["report"]
                   if k not in ref.get("fields", {}) and k not in ref.get("scalars", {})
                   and k != "max_div"]        # max_div is self-reported by the candidate; no analytic reference
        if missing:
            raise SystemExit(f"{name}: report asks for {missing}, which the analytic reference does not provide")
        (out / "cases" / f"{name}.json").write_text(json.dumps(c, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(ref, indent=1))
        manifest.append(name)
        nf = sum(len(v) if isinstance(v, list) else 1 for v in ref.get("fields", {}).values())
        ns = len(ref.get("scalars", {}))
        print("%-26s %-16s fields=%-4d scalars=%-2d" % (name, c["kind"], nf, ns))

    for name in ("c01_poiseuille", "c08_burgers_viscous", "c12_hyperelastic_tension"):
        c = json.loads((out / "cases" / f"{name}.json").read_text())
        r = json.loads((out / "ref" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.case.json").write_text(json.dumps(c, indent=1))
        (out / "examples" / f"{name}.expected.json").write_text(json.dumps(r, indent=1))

    (out / "manifest.json").write_text(json.dumps({"cases": manifest}, indent=1))
    print(f"\n{len(manifest)} cases written to {out}")


if __name__ == "__main__":
    main()
