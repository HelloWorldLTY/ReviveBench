#!/usr/bin/env python3
"""Reference CFD solver for cfd_solver — calibration kernel and achievability probe.

This is NOT the oracle. The oracle is `analytic.py`: closed-form solutions and one published table.
This file is just a competent implementation, and its job is to answer a question calibration alone
cannot: *are the stated tolerances reachable by the route the SPEC tells candidates to take?*

That question has bitten this suite before. On the EDA synthesis task the calibration scored full
marks while a 0.9 threshold silently let a netlist with witnessed counterexamples pass; on cad3d an
achievability probe showed mesh-derived mass properties miss 0.5% at coarse tessellation and clear
it at finer. Here the risk is the mirror image: tolerances asserted from theory (1e-6 for Poiseuille
at ny=9, 2e-3 for Taylor-Green at n=64) that no real scheme can hit would fail every correct
candidate, and a calibration against my own analytic formulas would never reveal it.

Schemes, all second order in space:
  poiseuille / couette_pg : solve mu u'' = dpdx by the Thomas algorithm. Central differences are
                            exact for a quadratic, so this is exact at the nodes even at ny=9 —
                            which is precisely what the coarse case is probing.
  taylor_green            : pseudo-spectral vorticity solver, Heun in time, 2/3 dealiasing, with
                            velocity recovered from the streamfunction so the divergence is zero to
                            round-off by construction. An earlier version returned the analytic
                            answer and reported max_div = 0.0 outright, which made the probe compare
                            the closed form against itself and prove nothing.
  burgers_viscous         : explicit conservative flux form + central viscous term.
  burgers_shock           : Godunov flux (exact Riemann solver for Burgers), conservative.
  hyperelastic_bar        : algebra.

(The lid-driven cavity was dropped from the case set: I could not demonstrate its tolerance was
reachable, and its runtime was prohibitive. solve_cavity below is now unreachable.)

usage: ref_flow.py <case.json> <out.json>
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from analytic import GHIA_U, GHIA_V, taylor_green_uv, taylor_green_energy  # noqa: E402


# ---------------------------------------------------------------- linear algebra

def thomas(a, b, c, d):
    """Solve a tridiagonal system in O(n). a: sub, b: diag, c: super, d: rhs."""
    n = len(d)
    cc, dd = [0.0] * n, [0.0] * n
    cc[0] = c[0] / b[0]
    dd[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cc[i - 1]
        cc[i] = c[i] / m if i < n - 1 else 0.0
        dd[i] = (d[i] - a[i] * dd[i - 1]) / m
    x = [0.0] * n
    x[-1] = dd[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dd[i] - cc[i] * x[i + 1]
    return x


def simpson(xs, ys):
    """Composite Simpson. Exact for a quadratic, which is what the channel profile is.

    The trapezoid rule is NOT exact for a parabola — its O(dy^2) error was the sole reason Q missed
    the 1e-6 tolerance (1.6e-2 at ny=9). The node-alignment fix cured the probe values but left this
    untouched, so the case still failed for a second, independent reason.
    """
    n = len(xs) - 1
    if n % 2:
        raise SystemExit("simpson: needs an even number of intervals (odd ny), which the guard ensures")
    h = (xs[-1] - xs[0]) / n
    s = ys[0] + ys[-1] + 4.0 * sum(ys[i] for i in range(1, n, 2)) + \
        2.0 * sum(ys[i] for i in range(2, n, 2))
    return s * h / 3.0


def interp(xs, ys, x):
    """Linear interpolation onto a probe point; grids here always bracket the probes."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] * (1 - t) + ys[hi] * t


# ---------------------------------------------------------------- solvers

def solve_channel(p, probe_y, couette=False):
    """mu u'' = dpdx with u(0)=0, u(H)=U. Central differences: exact for the quadratic."""
    H, mu, dpdx, ny = p["H"], p["mu"], p["dpdx"], p["ny"]
    U = p.get("U", 0.0) if couette else 0.0
    dy = H / (ny - 1)
    ys = [i * dy for i in range(ny)]
    n = ny - 2                                   # interior unknowns
    a = [1.0] * n
    b = [-2.0] * n
    c = [1.0] * n
    d = [dpdx / mu * dy * dy] * n
    d[-1] -= U                                   # top Dirichlet
    a[0] = 0.0
    c[-1] = 0.0
    u_in = thomas(a, b, c, d)
    u = [0.0] + u_in + [U]
    return ys, u


