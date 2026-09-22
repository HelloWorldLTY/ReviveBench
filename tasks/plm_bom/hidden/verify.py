#!/usr/bin/env python3
"""Hidden verifier for plm_bom. Never visible to the candidate.

Runs with the RUN's venv python. The oracle (`ref_plm`) is pure standard library, so there is no
oracle environment and no subprocess delegation.

Graded checks:

  entrypoint        run_plm.sh exists
  env_constraints   no forbidden graph/dataframe/date package in the workspace env
  explode           exact leaf sets and exact integer quantities — no tolerance
  where_used        exact ancestor sets — no tolerance
  effective_rev     exact revision or null — no tolerance
  eco_impact        exact impact sets — no tolerance
  cycle_detection   the right queries error, with the right part set — no tolerance

Nothing here carries a tolerance, and that is the point of the task rather than an oversight: every
answer is a set or an integer fixed exactly by the spec. A part missing from an explosion is the
wrong thing built; an assembly missing from a change's impact set is the wrong customer notified.

Assets were hand-checked before this ran: quantities summing across two paths (2·5 + 3·7 = 31),
three-level multiplication, a line expiring the day before the query date, an ECO closing a line on
29 February in a leap year, a variant switching between alternative children, a lapsed revision
returning null, two ECOs applied in effective-date order with the later superseding, and a cycle
that exists only under one option set.

One semantic that the first draft of the oracle left unstated — whether a part that is itself a leaf
explodes to `[]` or to one of itself — was pinned down in both the code and the SPEC before any
reference answer was generated. An unstated choice inside an oracle is how this suite's false
negatives have repeatedly been born.

usage: verify.py --workspace <ws> --out <json> [--plm-cmd 'tmpl {query} {out}'] [--skip-env-check]
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

FORBIDDEN = ("networkx", "pandas", "scipy", "sqlalchemy", "python-dateutil", "dateutil",
             "arrow", "pendulum", "matplotlib")


def grade(ref, got):
    """Return (per-kind ok counts, per-kind totals, detail)."""
    d = {}
    ok = {"explode": 0, "where_used": 0, "effective_rev": 0, "eco_impact": 0, "cycle": 0}
    tot = {"explode": 0, "where_used": 0, "effective_rev": 0, "eco_impact": 0, "cycle": 0}

    rres = ref["results"]
    gres = got.get("results")
    if not isinstance(gres, list) or len(gres) != len(rres):
        d["why"] = ("results not reported" if not isinstance(gres, list)
                    else f"expected {len(rres)} results, got {len(gres)}")
        for k in tot:
            tot[k] = sum(1 for r in rres if _bucket(r) == k)
        return ok, tot, d

    bad = []
    for i, (r, g) in enumerate(zip(rres, gres)):
        kind = _bucket(r)
        tot[kind] += 1
        if r.get("error") == "cycle":
            good = (g.get("error") == "cycle"
                    and sorted(map(str, g.get("cycle_parts") or [])) == r["cycle_parts"])
        elif r["kind"] == "explode":
            rl = [(x["part"], x["qty"]) for x in r["leaves"]]
            gl = [(x.get("part"), x.get("qty")) for x in (g.get("leaves") or [])]
            good = rl == gl
        elif r["kind"] in ("where_used", "eco_impact"):
            good = list(map(str, g.get("parts") or [])) == r["parts"]
        else:  # effective_rev
            good = g.get("rev") == r["rev"]
        if good:
            ok[kind] += 1
        else:
            bad.append(f"q{i}({r['kind']}): got={_short(g)} want={_short(r)}")
    if bad:
        d["bad"] = bad[:4]
    return ok, tot, d


def _bucket(r):
    if r.get("error") == "cycle":
        return "cycle"
    return r["kind"]


def _short(x):
    for k in ("leaves", "parts", "rev", "cycle_parts"):
        if k in x:
            v = x[k]
            s = json.dumps(v, ensure_ascii=False)
            return s if len(s) <= 90 else s[:90] + "…"
    return json.dumps(x, ensure_ascii=False)[:90]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plm-cmd", default=None)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_plm_"))
    env = make_env(ws)
    env.pop("PYTHONPATH", None)
    manifest = json.loads((HERE / "manifest.json").read_text())["cases"]

    checks, metrics, per = {}, {}, {}
    checks["entrypoint"] = {"pass": (ws / "run_plm.sh").exists(), "detail": "run_plm.sh"}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"],
                     str(tmp), env, 180)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad,
                                     "detail": "forbidden: " + ", ".join(bad) if bad else "ok"}

    agg_ok = {"explode": 0, "where_used": 0, "effective_rev": 0, "eco_impact": 0, "cycle": 0}
    agg_tot = dict(agg_ok)
    clean_cases = 0
    for name in manifest:
        q = json.loads((HERE / "queries" / f"{name}.json").read_text())
        ref = json.loads((HERE / "ref" / f"{name}.json").read_text())
        wd = tmp / name
        wd.mkdir(parents=True, exist_ok=True)
        qfile = wd / f"{name}.query.json"
        qfile.write_text(json.dumps(q))
        ofile = wd / f"{name}.out.json"
        cmd = (a.plm_cmd.format(query=qfile, out=ofile).split() if a.plm_cmd
               else ["bash", str(ws / "run_plm.sh"), str(qfile), str(ofile)])
        rc, log = sh(cmd, str(wd), env, 600)
        rec = {"rc": rc}
        if not ofile.exists():
            rec["why"] = f"no output: {log[-200:]}"
            per[name] = rec
            for r in ref["results"]:
                agg_tot[_bucket(r)] += 1
            per[name] = rec
            continue
        try:
            got = json.loads(ofile.read_text())
        except Exception as e:  # noqa: BLE001
            rec["why"] = f"unparseable output: {str(e)[:140]}"
            for r in ref["results"]:
                agg_tot[_bucket(r)] += 1
            per[name] = rec
            continue
        ok, tot, d = grade(ref, got)
        for k in agg_ok:
            agg_ok[k] += ok[k]
            agg_tot[k] += tot[k]
        rec.update(d, ok=sum(ok.values()), total=sum(tot.values()))
        if sum(ok.values()) == sum(tot.values()) and sum(tot.values()) > 0:
            clean_cases += 1
        per[name] = rec

    n = len(manifest)
    metrics["per_case"] = per
    metrics["n_cases"] = n
    metrics["clean_cases"] = clean_cases

    def mk(key, label):
        t = agg_tot[key]
        return {"pass": t > 0 and agg_ok[key] == t,
                "detail": f"{agg_ok[key]}/{t} {label}; mismatched: " +
                          ", ".join(f"{k}{v.get('bad', [''])[:1]}"
                                    for k, v in per.items()
                                    if v.get("ok") != v.get("total") or v.get("why"))[:260]}

    checks["explode"] = mk("explode", "explosions exact")
    checks["where_used"] = mk("where_used", "where-used sets exact")
    checks["effective_rev"] = mk("effective_rev", "effective revisions exact")
    checks["eco_impact"] = mk("eco_impact", "change-impact sets exact")
    checks["cycle_detection"] = mk("cycle", "cycle detection exact")

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")


if __name__ == "__main__":
    main()
