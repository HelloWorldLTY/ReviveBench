#!/usr/bin/env python3
"""Closed-form references for cfd_solver, plus the one tabulated benchmark.

This module is deliberately NOT a solver. Every quantity here is either algebra or a published
table, so there is no discretisation of mine for a candidate to disagree with. That inverts this
suite's dominant failure mode: across the other tasks the oracle was a program I wrote, and four of
the defects found so far were mine rather than the candidates'. Here the oracle is mathematics.

The only non-analytic reference is the Ghia, Ghia & Shin (1982) lid-driven-cavity table, which is
itself a 1982 numerical result and is therefore graded at a loose 3e-2 — it is a cross-check, not
ground truth.
"""
import math


# ---------------------------------------------------------------- analytic solutions

def poiseuille_u(y, H, mu, dpdx):
    """Plane Poiseuille: u(y) = -dpdx/(2 mu) y (H - y). Exact steady NS solution."""
    return -dpdx / (2.0 * mu) * y * (H - y)


def poiseuille_scalars(H, mu, dpdx):
    return {"u_center": poiseuille_u(H / 2.0, H, mu, dpdx),
            "Q": -dpdx * H ** 3 / (12.0 * mu)}


def couette_pg_u(y, H, mu, dpdx, U):
    """Couette + pressure gradient, superposition of the two exact solutions."""
    return U * y / H - dpdx / (2.0 * mu) * y * (H - y)


def taylor_green_uv(x, y, t, nu):
    """Exact unsteady incompressible NS solution on a periodic box."""
    d = math.exp(-2.0 * nu * t)
    return (math.sin(x) * math.cos(y) * d, -math.cos(x) * math.sin(y) * d)


def taylor_green_energy(t, nu, e0=None):
    """Kinetic energy decays as exp(-4 nu t). Mean of (u^2+v^2)/2 over the box is 1/4 at t=0."""
    if e0 is None:
        e0 = 0.25
    return e0 * math.exp(-4.0 * nu * t)


def burgers_travelling(x, t, u_l, u_r, nu, x0=0.0):
    """Viscous Burgers travelling wave; exact for the tanh profile.

    The wave is centred at x0 + s*t. Omitting x0 (as the first version did) silently assumes the
    profile starts at the origin, so with a case using x0=5 the reference described a different
    problem entirely and every correct solver looked ~300% wrong. The achievability probe caught it.
    """
    s = 0.5 * (u_l + u_r)
    return 0.5 * (u_l + u_r) - 0.5 * (u_l - u_r) * math.tanh(
        (x - x0 - s * t) * (u_l - u_r) / (4.0 * nu))


def shock_speed(u_l, u_r):
    """Rankine-Hugoniot speed for inviscid Burgers with flux u^2/2."""
    return 0.5 * (u_l + u_r)


def shock_position(x0, t, u_l, u_r):
    return x0 + shock_speed(u_l, u_r) * t


def shock_integral(L, x0, t, u_l, u_r):
    """Exact integral of u over [0,L] for the Riemann problem — conserved in the flux form."""
    xs = shock_position(x0, t, u_l, u_r)
    xs = min(max(xs, 0.0), L)
    return u_l * xs + u_r * (L - xs)


def neo_hookean(mu, lam):
    """Incompressible neo-Hookean uniaxial extension — pure algebra, no discretisation."""
    return {"P_nominal": mu * (lam - 1.0 / lam ** 2),
            "sigma_cauchy": mu * (lam ** 2 - 1.0 / lam),
            "W": mu / 2.0 * (lam ** 2 + 2.0 / lam - 3.0)}


# ---------------------------------------------------------------- tabulated benchmark

# Ghia, Ghia & Shin (1982), Table I/II. u along the vertical centreline and v along the
# horizontal centreline, at the paper's sample points, for Re = 100 and Re = 400.
GHIA_Y = [0.0000, 0.0547, 0.0625, 0.0703, 0.1016, 0.1719, 0.2813, 0.4531,
          0.5000, 0.6172, 0.7344, 0.8516, 0.9531, 0.9609, 0.9688, 0.9766, 1.0000]