def solve_burgers_viscous(p, probe_x):
    """Explicit conservative flux form: u_t + (u^2/2)_x = nu u_xx, tanh initial profile."""
    L, nx, nu = p["L"], p["nx"], p["nu"]
    ul, ur, x0, t_end = p["u_l"], p["u_r"], p["x0"], p["t_end"]
    dx = L / (nx - 1)
    xs = [i * dx for i in range(nx)]
    s = 0.5 * (ul + ur)
    u = [0.5 * (ul + ur) - 0.5 * (ul - ur) * math.tanh((x - x0) * (ul - ur) / (4.0 * nu))
         for x in xs]
    dt = 0.4 * min(dx / max(abs(ul), abs(ur), 1e-9), 0.5 * dx * dx / nu)
    t, nsteps = 0.0, 0
    while t < t_end - 1e-15:
        dt = min(dt, t_end - t)
        # MUSCL reconstruction with a minmod limiter, then a Rusanov flux on the reconstructed
        # states. The plain first-order Rusanov flux used before carried enough numerical diffusion
        # to thicken the tanh layer and miss 5e-3 (it gave 1.2e-2). Loosening the tolerance to fit
        # a weak scheme would have hidden exactly the discrimination this case exists to provide.
        def mm(a, b):
            return 0.0 if a * b <= 0 else (a if abs(a) < abs(b) else b)

        sl = [0.0] * nx
        for i in range(1, nx - 1):
            sl[i] = mm(u[i] - u[i - 1], u[i + 1] - u[i])

        def flux(i):                      # flux at face between i and i+1
            uL = u[i] + 0.5 * sl[i]
            uR = u[i + 1] - 0.5 * sl[i + 1]
            a = max(abs(uL), abs(uR))
            return 0.5 * (0.5 * uL * uL + 0.5 * uR * uR) - 0.5 * a * (uR - uL)

        un = list(u)
        for i in range(1, nx - 1):
            un[i] = u[i] - dt / dx * (flux(i) - flux(i - 1)) \
                + nu * dt / dx ** 2 * (u[i + 1] - 2 * u[i] + u[i - 1])
        un[0], un[-1] = ul, ur
        u = un
        t += dt
        nsteps += 1
        if nsteps > 2_000_000:
            raise SystemExit("ref_flow: burgers_viscous step count ran away")
    return {"u_at_probe_x": [interp(xs, u, x) for x in probe_x]}


def godunov_flux(ul, ur):
    """Exact Riemann solver for Burgers' flux u^2/2."""
    if ul > ur:                                   # shock
        s = 0.5 * (ul + ur)
        return 0.5 * ul * ul if s > 0 else 0.5 * ur * ur
    if ul > 0:                                    # rarefaction, all right-going
        return 0.5 * ul * ul
    if ur < 0:
        return 0.5 * ur * ur
    return 0.0                                    # sonic point


def solve_burgers_shock(p):
    """Godunov scheme — conservative by construction, so the flux balance holds to round-off."""
    L, nx = p["L"], p["nx"]
    ul, ur, x0, t_end = p["u_l"], p["u_r"], p["x0"], p["t_end"]
    dx = L / nx                                   # finite volumes
    xc = [(i + 0.5) * dx for i in range(nx)]
    u = [ul if x < x0 else ur for x in xc]
    t = 0.0
    while t < t_end - 1e-15:
        amax = max(abs(v) for v in u) or 1.0
        dt = min(0.4 * dx / amax, t_end - t)
        fl = [godunov_flux(ul, u[0])] + [godunov_flux(u[i], u[i + 1]) for i in range(nx - 1)] \
             + [godunov_flux(u[-1], ur)]
        u = [u[i] - dt / dx * (fl[i + 1] - fl[i]) for i in range(nx)]
        t += dt
    # shock position: steepest descent between cells
    drops = [(u[i] - u[i + 1], i) for i in range(nx - 1)]
    _, i_s = max(drops)
    xs = 0.5 * (xc[i_s] + xc[i_s + 1])
    return {"shock_position": xs, "u_left": u[0], "u_right": u[-1],
            "integral_u": sum(v * dx for v in u)}


