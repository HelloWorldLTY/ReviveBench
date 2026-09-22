#!/usr/bin/env python3
"""Hidden verifier for scada_dcs. Never visible to the candidate.

Runs with the RUN's venv python. The oracle (`ref_scada`) is pure standard library, so there is no
oracle environment, no subprocess delegation, and no optional third-party dependency that can fail
mid-run the way a missing trimesh backend once did on cad3d.

Graded checks:

  entrypoint            run_scada.sh exists
  env_constraints       no forbidden protocol/dataframe package installed in the workspace env
  alarm_journal         exact event sequence, timestamps, ordering — no tolerance
  historian_queries     count/min/max exact; twavg/avg within 1e-9
  modbus_image          exact integers — no tolerance
  loop_outputs          per-scan PID outputs within 1e-9

Why most of this is exact: the engine is deterministic integer-timed logic, so there is exactly one
right answer. A spurious alarm event, a missing one, or one at the wrong scan is not "close" — it is
an operator being told the wrong thing about a plant. Only genuine floats get a band.

The scenarios were hand-checked against independently computed sequences before any of this ran:
the on-delay firing on the third scan of the condition, no event when the condition breaks one scan
early, the deadband turning a chattering journal into one ACT/CLR pair, anti-windup pinning a
saturated loop, twavg differing materially from avg, and a Modbus value clamping at 65535. One of
those hand-checks disagreed with the reference and the REFERENCE turned out to be right — my
assertion had forgotten that a LO alarm was already active from the initial value. Recording that
here because the same mistake in the opposite direction is how a benchmark ships a wrong answer.

usage: verify.py --workspace <ws> --out <json> [--scada-cmd 'tmpl {scenario} {out}'] [--skip-env-check]
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

FORBIDDEN = ("pymodbus", "pyscada", "opcua", "asyncua", "scipy", "pandas", "simpy",
             "twisted", "matplotlib")
FLOAT_TOL = 1e-9


def near(a, b, tol=FLOAT_TOL):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def grade(ref, got, scen):
    """Return (journal_ok, hist_ok, modbus_ok, loops_ok, detail)."""
    d = {}

    # --- alarm journal: exact, including order
    rj, gj = ref["alarm_journal"], got.get("alarm_journal")
    if not isinstance(gj, list):
        journal_ok = False
        d["journal_why"] = "alarm_journal not reported"
    else:
        def norm(e):
            return (e.get("t_ms"), str(e.get("tag")), str(e.get("kind")),
                    str(e.get("event")), e.get("priority"))
        rn, gn = [norm(e) for e in rj], [norm(e) for e in gj]
        journal_ok = rn == gn
        if not journal_ok:
            missing = [e for e in rn if e not in gn][:3]
            spurious = [e for e in gn if e not in rn][:3]
            d["journal_n_ref"], d["journal_n_got"] = len(rn), len(gn)
            if missing:
                d["journal_missing"] = missing
            if spurious:
                d["journal_spurious"] = spurious
            if not missing and not spurious:
                d["journal_why"] = "same event set, but the order does not follow the specification's sort key"

    # --- historian: exact for integer aggregates, 1e-9 for averages
    rh, gh = ref["historian"], got.get("historian")
    hist_ok, bad_q = True, []
    if not isinstance(gh, list) or len(gh) != len(rh):
        hist_ok = False
        d["hist_why"] = f"expected {len(rh)} query results, got " + (
            "not a list" if not isinstance(gh, list) else str(len(gh)))
    else:
        for i, (rq, gq) in enumerate(zip(rh, gh)):
            agg = scen["queries"][i]["agg"]
            rv, gv = rq["value"], gq.get("value")
            ok = (rv == gv) if agg in ("count", "min", "max") else near(rv, gv)
            if not ok:
                hist_ok = False
                bad_q.append(f"q{i}({agg}): {gv} != {rv}")
        if bad_q:
            d["hist_bad"] = bad_q[:4]

    # --- modbus image: exact integers
    rm, gm = ref["modbus_registers"], got.get("modbus_registers")
    modbus_ok = isinstance(gm, list) and len(gm) == len(rm) and all(
        isinstance(a, int) and a == b for a, b in zip(gm, rm))
    if not modbus_ok:
        d["modbus_ref"], d["modbus_got"] = rm[:8], (gm[:8] if isinstance(gm, list) else gm)

    # --- loop outputs: per-scan floats
    rl, gl = ref["loop_outputs"], got.get("loop_outputs") or {}
    loops_ok, bad_l = True, []
    for lid, rseq in rl.items():
        gseq = gl.get(lid)
        if not isinstance(gseq, list) or len(gseq) != len(rseq):
            loops_ok = False
            bad_l.append(f"{lid}: expected {len(rseq)} samples, got " + (
                "missing" if gseq is None else str(len(gseq))))
            continue
        for i, (a, b) in enumerate(zip(rseq, gseq)):
            if a["t_ms"] != b.get("t_ms") or not near(a["out"], b.get("out")):
                loops_ok = False
                bad_l.append(f"{lid}@scan{i}: t={b.get('t_ms')} out={b.get('out')} "
                             f"expected t={a['t_ms']} out={a['out']}")
                break
    if bad_l:
        d["loops_bad"] = bad_l[:3]
    return journal_ok, hist_ok, modbus_ok, loops_ok, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scada-cmd", default=None,
                    help="calibration: command template with {scenario} and {out}")
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_scada_"))
    env = make_env(ws)
    env.pop("PYTHONPATH", None)
    manifest = json.loads((HERE / "manifest.json").read_text())["scenarios"]

    checks, metrics, per = {}, {}, {}
    checks["entrypoint"] = {"pass": (ws / "run_scada.sh").exists(), "detail": "run_scada.sh"}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"],
                     str(tmp), env, 180)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad,
                                     "detail": "forbidden: " + ", ".join(bad) if bad else "ok"}

    j_ok = h_ok = m_ok = l_ok = 0
    for name in manifest:
        scen = json.loads((HERE / "scenarios" / f"{name}.json").read_text())
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text())
        wd = tmp / name
        wd.mkdir(parents=True, exist_ok=True)
        sfile = wd / f"{name}.scenario.json"
        sfile.write_text(json.dumps(scen))
        ofile = wd / f"{name}.out.json"
        cmd = (a.scada_cmd.format(scenario=sfile, out=ofile).split() if a.scada_cmd
               else ["bash", str(ws / "run_scada.sh"), str(sfile), str(ofile)])
        rc, log = sh(cmd, str(wd), env, 600)
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
        jo, ho, mo, lo, d = grade(ref, got, scen)
        rec.update(d, journal=jo, hist=ho, modbus=mo, loops=lo)
        j_ok += jo
        h_ok += ho
        m_ok += mo
        l_ok += lo
        per[name] = rec

    n = len(manifest)
    metrics["per_scenario"] = per
    metrics["n_scenarios"] = n
    checks["alarm_journal"] = {
        "pass": j_ok == n,
        "detail": f"{j_ok}/{n} event sequences exact; mismatched: " +
                  ", ".join(f"{k}({v.get('journal_n_got','?')}/{v.get('journal_n_ref','?')})"
                            for k, v in per.items() if not v.get("journal"))[:300]}
    checks["historian_queries"] = {
        "pass": h_ok == n,
        "detail": f"{h_ok}/{n} queries all correct; mismatched: " +
                  ", ".join(f"{k}{v.get('hist_bad', [''])[:1]}"
                            for k, v in per.items() if not v.get("hist"))[:300]}
    checks["modbus_image"] = {
        "pass": m_ok == n,
        "detail": f"{m_ok}/{n} register images exact; mismatched: " +
                  ", ".join(k for k, v in per.items() if not v.get("modbus"))}
    checks["loop_outputs"] = {
        "pass": l_ok == n,
        "detail": f"{l_ok}/{n} loop outputs within 1e-9; mismatched: " +
                  ", ".join(f"{k}({v.get('loops_bad', [''])[:1]})"
                            for k, v in per.items() if not v.get("loops"))[:300]}

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")


if __name__ == "__main__":
    main()
