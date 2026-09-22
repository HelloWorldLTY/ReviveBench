#!/usr/bin/env python3
"""Hidden verifier for cad3d_brep. Never visible to the candidate.

Like every hidden verifier here, this runs with the RUN's venv python — the candidate's own
environment, which has no geometry libraries at all. So every oracle-side computation is delegated
by subprocess to envs/cad3d_oracle (OCP + trimesh), exactly as cad2d_dxf delegates to ezdxf/shapely.
Importing trimesh here would crash the verifier in production and look like a total agent failure.

Four graded checks plus one informational:

  entrypoint            run_solid.sh exists
  env_constraints       no forbidden geometry library installed in the workspace env
  mass_properties       volume / area / centroid / bbox vs OCC's exact analytic values
  mesh_topology         every shell closed, total Euler characteristic and shell count exact
  point_membership      every query point classified correctly, on every model

On thresholds — this is the lesson the EDA synthesis task paid for. A tolerance is right for numeric
agreement, so mass_properties may miss on a minority of models. It is wrong where a failure is a
*proof of wrongness*: a misclassified query point means the candidate's solid provably contains a
point the real solid does not, and a wrong Euler characteristic means the boundary is provably a
different surface. Those two are graded n-of-n. A 0.9 threshold on 13 models is 11.7 — i.e. 12/13
would pass — which is exactly how a netlist carrying three witnessed counterexamples once scored
full marks on the synthesis task.

usage: verify.py --workspace <ws> --out <json> [--solid-cmd 'tmpl {model} {out}'] [--skip-env-check]
"""
import argparse
import json
import math
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import sh, make_env  # noqa: E402

ORACLE_PY = str(HERE.parents[2] / "envs" / "cad3d_oracle" / "bin" / "python")
FORBIDDEN = ("ocp", "cadquery", "cadquery-ocp", "pythonocc-core", "opencascade", "trimesh",
             "manifold3d", "open3d", "pymesh", "numpy-stl", "meshio", "scipy", "shapely",
             "gmsh", "pyvista", "vtk", "matplotlib")

# volume is tightest: a correct kernel gets it right most easily. area is looser because
# tessellating a curved face always under-reports it a little.
TOL_VOL = 0.005      # relative
TOL_AREA = 0.015     # relative
TOL_POS = 0.005      # fraction of the bbox diagonal, for centroid and bbox corners


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


def mesh_topology(stl, env, tmp):
    """Delegate STL analysis to the oracle env; returns a dict (possibly {'error': ...})."""
    if not pathlib.Path(stl).exists():
        return {"error": f"no STL at {pathlib.Path(stl).name}"}
    rc, out = sh([ORACLE_PY, str(HERE / "mesh_topo.py"), str(stl)], str(tmp), env, 600)
    lines = [l for l in out.splitlines() if l.startswith("{")]
    if not lines:
        return {"error": f"mesh_topo produced nothing (rc={rc}): {out[-160:]}"}
    try:
        return json.loads(lines[-1])
    except Exception as e:  # noqa: BLE001
        return {"error": f"unparseable mesh_topo output: {e}"}


