#!/usr/bin/env python3
"""Hidden verifier for spice_ngspice: compare the agent's CSV outputs with ngspice references."""
import argparse, json, math, pathlib, sys, tempfile, glob
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, finish
FORBIDDEN = ("scipy", "pyspice", "ngspice", "ahkab", "lcapy", "schemdraw", "pandas")

def read_csv(p):
    lines = [l.strip() for l in pathlib.Path(p).read_text().splitlines() if l.strip()]
    hdr = [h.strip().lower() for h in lines[0].split(",")]
    rows = np.array([[float(x) for x in l.split(",")] for l in lines[1:]], dtype=float)
    return hdr, rows

def compare(kind, ref_hdr, ref, hdr, got):
    cols = {h: i for i, h in enumerate(hdr)}; details = {}; ok = True
    if kind == "op":
        for j, h in enumerate(ref_hdr):
            if h not in cols: ok = False; details[h] = "missing"; continue
            r, g = ref[0, j], got[0, cols[h]]
            tol = 0.005 * abs(r) + (1e-6 if h.startswith("v") else 1e-9)
            details[h] = round(abs(r - g), 9); ok &= abs(r - g) <= tol
        return ok, details
    x = ref[:, 0]; gx = got[:, 0]
    for j, h in enumerate(ref_hdr[1:], start=1):
        if h not in cols: ok = False; details[h] = "missing"; continue
        r = ref[:, j]; gi = np.interp(x, gx, got[:, cols[h]])
        if kind == "dc":
            tol = 0.005 * np.abs(r) + (1e-6 if h.startswith("v") else 1e-9)
            bad = np.mean(np.abs(r - gi) > tol); details[h] = {"frac_bad": round(float(bad), 4)}; ok &= bad <= 0.02
        else:
            rng = max(float(r.max() - r.min()), 1e-12)
            rms = float(np.sqrt(np.mean((r - gi) ** 2)) / rng); mx = float(np.max(np.abs(r - gi)) / rng)
            details[h] = {"rms_rel": round(rms, 4), "max_rel": round(mx, 4)}; ok &= rms <= 0.02 and mx <= 0.05
    return ok, details

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
        checks["launcher_present"] = {"pass": (ws / "run_sim.sh").exists(), "detail": "run_sim.sh"}
    engine = a.engine.split() if a.engine else ["bash", str(ws / "run_sim.sh")]
    per, n_pass = {}, 0
    for f in sorted(glob.glob(str(HERE / "netlists" / "*.cir"))):
        name = pathlib.Path(f).stem; kind = "op" if ".op" in open(f).read().lower() else ("dc" if "\n.dc" in open(f).read().lower() else "tran")
        wd = tmp / name; wd.mkdir(); out = wd / "out.csv"
        rc, log = sh(engine + [f, str(out)], wd, env, 600)
        rec = {"kind": kind, "rc": rc}
        try:
            rh, ref = read_csv(HERE / "ref" / f"{name}.csv"); gh, got = read_csv(out)
            ok, det = compare(kind, rh, ref, gh, got); rec["detail"] = det
        except Exception as e:
            ok = False; rec["error"] = (str(e) + " | " + log[-300:])[-500:]
        rec["pass"] = bool(ok); per[name] = rec; n_pass += bool(ok)
    metrics["per_netlist"] = per; metrics["n_pass"] = n_pass; metrics["n_total"] = len(per)
    checks["waveforms_vs_ngspice"] = {"pass": n_pass >= 0.8 * len(per), "detail": f"{n_pass}/{len(per)} netlists match; failures: " + ", ".join(k for k, v in per.items() if not v["pass"])}
    finish(a.out, checks, metrics, tmp)

if __name__ == "__main__":
    main()