def solve_cavity(p):
    """Vorticity-streamfunction, SOR to steady state. Divergence is zero by construction."""
    Re, n = p["Re"], p["n"]
    h = 1.0 / (n - 1)
    psi = [[0.0] * n for _ in range(n)]
    w = [[0.0] * n for _ in range(n)]
    nu = 1.0 / Re
    dt = 0.2 * min(h * h / (4 * nu), h)
    for step in range(60000):
        # streamfunction: Laplacian psi = -w, a few SOR sweeps
        for _ in range(3):
            for i in range(1, n - 1):
                for j in range(1, n - 1):
                    new = 0.25 * (psi[i + 1][j] + psi[i - 1][j] + psi[i][j + 1] + psi[i][j - 1]
                                  + h * h * w[i][j])
                    psi[i][j] += 1.5 * (new - psi[i][j])
        # wall vorticity (Thom)
        for i in range(n):
            w[i][0] = 2.0 * (psi[i][0] - psi[i][1]) / h ** 2
            w[i][n - 1] = 2.0 * (psi[i][n - 1] - psi[i][n - 2]) / h ** 2 - 2.0 / h
        for j in range(n):
            w[0][j] = 2.0 * (psi[0][j] - psi[1][j]) / h ** 2
            w[n - 1][j] = 2.0 * (psi[n - 1][j] - psi[n - 2][j]) / h ** 2
        # vorticity transport
        wn = [row[:] for row in w]
        mx = 0.0
        for i in range(1, n - 1):
            for j in range(1, n - 1):
                u = (psi[i][j + 1] - psi[i][j - 1]) / (2 * h)
                v = -(psi[i + 1][j] - psi[i - 1][j]) / (2 * h)
                conv = u * (w[i + 1][j] - w[i - 1][j]) / (2 * h) + \
                    v * (w[i][j + 1] - w[i][j - 1]) / (2 * h)
                diff = nu * (w[i + 1][j] + w[i - 1][j] + w[i][j + 1] + w[i][j - 1] - 4 * w[i][j]) / h ** 2
                wn[i][j] = w[i][j] + dt * (diff - conv)
                mx = max(mx, abs(wn[i][j] - w[i][j]))
        w = wn
        if step > 200 and mx < 1e-7:
            break
    mid = (n - 1) // 2
    ys = [j * h for j in range(n)]
    u_line = [(psi[mid][j + 1] - psi[mid][j - 1]) / (2 * h) if 0 < j < n - 1
              else (1.0 if j == n - 1 else 0.0) for j in range(n)]
    v_line = [-(psi[i + 1][mid] - psi[i - 1][mid]) / (2 * h) if 0 < i < n - 1 else 0.0
              for i in range(n)]
    return {"u_line": (ys, u_line), "v_line": (ys, v_line)}


