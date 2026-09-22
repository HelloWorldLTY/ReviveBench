#!/usr/bin/env python3
"""Result matrix for the 13 industrial tasks x models (replaces a matrix.csv computed ad hoc, with no script kept).

Score definition -- fixed per row, identical for every model in that row (the caption promises
within-row comparability):
  CASE        n_pass/n_total (cases): stats / spice / plc / fem / cad2d
  CHECK_NOENV checks, excluding env_constraints: synth / cad3d / erp / place_route / cfd
  CHECK_ALL   checks, all of them: scada / mes / plm
The old matrix.csv used check counts for the three GPT-5.6 columns in the first four rows while the
other columns used case counts -- 12 cells, and the reason this script exists. Definitions differ
across rows, which the caption states.

Each cell takes the best run for that (task, model): first post_pass, then the score ratio.
Only main-experiment run_ids (m*/p*/s*) count; hp* (headroom probes) and eff* (effort ablation) are
excluded, so a probe or an ablation run cannot slip into the main table unnoticed.

An infrastructure failure (no code written, final message a timeout or API error) is not a model
result: it is marked INFRA and never selected as the best run.
"""
import os
import json, glob, re, csv, sys, argparse
from pathlib import Path

ROOT = Path(os.environ.get("REVIVE_ROOT") or Path(__file__).resolve().parent.parent)
ROWS = [("stats_nist","CASE"),("spice_ngspice","CASE"),("plc_iec61131","CASE"),
        ("fem_nafems","CASE"),("cad2d_dxf","CASE"),
        ("synth_verilog","CHECK_NOENV"),("cad3d_brep","CHECK_NOENV"),("erp_ledger","CHECK_NOENV"),
        ("place_route","CHECK_NOENV"),("cfd_solver","CHECK_NOENV"),
        ("scada_dcs","CHECK_ALL"),("mes_exec","CHECK_ALL"),("plm_bom","CHECK_ALL")]
MODELS = ["fable5.1","opus5","sonnet5","haiku4.5","gpt-5.6-sol","gpt-5.6-luna","gpt-5.6-terra"]
MAIN_RID = re.compile(r"^(m|p|s)\d+$")
INFRA_MSG = re.compile(r"timed out|API Error|overloaded|connection", re.I)

# Restrict which runs a cell may use, by experimental condition (2026-09-13).
# The adapter used to write the output cap into max_completion_tokens, which this provider accepts
# but silently ignores, so early GLM runs had no cap at all, unlike the Claude models (Claude Code
# sends max_tokens=64000).
# Whole-run output <= 64K proves no single turn exceeded the cap, so cad3d/fem/plc/plm are equivalent
# under both conditions and keep m1;
# the other nine cells take only m4, the re-runs with the honoured max_tokens field; the uncapped
# earlier runs (m1/m2/m3) never participate.
_GLM_CAPPED = ["stats_nist", "spice_ngspice", "cad2d_dxf", "synth_verilog", "erp_ledger",
               "place_route", "cfd_solver", "scada_dcs", "mes_exec"]
ALLOW_RIDS = {("glm-5.3-flash", t): {"m4"} for t in _GLM_CAPPED}

def score(d, rule):
    if rule == "CASE":
        pm = d.get("post_metrics") or {}
        return pm.get("n_pass"), pm.get("n_total")
    ck = d.get("post_checks") or {}
    if rule == "CHECK_NOENV":
        ck = {k: v for k, v in ck.items() if k != "env_constraints"}
    return sum(1 for v in ck.values() if v is True), len(ck)

def is_infra(d):
    """No code written, and ended in a timeout or API error, or was cut off by the wall clock (agent_rc=124).

    The second clause closes a hole GLM m3 exposed: scada_dcs m3 ran the full 10800s, wrote nothing and
    left no final message, so the old rule counted it as a genuine failure (FAIL 1/6). Three hours with
    no line of code and no usable turn is not a model result.
    """
    added = (d.get("diff") or {}).get("lines_added")
    if added != 0:
        return False
    return bool(INFRA_MSG.search(d.get("agent_final_message") or "")) or d.get("agent_rc") == 124

def cell(task, rule, model):
    best = None; infra = 0
    for f in glob.glob(str(ROOT / f"runs/{task}/protocol__{model}__*/results.json")):
        rid = Path(f).parent.name.split("__")[-1]
        if not MAIN_RID.match(rid):
            continue
        if (model_key := (model, task)) in ALLOW_RIDS and rid not in ALLOW_RIDS[model_key]:
            continue
        d = json.load(open(f))
        if is_infra(d):
            infra += 1; continue
        n, t = score(d, rule)
        if n is None or not t:
            continue
        key = (bool(d.get("post_pass")), n / t)
        if best is None or key > best[0]:
            best = (key, "%s %d/%d" % ("PASS" if d.get("post_pass") else "FAIL", n, t), rid)
    if best is None:
        return ("INFRA" if infra else ""), None, infra
    return best[1], best[2], infra

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    models = a.models.split(",")
    rows = []; prov = []
    for task, rule in ROWS:
        r = {"task": task}
        for m in models:
            v, rid, infra = cell(task, rule, m)
            r[m] = v
            prov.append((task, m, rule, v, rid, infra))
        rows.append(r)
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["task"] + models); w.writeheader(); w.writerows(rows)
    with open(a.out.replace(".csv", "_provenance.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["task","model","rule","cell","best_run_id","infra_runs_excluded"])
        w.writerows(prov)

if __name__ == "__main__":
    main()
