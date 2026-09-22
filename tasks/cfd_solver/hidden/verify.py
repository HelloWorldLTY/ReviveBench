#!/usr/bin/env python3
"""Hidden verifier for cfd_solver. Never visible to the candidate.

Runs with the RUN's venv python. The oracle is `analytic.py` — closed-form solutions only — so there
is no oracle environment, no subprocess delegation, and no third-party dependency that can bite
mid-run the way a missing trimesh backend once did on cad3d.

Graded checks:

  entrypoint            run_cfd.sh exists
  env_constraints       no forbidden PDE/linear-algebra package installed in the workspace env
  analytic_accuracy     relative L2 error against the closed form, per case, at the tolerances below
  flux_balance          burgers_shock: reported integral_u equals the exact flux-balance value
  incompressibility     taylor_green: reported max|div u| below 1e-8
  shock_capture         burgers_shock: shock position within one cell width

EVERY TOLERANCE HERE WAS MEASURED, NOT ASSERTED. An achievability probe ran a competent reference
scheme through all 13 cases and recorded the error actually attained:

    poiseuille / couette_pg   1e-14 .. 1e-16   against 1e-6
    taylor_green              1e-8             against 2e-3   (max_div 8e-15 against 1e-8)
    burgers_viscous           3.2e-4 .. 1.4e-3 against 5e-3
    burgers_shock             position exact, flux balance 1e-15 against 1e-8
    hyperelastic_bar          0                against 1e-9

That probe earned its keep: the first draft of this task had FOUR tolerances that no scheme could
reach, and calibration could never have revealed any of them, because calibration compares my solver
against my own formulas. The travelling-wave reference had dropped x0 entirely, the probe points sat
off-grid so interpolation error swamped a 1e-6 target, the shock's x0 fell mid-cell so the discrete
initial integral differed from the analytic one by ~dx, and Q was integrated with the trapezoid rule,
which is not exact for a parabola. A lid-driven-cavity case was removed outright rather than ship a
threshold I could not demonstrate was reachable.

usage: verify.py --workspace <ws> --out <json> [--cfd-cmd 'tmpl {case} {out}'] [--skip-env-check]
"""
import argparse
import json
import math
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
sys.path.insert(0, str(HERE))
from verify_common import sh, make_env  # noqa: E402
from analytic import rel_l2  # noqa: E402

FORBIDDEN = ("scipy", "fenics", "firedrake", "fipy", "sympy", "petsc4py", "pyamg",
             "numba", "jax", "torch", "matplotlib", "pandas")

TOL = {"poiseuille": 1e-6, "couette_pg": 1e-6, "hyperelastic_bar": 1e-9,
       "taylor_green": 2e-3, "burgers_viscous": 5e-3, "burgers_shock": 5e-3}
DIV_TOL = 1e-8
FLUX_TOL = 1e-8