def solve_taylor_green(p, probe_xy):
    """Pseudo-spectral vorticity solver — a REAL integration, not the analytic answer.

    The first version of this function simply returned the closed form and reported max_div = 0.0,
    which meant the achievability probe validated nothing at all for these cases: it compared the
    analytic solution against itself. Since the whole purpose of the probe is to show that the
    stated tolerances are reachable by an actual scheme, that was worse than useless — it was a
    green light with no evidence behind it.

    Vorticity form, omega = v_x - u_y, advanced with Heun (2nd order in time) and 2/3 dealiasing.
    Velocity is recovered from the streamfunction, so the discrete divergence is zero to round-off
    by construction — which is exactly what the 1e-8 incompressibility check demands.
    """
    import numpy as np

    n, nu, t_end = p["n"], p["nu"], p["t_end"]
    x = np.arange(n) * 2.0 * np.pi / n
    X, Y = np.meshgrid(x, x, indexing="ij")
    w = 2.0 * np.sin(X) * np.sin(Y)                    # omega at t=0 for Taylor-Green

    k = np.fft.fftfreq(n, d=1.0 / n)
    KX, KY = np.meshgrid(k, k, indexing="ij")
    K2 = KX ** 2 + KY ** 2
    K2inv = np.where(K2 == 0, 1.0, K2)
    mask = (np.abs(KX) < n / 3.0) & (np.abs(KY) < n / 3.0)   # 2/3 rule

    def velocity(wh):
        psih = wh / K2inv
        psih[0, 0] = 0.0
        u = np.real(np.fft.ifft2(1j * KY * psih))
        v = np.real(np.fft.ifft2(-1j * KX * psih))
        return u, v

    def rhs(wh):
        u, v = velocity(wh)
        wx = np.real(np.fft.ifft2(1j * KX * wh))
        wy = np.real(np.fft.ifft2(1j * KY * wh))
        conv = np.fft.fft2(u * wx + v * wy) * mask
        return -conv - nu * K2 * wh

    wh = np.fft.fft2(w)
    dt = 0.2 * min(2.0 * np.pi / n, 1.0 / (nu * (n / 3.0) ** 2 + 1e-30))
    t = 0.0
    while t < t_end - 1e-14:
        dt_step = min(dt, t_end - t)
        k1 = rhs(wh)
        k2 = rhs(wh + dt_step * k1)
        wh = wh + 0.5 * dt_step * (k1 + k2)
        t += dt_step

    u, v = velocity(wh)
    d = 2.0 * np.pi / n
    idx = [(int(round(px / d)) % n, int(round(py / d)) % n) for (px, py) in probe_xy]
    # discrete divergence from the same spectral operators used to build the velocity
    div = np.real(np.fft.ifft2(1j * KX * np.fft.fft2(u) + 1j * KY * np.fft.fft2(v)))
    return {"fields": {"u_at_probe": [float(u[i, j]) for (i, j) in idx],
                       "v_at_probe": [float(v[i, j]) for (i, j) in idx]},
            "scalars": {"kinetic_energy": float(np.mean(0.5 * (u ** 2 + v ** 2))),
                        "max_div": float(np.max(np.abs(div)))}}


def run(case):
    k, p = case["kind"], case["params"]
    if k == "poiseuille":
        ys, u = solve_channel(p, case["probe_y"])
        H, mu, dpdx = p["H"], p["mu"], p["dpdx"]
        return {"fields": {"u_at_probe_y": [interp(ys, u, y) for y in case["probe_y"]]},
                "scalars": {"u_center": interp(ys, u, H / 2.0), "Q": simpson(ys, u)}}
    if k == "couette_pg":
        ys, u = solve_channel(p, case["probe_y"], couette=True)
        return {"fields": {"u_at_probe_y": [interp(ys, u, y) for y in case["probe_y"]]},
                "scalars": {"u_center": interp(ys, u, p["H"] / 2.0)}}
    if k == "taylor_green":
        return solve_taylor_green(p, case["probe_xy"])
    if k == "burgers_viscous":
        return {"fields": solve_burgers_viscous(p, case["probe_x"]), "scalars": {}}
    if k == "burgers_shock":
        return {"fields": {}, "scalars": solve_burgers_shock(p)}
    if k == "hyperelastic_bar":
        mu, lam = p["mu"], p["lambda"]
        return {"fields": {}, "scalars": {"P_nominal": mu * (lam - 1.0 / lam ** 2),
                                          "sigma_cauchy": mu * (lam ** 2 - 1.0 / lam),
                                          "W": mu / 2.0 * (lam ** 2 + 2.0 / lam - 3.0)}}
    if k == "cavity":
        out = solve_cavity(p)
        ys, ul = out["u_line"]
        xs, vl = out["v_line"]
        return {"fields": {"u_centerline": [interp(ys, ul, y) for y in case["probe_y"]],
                           "v_centerline": [interp(xs, vl, x) for x in case["probe_x"]]},
                "scalars": {"max_div": 0.0}}
    raise SystemExit(f"ref_flow: unknown kind {k!r}")


def main():
    case = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out = run(case)
    out["name"] = case["name"]
    pathlib.Path(sys.argv[2]).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
