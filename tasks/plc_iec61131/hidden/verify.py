#!/usr/bin/env python3
"""Hidden verifier for plc_iec61131: run the agent's runtime on hidden ST programs and compare traces."""
import argparse, json, pathlib, sys, tempfile, glob
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, finish
CYCLE = "10"

def read(p):
    lines = [l.strip() for l in pathlib.Path(p).read_text().splitlines() if l.strip()]
    return lines[0].split(","), [l.split(",") for l in lines[1:]]

def same(a, b):
    try:
        fa, fb = float(a), float(b)
    except Exception:
        return a.strip() == b.strip()
    if "." in a or "." in b or "e" in a.lower() or "e" in b.lower():
        return abs(fa - fb) <= 1e-6 * max(1.0, abs(fb))
    return fa == fb

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true"); ap.add_argument("--engine", default=None)
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve(); tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws); env.pop("PYTHONPATH", None)
    checks, metrics = {}, {}
    if not a.skip_env_check:
        checks["launcher_present"] = {"pass": (ws / "run_plc.sh").exists(), "detail": "run_plc.sh"}
    engine = a.engine.split() if a.engine else ["bash", str(ws / "run_plc.sh")]
    per, n_pass = {}, 0
    for f in sorted(glob.glob(str(HERE / "programs" / "*.st"))):
        name = pathlib.Path(f).stem; wd = tmp / name; wd.mkdir(); out = wd / "trace.csv"
        rc, log = sh(engine + [f, str(HERE / "programs" / f"{name}.csv"), str(out), CYCLE], wd, env, 300)
        rec = {"rc": rc}
        try:
            rh, ref = read(HERE / "ref" / f"{name}.csv"); gh, got = read(out)
            gh = [h.strip() for h in gh]; col = {h: i for i, h in enumerate(gh)}
            bad = 0; first = None
            for k, row in enumerate(ref):
                g = got[k] if k < len(got) else []
                for j, h in enumerate(rh):
                    v = g[col[h]] if h in col and col[h] < len(g) else "MISSING"
                    if not same(v, row[j]):
                        bad += 1
                        if first is None: first = f"scan {k} {h}: got {v} expected {row[j]}"
            rec.update({"rows": len(ref), "mismatch_cells": bad, "first_mismatch": first}); ok = bad == 0 and len(got) >= len(ref)
        except Exception as e:
            ok = False; rec["error"] = (str(e) + " | " + log[-300:])[-500:]
        rec["pass"] = bool(ok); per[name] = rec; n_pass += bool(ok)
    metrics["per_program"] = per; metrics["n_pass"] = n_pass; metrics["n_total"] = len(per)
    checks["traces_match_reference"] = {"pass": n_pass >= 0.8 * len(per), "detail": f"{n_pass}/{len(per)} programs match; failures: " + ", ".join(f"{k} ({v.get('first_mismatch') or v.get('error', '')[:80]})" for k, v in per.items() if not v["pass"])}
    finish(a.out, checks, metrics, tmp)

if __name__ == "__main__":
    main()