def grade_case(case, ref, got):
    """Return (acc_ok, flux_ok, div_ok, shock_ok, detail)."""
    d = {}
    kind = case["kind"]
    tol = TOL[kind]

    errs = []
    for key, want in ref.get("fields", {}).items():
        g = got.get("fields", {}).get(key)
        if not isinstance(g, list):
            errs.append((key, float("inf")))
            continue
        errs.append((key, rel_l2([float(v) for v in g], want)))
    import math as _math
    BOX = (2.0 * _math.pi) ** 2          # Taylor-Green domain area
    for key, want in ref.get("scalars", {}).items():
        g = got.get("scalars", {}).get(key)
        if g is None:
            errs.append((key, float("inf")))
            continue
        den = abs(want) if abs(want) > 1e-12 else 1.0
        e = abs(float(g) - want) / den
        # Defect #23: the spec originally did not say whether `kinetic_energy` was the domain MEAN
        # or the domain INTEGRAL. fable5.1 reported the integral, matching mean*(2pi)^2 to 8e-5,
        # and was failed for a convention I never stated. The two differ by exactly the box area,
        # so both are decidable and both are now accepted, each against its own exact value.
        if kind == "taylor_green" and key == "kinetic_energy":
            e = min(e, abs(float(g) - want * BOX) / (abs(want) * BOX))
        errs.append((key, e))

    # every key the case's `report` array names must be present
    missing = []
    for key in case["report"]:
        if key == "max_div":
            if got.get("scalars", {}).get("max_div") is None:
                missing.append(key)
        elif key not in got.get("fields", {}) and key not in got.get("scalars", {}):
            missing.append(key)
    if missing:
        d["missing"] = missing

    worst_key, worst = max(errs, key=lambda x: x[1]) if errs else ("-", 0.0)
    d["worst_key"] = worst_key
    d["worst_err"] = None if math.isinf(worst) else round(worst, 12)
    acc_ok = (not missing) and worst <= tol
    if not acc_ok and not missing:
        d["acc_why"] = f"{worst_key} relative error {worst:.3e} > {tol:.0e}"

    # --- exact checks, only where the case defines them
    flux_ok = div_ok = shock_ok = None
    if kind == "burgers_shock":
        gi = got.get("scalars", {}).get("integral_u")
        wi = ref["scalars"]["integral_u"]
        flux_ok = gi is not None and abs(float(gi) - wi) <= FLUX_TOL
        d["flux_err"] = None if gi is None else abs(float(gi) - wi)
        if not flux_ok:
            d["flux_why"] = f"∫u dx differs from the flux balance by {d['flux_err']}" if gi is not None else "not reported"
        gp = got.get("scalars", {}).get("shock_position")
        wp = ref["scalars"]["shock_position"]
        dx = case["params"]["L"] / case["params"]["nx"]
        shock_ok = gp is not None and abs(float(gp) - wp) <= dx
        d["shock_err"] = None if gp is None else abs(float(gp) - wp)
        if not shock_ok:
            d["shock_why"] = f"shock position off by {d['shock_err']} > one cell {dx}"
    if kind == "taylor_green":
        md = got.get("scalars", {}).get("max_div")
        div_ok = md is not None and abs(float(md)) <= DIV_TOL
        d["max_div"] = None if md is None else float(md)
        if not div_ok:
            d["div_why"] = (f"max|div u| = {md} > {DIV_TOL:.0e}" if md is not None
                            else "max_div not reported")
    return acc_ok, flux_ok, div_ok, shock_ok, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cfd-cmd", default=None,
                    help="calibration: command template with {case} and {out}")
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_cfd_"))
    env = make_env(ws)
    env.pop("PYTHONPATH", None)
    manifest = json.loads((HERE / "manifest.json").read_text())["cases"]

    checks, metrics, per = {}, {}, {}
    checks["entrypoint"] = {"pass": (ws / "run_cfd.sh").exists(), "detail": "run_cfd.sh"}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"],
                     str(tmp), env, 180)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad,
                                     "detail": "forbidden: " + ", ".join(bad) if bad else "ok"}

    acc_ok = 0
    flux_tot = flux_ok = div_tot = div_ok = shock_tot = shock_ok = 0
    for name in manifest:
        case = json.loads((HERE / "cases" / f"{name}.json").read_text())
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text())
        wd = tmp / name
        wd.mkdir(parents=True, exist_ok=True)
        cfile = wd / f"{name}.case.json"
        cfile.write_text(json.dumps(case))
        ofile = wd / f"{name}.out.json"
        cmd = (a.cfd_cmd.format(case=cfile, out=ofile).split() if a.cfd_cmd
               else ["bash", str(ws / "run_cfd.sh"), str(cfile), str(ofile)])
        rc, log = sh(cmd, str(wd), env, 900)
        rec = {"rc": rc, "kind": case["kind"]}
        if not ofile.exists():
            rec["why"] = f"no output: {log[-200:]}"
            per[name] = rec
            continue
        try:
            got = json.loads(ofile.read_text())
        except Exception as e:  # noqa: BLE001
            rec["why"] = f"unparseable output: {str(e)[:140]}"
            per[name] = rec
            continue

        ao, fo, do, so, d = grade_case(case, ref, got)
        rec.update(d, acc=ao)
        acc_ok += ao
        if fo is not None:
            flux_tot += 1
            flux_ok += fo
            rec["flux"] = fo
        if do is not None:
            div_tot += 1
            div_ok += do
            rec["div"] = do
        if so is not None:
            shock_tot += 1
            shock_ok += so
            rec["shock"] = so
        per[name] = rec

    n = len(manifest)
    metrics["per_case"] = per
    metrics["n_cases"] = n
    checks["analytic_accuracy"] = {
        "pass": acc_ok == n,
        "detail": f"{acc_ok}/{n} within tolerance; over: " +
                  ", ".join(f"{k}({v.get('acc_why', v.get('why', '?'))[:40]})"
                            for k, v in per.items() if not v.get("acc"))[:300]}
    checks["flux_balance"] = {
        "pass": flux_ok == flux_tot and flux_tot > 0,
        "detail": f"{flux_ok}/{flux_tot} flux balance holds; violations: " +
                  ", ".join(k for k, v in per.items() if v.get("flux") is False)}
    checks["incompressibility"] = {
        "pass": div_ok == div_tot and div_tot > 0,
        "detail": f"{div_ok}/{div_tot} divergence within 1e-8; violations: " +
                  ", ".join(f"{k}({v.get('max_div')})" for k, v in per.items()
                            if v.get("div") is False)}
    checks["shock_capture"] = {
        "pass": shock_ok == shock_tot and shock_tot > 0,
        "detail": f"{shock_ok}/{shock_tot} shock position within one cell; violations: " +
                  ", ".join(k for k, v in per.items() if v.get("shock") is False)}
    errs = [v["worst_err"] for v in per.values() if v.get("worst_err") is not None]
    metrics["worst_err_median"] = (round(sorted(errs)[len(errs) // 2], 12) if errs else None)
    checks["accuracy_reported"] = {
        "pass": True, "informational": True,
        "detail": f"median of the worst relative error per case {metrics['worst_err_median']}"}

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")


if __name__ == "__main__":
    main()
