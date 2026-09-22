#!/usr/bin/env python3
"""Hidden verifier for mes_exec. Never visible to the candidate.

Runs with the RUN's venv python. The oracle (`ref_mes`) is pure standard library, so there is no
oracle environment and no subprocess delegation.

Graded checks:

  entrypoint          run_mes.sh exists
  env_constraints     no forbidden scheduling/dataframe package in the workspace env
  schedule            exact operations, times, quantities and ordering — no tolerance
  genealogy           exact lots, order and quantities; plus the stalled set — no tolerance
  material_balance    exact integers, and received - consumed = remaining must hold
  oee_metrics         1e-9 per ratio

The engine is deterministic integer-timed scheduling, so there is exactly one right answer and
"close" has no meaning for the first four. A schedule that overlaps two operations on one work
centre is not a near-miss, it is a plan that cannot be executed.

Assets were hand-checked before this ran: dispatch order by id and by priority, setup charged on
every run, floor-scrap compounding (200 -> 190 -> 181, where 9.5 must floor to 9), FIFO across
three lots, a starved order stalling while a lower-priority one proceeds, and OEE whose performance
falls to 0.2 under setup overhead.

usage: verify.py --workspace <ws> --out <json> [--mes-cmd 'tmpl {scenario} {out}'] [--skip-env-check]
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

FORBIDDEN = ("simpy", "pulp", "ortools", "pandas", "networkx", "scipy", "matplotlib")
TOL = 1e-9


def near(a, b):
    try:
        return abs(float(a) - float(b)) <= TOL
    except (TypeError, ValueError):
        return False


def grade(ref, got):
    d = {}

    # --- schedule: exact tuples in exact order
    rs, gs = ref["schedule"], got.get("schedule")
    if not isinstance(gs, list):
        sched_ok = False
        d["sched_why"] = "schedule not reported"
    else:
        key = lambda x: (x.get("wo"), x.get("op"), x.get("wc"), x.get("start_min"),
                         x.get("end_min"), x.get("qty_in"), x.get("qty_out"))
        rn, gn = [key(x) for x in rs], [key(x) for x in gs]
        sched_ok = rn == gn
        if not sched_ok:
            d["sched_n"] = f"{len(gn)} vs {len(rn)}"
            miss = [x for x in rn if x not in gn][:3]
            spur = [x for x in gn if x not in rn][:3]
            if miss:
                d["sched_missing"] = miss
            if spur:
                d["sched_spurious"] = spur
            if not miss and not spur:
                d["sched_why"] = "same operation set, but the ordering does not follow the specification"
            # finite capacity is worth reporting separately when it is the actual fault
            by = {}
            for x in gs:
                by.setdefault(x.get("wc"), []).append((x.get("start_min"), x.get("end_min")))
            for wc, ivs in by.items():
                ivs.sort(key=lambda p: (p[0] is None, p[0]))
                for i in range(len(ivs) - 1):
                    if None not in ivs[i] and None not in ivs[i + 1] and ivs[i][1] > ivs[i + 1][0]:
                        d["capacity_violation"] = f"{wc}: {ivs[i]} and {ivs[i+1]} overlap"
                        break

    # --- genealogy + stalled
    rg = {e["wo"]: [(c["lot"], c["material"], c["qty"]) for c in e["consumed"]]
          for e in ref["genealogy"]}
    gg_raw = got.get("genealogy")
    if not isinstance(gg_raw, list):
        gen_ok = False
        d["gen_why"] = "genealogy not reported"
    else:
        gg = {e.get("wo"): [(c.get("lot"), c.get("material"), c.get("qty"))
                            for c in (e.get("consumed") or [])] for e in gg_raw}
        gen_ok = rg == gg
        if not gen_ok:
            diff = [w for w in set(rg) | set(gg) if rg.get(w) != gg.get(w)][:3]
            d["gen_diff"] = {w: {"ref": rg.get(w), "got": gg.get(w)} for w in diff}
    stall_ok = sorted(map(str, got.get("stalled") or [])) == sorted(map(str, ref["stalled"]))
    if not stall_ok:
        d["stalled_ref"], d["stalled_got"] = ref["stalled"], got.get("stalled")
    gen_ok = gen_ok and stall_ok

    # --- material balance: exact, and the identity must hold on the candidate's own numbers
    ri = {x["material"]: (x["received"], x["consumed"], x["remaining"]) for x in ref["inventory"]}
    gi_raw = got.get("inventory")
    if not isinstance(gi_raw, list):
        bal_ok = False
        d["bal_why"] = "inventory not reported"
    else:
        gi = {x.get("material"): (x.get("received"), x.get("consumed"), x.get("remaining"))
              for x in gi_raw}
        bal_ok = ri == gi
        if not bal_ok:
            d["bal_diff"] = {m: {"ref": ri.get(m), "got": gi.get(m)}
                             for m in set(ri) | set(gi) if ri.get(m) != gi.get(m)}
        broken = [m for m, (rc, cs, rm) in gi.items()
                  if None not in (rc, cs, rm) and rc - cs != rm]
        if broken:
            bal_ok = False
            d["bal_identity_broken"] = broken[:4]

    # --- OEE
    ro = {x["wc"]: x for x in ref["oee"]}
    go_raw = got.get("oee")
    if not isinstance(go_raw, list):
        oee_ok = False
        d["oee_why"] = "oee not reported"
    else:
        go = {x.get("wc"): x for x in go_raw}
        oee_ok = set(ro) == set(go)
        bad = []
        for wc, r in ro.items():
            g = go.get(wc)
            if not g:
                continue
            for f in ("availability", "performance", "quality", "oee"):
                if not near(r[f], g.get(f)):
                    oee_ok = False
                    bad.append(f"{wc}.{f}: {g.get(f)} != {r[f]}")
        if bad:
            d["oee_bad"] = bad[:4]
    return sched_ok, gen_ok, bal_ok, oee_ok, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mes-cmd", default=None)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_mes_"))
    env = make_env(ws)
    env.pop("PYTHONPATH", None)
    manifest = json.loads((HERE / "manifest.json").read_text())["scenarios"]

    checks, metrics, per = {}, {}, {}
    checks["entrypoint"] = {"pass": (ws / "run_mes.sh").exists(), "detail": "run_mes.sh"}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"],
                     str(tmp), env, 180)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad,
                                     "detail": "forbidden: " + ", ".join(bad) if bad else "ok"}

    s_ok = g_ok = b_ok = o_ok = 0
    for name in manifest:
        scen = json.loads((HERE / "scenarios" / f"{name}.json").read_text())
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text())
        wd = tmp / name
        wd.mkdir(parents=True, exist_ok=True)
        sfile = wd / f"{name}.scenario.json"
        sfile.write_text(json.dumps(scen))
        ofile = wd / f"{name}.out.json"
        cmd = (a.mes_cmd.format(scenario=sfile, out=ofile).split() if a.mes_cmd
               else ["bash", str(ws / "run_mes.sh"), str(sfile), str(ofile)])
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
        so, go_, bo, oo, d = grade(ref, got)
        rec.update(d, sched=so, gen=go_, bal=bo, oee=oo)
        s_ok += so
        g_ok += go_
        b_ok += bo
        o_ok += oo
        per[name] = rec

    n = len(manifest)
    metrics["per_scenario"] = per
    metrics["n_scenarios"] = n
    checks["schedule"] = {
        "pass": s_ok == n,
        "detail": f"{s_ok}/{n} schedules exact; mismatched: " +
                  ", ".join(f"{k}({v.get('capacity_violation') or v.get('sched_n','?')})"
                            for k, v in per.items() if not v.get("sched"))[:300]}
    checks["genealogy"] = {
        "pass": g_ok == n,
        "detail": f"{g_ok}/{n} genealogy and stall sets exact; mismatched: " +
                  ", ".join(k for k, v in per.items() if not v.get("gen"))}
    checks["material_balance"] = {
        "pass": b_ok == n,
        "detail": f"{b_ok}/{n} material balances exact; mismatched: " +
                  ", ".join(f"{k}{'(identity broken)' if v.get('bal_identity_broken') else ''}"
                            for k, v in per.items() if not v.get("bal"))}
    checks["oee_metrics"] = {
        "pass": o_ok == n,
        "detail": f"{o_ok}/{n} OEE within 1e-9; mismatched: " +
                  ", ".join(f"{k}{v.get('oee_bad', [''])[:1]}"
                            for k, v in per.items() if not v.get("oee"))[:250]}

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")


if __name__ == "__main__":
    main()
