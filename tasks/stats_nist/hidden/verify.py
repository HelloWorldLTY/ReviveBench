#!/usr/bin/env python3
"""Hidden verifier for stats_nist: run the agent's engine on every NIST StRD dataset and score LRE vs certified values."""
import argparse, json, math, pathlib, shutil, subprocess, sys, tempfile, glob
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness")); sys.path.insert(0, str(HERE))
from verify_common import PY, sh, make_env, finish
import nist_parse
TASK = json.loads((HERE.parent / "task.json").read_text())
THRESH = {"Lower": 7, "Average": 6, "Higher": 4}
NLS_THRESH = {"Lower": 6, "Average": 5, "Higher": 4}
FORBIDDEN = ("scipy", "statsmodels", "scikit-learn", "sklearn", "lmfit", "patsy", "pandas", "sympy", "torch", "jax")

def lre(est, cert):
    try:
        est = float(est)
    except Exception:
        return 0.0
    if not math.isfinite(est): return 0.0
    if cert == 0: return 15.0 if abs(est) < 1e-15 else max(0.0, -math.log10(abs(est)))
    if est == cert: return 15.0
    return max(0.0, min(15.0, -math.log10(abs(est - cert) / abs(cert))))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    ap.add_argument("--engine", default=None, help="calibration: command prefix instead of run_engine.sh")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve(); tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws); env.pop("PYTHONPATH", None)
    checks, metrics = {}, {}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"], tmp, env, 120)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad, "detail": "forbidden libraries installed: " + ",".join(bad) if bad else "ok"}
        checks["launcher_present"] = {"pass": (ws / "run_engine.sh").exists(), "detail": "run_engine.sh"}
    engine = a.engine.split() if a.engine else ["bash", str(ws / "run_engine.sh")]
    per, n_pass, n_total = {}, 0, 0
    for f in sorted(glob.glob(str(HERE / "data" / "*.dat"))):
        d = nist_parse.parse(f); csv, syn = nist_parse.to_syntax(d)
        wd = tmp / d["name"]; wd.mkdir(); (wd / "data.csv").write_text(csv); (wd / "script.sps").write_text(syn)
        rc, out = sh(engine + ["script.sps", "out.json"], wd, env, 300)
        rec = {"kind": d["kind"], "difficulty": d["difficulty"], "rc": rc}
        try:
            res = json.loads((wd / "out.json").read_text())["results"][-1]
        except Exception:
            res = None; rec["error"] = out[-400:]
        ok = False
        if res:
            if d["kind"] == "LLS":
                th = THRESH[d["difficulty"]]
                coef = res.get("coefficients", []); se = res.get("std_errors", [])
                l_coef = [lre(e, c) for e, c in zip(coef, d["cert"])] if len(coef) == len(d["cert"]) else [0]
                l_se = [lre(e, c) for e, c in zip(se, d["cert_sd"])] if len(se) == len(d["cert_sd"]) else [0]
                l_rsd = lre(res.get("residual_sd"), d["cert_rsd"]); l_r2 = lre(res.get("r_squared"), d["cert_r2"])
                rec.update({"lre_coef_min": round(min(l_coef), 2), "lre_se_min": round(min(l_se), 2), "lre_rsd": round(l_rsd, 2), "lre_r2": round(l_r2, 2), "threshold": th})
                ok = min(l_coef) >= th and min(l_se) >= th - 1 and l_rsd >= th - 1 and l_r2 >= th - 1
            elif d["kind"] == "NLS":
                th = NLS_THRESH[d["difficulty"]]
                est = res.get("estimates", []); se = res.get("std_errors", [])
                l_est = [lre(e, c) for e, c in zip(est, d["cert"])] if len(est) == len(d["cert"]) else [0]
                l_se = [lre(e, c) for e, c in zip(se, d["cert_sd"])] if len(se) == len(d["cert_sd"]) else [0]
                l_rss = lre(res.get("residual_ss"), d["cert_rss"]) if d["cert_rss"] > 1e-18 else (15.0 if abs(float(res.get("residual_ss", 1))) < 1e-18 else max(0.0, -math.log10(abs(float(res.get("residual_ss", 1))))))
                rec.update({"lre_est_min": round(min(l_est), 2), "lre_se_min": round(min(l_se), 2), "lre_rss": round(l_rss, 2), "threshold": th, "converged": res.get("converged")})
                ok = min(l_est) >= th and min(l_se) >= th - 2 and l_rss >= th
            else:
                c = d["cert"]; th = THRESH[d["difficulty"]]
                ls = {k: lre(res.get(k2), c[k]) for k, k2 in [("between_ss", "between_ss"), ("within_ss", "within_ss"), ("F", "f"), ("r2", "r_squared"), ("rsd", "residual_sd")]}
                rec.update({"lre": {k: round(v, 2) for k, v in ls.items()}, "threshold": th})
                ok = min(ls.values()) >= th and res.get("between_df") == c["between_df"] and res.get("within_df") == c["within_df"]
        rec["pass"] = bool(ok); per[d["name"]] = rec; n_total += 1; n_pass += bool(ok)
    metrics["per_dataset"] = per; metrics["n_pass"] = n_pass; metrics["n_total"] = n_total
    by_kind = {}
    for r in per.values(): by_kind.setdefault(r["kind"], [0, 0]); by_kind[r["kind"]][0] += r["pass"]; by_kind[r["kind"]][1] += 1
    metrics["by_kind"] = by_kind
    checks["nist_strd_accuracy"] = {"pass": n_pass >= 0.85 * n_total, "detail": f"{n_pass}/{n_total} datasets within NIST LRE thresholds; by kind {by_kind}; failures: " + ", ".join(k for k, v in per.items() if not v["pass"])}
    finish(a.out, checks, metrics, tmp)

if __name__ == "__main__":
    main()