def grade_mass(got, ref, diag):
    reasons, d = [], {}
    if got.get("volume") is None:
        reasons.append("volume missing")
    else:
        d["vol_err"] = round(rel(got["volume"], ref["volume"]), 6)
        if d["vol_err"] > TOL_VOL:
            reasons.append(f"volume {got['volume']:.5f} vs {ref['volume']:.5f} ({d['vol_err']:.3%})")
    if got.get("area") is None:
        reasons.append("area missing")
    else:
        d["area_err"] = round(rel(got["area"], ref["area"]), 6)
        if d["area_err"] > TOL_AREA:
            reasons.append(f"area {got['area']:.5f} vs {ref['area']:.5f} ({d['area_err']:.3%})")
    for key in ("centroid", "bbox"):
        g, r = got.get(key), ref[key]
        if not isinstance(g, list) or len(g) != len(r):
            reasons.append(f"{key} missing/malformed")
            continue
        err = max(abs(float(gi) - ri) for gi, ri in zip(g, r)) / diag
        d[f"{key}_err"] = round(err, 6)
        if err > TOL_POS:
            reasons.append(f"{key} off by {err:.3%} of diagonal")
    if reasons:
        d["mass_why"] = "; ".join(reasons)[:200]
    return not reasons, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--solid-cmd", default=None,
                    help="calibration: command template with {model} and {out}")
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_cad3d_"))
    env = make_env(ws)
    env.pop("PYTHONPATH", None)
    manifest = json.loads((HERE / "manifest.json").read_text())["models"]

    checks, metrics, per = {}, {}, {}
    checks["entrypoint"] = {"pass": (ws / "run_solid.sh").exists(), "detail": "run_solid.sh"}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"],
                     str(tmp), env, 180)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad,
                                     "detail": "forbidden: " + ", ".join(bad) if bad else "ok"}

    mass_ok = topo_ok = pmc_ok = 0
    for name in manifest:
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text())
        model = json.loads((HERE / "models" / f"{name}.model.json").read_text())
        wd = tmp / name
        wd.mkdir(parents=True, exist_ok=True)
        model_file = wd / f"{name}.model.json"
        model_file.write_text(json.dumps(model))
        out_file = wd / f"{name}.out.json"
        cmd = (a.solid_cmd.format(model=model_file, out=out_file).split() if a.solid_cmd
               else ["bash", str(ws / "run_solid.sh"), str(model_file), str(out_file)])
        # 600s x 13 models = 7800s, inside task.json's verify_timeout of 9000. Keep these two in
        # step: a per-model budget that can outrun the task timeout gets a slow-but-correct kernel
        # killed mid-verification, which is indistinguishable from total failure.
        rc, log = sh(cmd, str(wd), env, 600)
        rec = {"rc": rc}
        if not out_file.exists():
            rec["why"] = f"no output: {log[-160:]}"
            per[name] = rec
            continue
        try:
            got = json.loads(out_file.read_text())
        except Exception as e:  # noqa: BLE001
            rec["why"] = f"unparseable output: {str(e)[:120]}"
            per[name] = rec
            continue

        diag = math.dist(ref["bbox"][:3], ref["bbox"][3:]) or 1.0
        m_ok, d = grade_mass(got, ref, diag)
        rec.update(d)

        topo = mesh_topology(wd / model["stl_out"], env, wd)
        if "error" in topo:
            t_ok = False
            rec["topo_why"] = topo["error"]
        else:
            t_ok = (topo["closed"] and topo["euler"] == ref["euler"]
                    and topo["shells"] == ref["shells"])
            rec.update(euler=topo["euler"], shells=topo["shells"], closed=topo["closed"])
            if not t_ok:
                rec["topo_why"] = (f"closed={topo['closed']} euler={topo['euler']}"
                                   f"(want {ref['euler']}) shells={topo['shells']}"
                                   f"(want {ref['shells']})")

        got_in, ref_in = got.get("inside"), ref["inside"]
        if not isinstance(got_in, list) or len(got_in) != len(ref_in):
            p_ok = False
            rec["pmc_why"] = f"expected {len(ref_in)} answers, got " + (
                "none" if got_in is None else str(len(got_in)))
        else:
            wrong = [i for i, (g, r) in enumerate(zip(got_in, ref_in)) if bool(g) != bool(r)]
            p_ok = not wrong
            rec["pmc_wrong"] = len(wrong)
            if wrong:
                rec["pmc_why"] = f"{len(wrong)}/{len(ref_in)} misclassified, first at {wrong[0]}"

        rec.update(mass=m_ok, topo=t_ok, pmc=p_ok)
        mass_ok += m_ok
        topo_ok += t_ok
        pmc_ok += p_ok
        per[name] = rec

    n = len(manifest)
    metrics["per_model"] = per
    metrics["n_models"] = n
    checks["mass_properties"] = {
        "pass": mass_ok >= 0.9 * n,
        "detail": f"{mass_ok}/{n} within tolerance; off: " +
                  ", ".join(k for k, v in per.items() if not v.get("mass"))}
    checks["mesh_topology"] = {
        "pass": topo_ok == n,
        "detail": f"{topo_ok}/{n} topologically exact; off: " +
                  ", ".join(f"{k}({str(v.get('topo_why', ''))[:44]})"
                            for k, v in per.items() if not v.get("topo"))}
    checks["point_membership"] = {
        "pass": pmc_ok == n,
        "detail": f"{pmc_ok}/{n} models fully correct; off: " +
                  ", ".join(f"{k}({v.get('pmc_wrong', '?')})"
                            for k, v in per.items() if not v.get("pmc"))}
    errs = [v["vol_err"] for v in per.values() if "vol_err" in v]
    metrics["vol_err_median"] = round(sorted(errs)[len(errs) // 2], 6) if errs else None
    checks["accuracy_reported"] = {
        "pass": True, "informational": True,
        "detail": f"volume relative error median {metrics['vol_err_median']}"}

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")


if __name__ == "__main__":
    main()