GHIA_U = {
    100: [0.00000, -0.03717, -0.04192, -0.04775, -0.06434, -0.10150, -0.15662, -0.21090,
          -0.20581, -0.13641, 0.00332, 0.23151, 0.68717, 0.73722, 0.78871, 0.84123, 1.00000],
    400: [0.00000, -0.08186, -0.09266, -0.10338, -0.14612, -0.24299, -0.32726, -0.17119,
          -0.11477, 0.02135, 0.16256, 0.29093, 0.55892, 0.61756, 0.68439, 0.75837, 1.00000],
}
GHIA_X = [0.0000, 0.0625, 0.0703, 0.0781, 0.0938, 0.1563, 0.2266, 0.2344,
          0.5000, 0.8047, 0.8594, 0.9063, 0.9453, 0.9531, 0.9609, 0.9688, 1.0000]
GHIA_V = {
    100: [0.00000, 0.09233, 0.10091, 0.10890, 0.12317, 0.16077, 0.17507, 0.17527,
          0.05454, -0.24533, -0.22445, -0.16914, -0.10313, -0.08864, -0.07391, -0.05906, 0.00000],
    400: [0.00000, 0.18360, 0.19713, 0.20920, 0.22965, 0.28124, 0.30203, 0.30174,
          0.05186, -0.38598, -0.44993, -0.23827, -0.22847, -0.19254, -0.15663, -0.12146, 0.00000],
}


# ---------------------------------------------------------------- grading helpers

def rel_l2(got, want):
    """Relative L2 error. Falls back to absolute norm when the reference is ~zero."""
    if len(got) != len(want):
        return float("inf")
    num = math.sqrt(sum((a - b) ** 2 for a, b in zip(got, want)))
    den = math.sqrt(sum(b * b for b in want))
    return num / den if den > 1e-14 else num


def reference(case):
    """Return {'fields': {...}, 'scalars': {...}} for a case, from closed form or the table."""
    k, p = case["kind"], case["params"]
    if k == "poiseuille":
        ys = case["probe_y"]
        return {"fields": {"u_at_probe_y": [poiseuille_u(y, p["H"], p["mu"], p["dpdx"]) for y in ys]},
                "scalars": poiseuille_scalars(p["H"], p["mu"], p["dpdx"])}
    if k == "couette_pg":
        ys = case["probe_y"]
        return {"fields": {"u_at_probe_y": [couette_pg_u(y, p["H"], p["mu"], p["dpdx"], p["U"])
                                            for y in ys]},
                "scalars": {"u_center": couette_pg_u(p["H"] / 2, p["H"], p["mu"], p["dpdx"], p["U"])}}
    if k == "taylor_green":
        t, nu = p["t_end"], p["nu"]
        pts = case["probe_xy"]
        us = [taylor_green_uv(x, y, t, nu)[0] for (x, y) in pts]
        vs = [taylor_green_uv(x, y, t, nu)[1] for (x, y) in pts]
        return {"fields": {"u_at_probe": us, "v_at_probe": vs},
                "scalars": {"kinetic_energy": taylor_green_energy(t, nu)}}
    if k == "burgers_viscous":
        t = p["t_end"]
        xs = case["probe_x"]
        return {"fields": {"u_at_probe_x": [
            burgers_travelling(x, t, p["u_l"], p["u_r"], p["nu"], p.get("x0", 0.0))
            for x in xs]}, "scalars": {}}
    if k == "burgers_shock":
        t = p["t_end"]
        return {"fields": {},
                "scalars": {"shock_position": shock_position(p["x0"], t, p["u_l"], p["u_r"]),
                            "u_left": p["u_l"], "u_right": p["u_r"],
                            "integral_u": shock_integral(p["L"], p["x0"], t, p["u_l"], p["u_r"])}}
    if k == "hyperelastic_bar":
        return {"fields": {}, "scalars": neo_hookean(p["mu"], p["lambda"])}
    raise SystemExit(f"analytic: unknown kind {k!r}")
