#!/usr/bin/env python3
"""Hidden verifier for fem_nafems: agent's femx vs CalculiX references and analytical probes."""
import argparse, json, pathlib, sys, tempfile, glob
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, finish
FORBIDDEN = ("scipy", "calculix", "sfepy", "fenics", "dolfin", "pynastran", "scikit-fem", "meshio", "gmsh", "pandas")
MODELS = json.loads((HERE / "ref" / "models.json").read_text())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true"); ap.add_argument("--engine", default=None)
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve(); tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws); env.pop("PYTHONPATH", None)
    checks, metrics = {}, {}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"], tmp, env, 120)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad, "detail": "forbidden: " + ",".join(bad) if bad else "ok"}
        checks["launcher_present"] = {"pass": (ws / "run_fem.sh").exists(), "detail": "run_fem.sh"}
    engine = a.engine.split() if a.engine else ["bash", str(ws / "run_fem.sh")]
    per, n_pass = {}, 0
    for name, m in MODELS.items():
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text()); wd = tmp / name; wd.mkdir(); out = wd / "out.json"
        rc, log = sh(engine + [str(HERE / "models" / f"{name}.inp"), str(out)], wd, env, 1200)
        rec = {"rc": rc}; ok = False
        try:
            res = json.loads(out.read_text())
            if m["kind"] == "static":
                rd = {int(k): np.array(v[:2]) for k, v in ref["displacements"].items()}; gd = {int(k): np.array(v[:2]) for k, v in res["displacements"].items()}
                umax = max(np.linalg.norm(v) for v in rd.values()); errs = []
                for k, v in rd.items():
                    if np.linalg.norm(v) < 0.01 * umax: continue
                    g = gd.get(k); errs.append(np.linalg.norm(g - v) / np.linalg.norm(v) if g is not None else 1.0)
                rec["max_rel_disp_err"] = float(max(errs)) if errs else None; rec["n_nodes"] = len(rd); ok = bool(errs) and max(errs) <= 0.01
                if "probe" in m:
                    pr = m["probe"]; g = gd.get(pr["node"]); val = float(g[pr["dof"] - 1]) if g is not None else None
                    rec["probe"] = {"got": val, "analytic": pr["analytic"]}; ok &= val is not None and abs(val - pr["analytic"]) / abs(pr["analytic"]) <= pr["tol"]
                if "probe_stress" in m:
                    ps = m["probe_stress"]; st = res.get("stresses", {}).get(str(ps["node"])); comp = {"sxx": 0, "syy": 1, "sxy": 2}[ps["component"]]
                    val = float(st[comp]) if st else None; rec["probe_stress"] = {"got": val, "analytic": ps["analytic"]}
                    ok &= val is not None and abs(val - ps["analytic"]) / abs(ps["analytic"]) <= ps["tol"]
            else:
                rf = ref["frequencies_hz"][:3]; gf = res.get("frequencies_hz", [])[:3]
                rec["freqs"] = {"got": gf, "ref": rf, "analytic_bending": m["analytic_bending_hz"]}
                ok = len(gf) == 3 and all(abs(g - r) / r <= 0.01 for g, r in zip(gf, rf))
        except Exception as e:
            rec["error"] = (str(e) + " | " + log[-300:])[-500:]
        rec["pass"] = bool(ok); per[name] = rec; n_pass += bool(ok)
    metrics["per_model"] = per; metrics["n_pass"] = n_pass; metrics["n_total"] = len(per)
    checks["benchmarks_vs_reference"] = {"pass": n_pass == len(per), "detail": f"{n_pass}/{len(per)} models; failures: " + ", ".join(k for k, v in per.items() if not v["pass"])}
    finish(a.out, checks, metrics, tmp)
if __name__ == "__main__": main()
