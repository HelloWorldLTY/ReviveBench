#!/usr/bin/env python3
"""Hidden verifier for place_route. Never visible to the candidate.

Runs with the RUN's venv python. The oracle is `check_layout` from ref_pnr, which is pure standard
library, so there is no oracle environment and no subprocess delegation — and, unlike cad3d_brep,
no third-party library whose optional dependencies can bite mid-run.

Graded checks:

  entrypoint            run_pnr.sh exists
  env_constraints       no forbidden EDA/geometry package installed in the workspace env
  placement_legality    SPEC §4 on every instance of every design — no tolerance
  routing_correctness   SPEC §5 on every net of every design — no tolerance
  hpwl_consistency      the reported hpwl must equal the recomputation from the candidate's own
                        placement — no tolerance
  wirelength_quality    informational: routed length vs the reference router

Why three of these are n-of-n: on an integer grid a violation is a *proof* that the layout is
wrong. An overlapping cell, a disconnected net or two nets sharing a grid point are not "close to
right" — they are a chip that does not work. That is the same reasoning that put the EDA synthesis
task's simulation counterexamples and this suite's Euler characteristics on exact grading, and the
opposite of the 0.9-of-13 threshold that once let a netlist with three witnessed counterexamples
score full marks.

usage: verify.py --workspace <ws> --out <json> [--pnr-cmd 'tmpl {design} {out}'] [--skip-env-check]
"""
import argparse
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
sys.path.insert(0, str(HERE))
from verify_common import sh, make_env  # noqa: E402
from ref_pnr import check_layout  # noqa: E402

FORBIDDEN = ("openroad", "klayout", "gdstk", "gdspy", "shapely", "networkx",
             "scipy", "rtree", "matplotlib", "pandas")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pnr-cmd", default=None,
                    help="calibration: command template with {design} and {out}")
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_pnr_"))
    env = make_env(ws)
    env.pop("PYTHONPATH", None)
    manifest = json.loads((HERE / "manifest.json").read_text())["designs"]

    checks, metrics, per = {}, {}, {}
    checks["entrypoint"] = {"pass": (ws / "run_pnr.sh").exists(), "detail": "run_pnr.sh"}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"],
                     str(tmp), env, 180)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad,
                                     "detail": "forbidden: " + ", ".join(bad) if bad else "ok"}

    place_ok = route_ok = hpwl_ok = 0
    ratios = []
    for name in manifest:
        design = json.loads((HERE / "designs" / f"{name}.json").read_text())
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text())
        wd = tmp / name
        wd.mkdir(parents=True, exist_ok=True)
        dfile = wd / f"{name}.design.json"
        dfile.write_text(json.dumps(design))
        ofile = wd / f"{name}.out.json"
        cmd = (a.pnr_cmd.format(design=dfile, out=ofile).split() if a.pnr_cmd
               else ["bash", str(ws / "run_pnr.sh"), str(dfile), str(ofile)])
        rc, log = sh(cmd, str(wd), env, 900)
        rec = {"rc": rc}
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

        probs, met = check_layout(design, got)
        # Separate the problem list into the two graded families so the report can say which
        # stage failed rather than just "illegal".
        pl_probs = [p for p in probs if any(k in p for k in
                    ("outside the die", "not aligned", "overlap", "obstacle", "no position given",
                     "non-integer coordinates"))]
        rt_probs = [p for p in probs if p not in pl_probs]
        p_ok, r_ok = not pl_probs, not rt_probs
        rec["placement"] = p_ok
        rec["routing"] = r_ok
        if pl_probs:
            rec["place_why"] = "; ".join(pl_probs[:3])[:220]
            rec["n_place_probs"] = len(pl_probs)
        if rt_probs:
            rec["route_why"] = "; ".join(rt_probs[:3])[:220]
            rec["n_route_probs"] = len(rt_probs)

        # hpwl self-consistency, only meaningful when the placement itself parsed
        h_ok = False
        if p_ok and "hpwl" in met:
            reported = got.get("hpwl")
            h_ok = isinstance(reported, int) and reported == met["hpwl"]
            rec["hpwl_reported"] = reported
            rec["hpwl_recomputed"] = met["hpwl"]
            if not h_ok:
                rec["hpwl_why"] = f"self-reported {reported} != recomputed from its own placement {met['hpwl']}"
        rec["hpwl_ok"] = h_ok

        if p_ok and r_ok and met.get("routed_len") and ref.get("routed_len"):
            ratio = round(met["routed_len"] / ref["routed_len"], 3)
            rec["len_ratio"] = ratio
            ratios.append(ratio)

        place_ok += p_ok
        route_ok += r_ok
        hpwl_ok += h_ok
        per[name] = rec

    n = len(manifest)
    metrics["per_design"] = per
    metrics["n_designs"] = n
    metrics["len_ratio_median"] = (round(sorted(ratios)[len(ratios) // 2], 3)
                                   if ratios else None)
    checks["placement_legality"] = {
        "pass": place_ok == n,
        "detail": f"{place_ok}/{n} placements legal; violations: " +
                  ", ".join(f"{k}({v.get('n_place_probs','?')} problems)"
                            for k, v in per.items() if not v.get("placement"))}
    checks["routing_correctness"] = {
        "pass": route_ok == n,
        "detail": f"{route_ok}/{n} routings correct; violations: " +
                  ", ".join(f"{k}({v.get('n_route_probs', v.get('why','?'))})"
                            for k, v in per.items() if not v.get("routing"))[:300]}
    checks["hpwl_consistency"] = {
        "pass": hpwl_ok == n,
        "detail": f"{hpwl_ok}/{n} wirelengths self-consistent; mismatched: " +
                  ", ".join(k for k, v in per.items() if not v.get("hpwl_ok"))}
    checks["wirelength_quality"] = {
        "pass": True, "informational": True,
        "detail": f"median routed-length ratio {metrics['len_ratio_median']}x against the reference router (informational)"}

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")


if __name__ == "__main__":
    main()
