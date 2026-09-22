#!/usr/bin/env python3
"""Collect runs/*/*/results.json into results/summary.{json,md}."""
import os
import pathlib
import json, pathlib, collections
ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
rows = []
LEAK_PATTERNS = ("hidden/", "verify_baseline", "verify_post", "oracle_reference", "agent_revive/tasks", "../../")

def leak_audit(run_dir):
    """Did the agent touch anything outside its workspace that could reveal the hidden verifier?"""
    traj = run_dir / "trajectory.jsonl"
    hits = []
    if not traj.exists():
        return hits
    for line in open(traj):
        try: ev = json.loads(line)
        except Exception: continue
        if ev.get("type") != "assistant": continue
        for blk in ev["message"].get("content", []):
            if blk.get("type") == "tool_use":
                txt = json.dumps(blk.get("input", {}))
                for pat in LEAK_PATTERNS:
                    if pat in txt:
                        hits.append(pat); break
    return sorted(set(hits))
for r in sorted(ROOT.glob("runs/*/*/results.json")):
    d = json.loads(r.read_text())
    d["run_dir"] = str(r.parent.relative_to(ROOT))
    d["leak_audit"] = leak_audit(r.parent)
    ar = r.parent / "agent_result.json"
    d["interrupted"] = False
    if ar.exists():
        a = json.loads(ar.read_text())
        d["interrupted"] = bool(a.get("is_error")) and any(k in (a.get("result") or "") for k in ("API Error", "session limit", "usage limit", "rate limit", "cc_cli_limit_message"))
        d["max_turns_hit"] = a.get("subtype") == "error_max_turns" or (a.get("num_turns") or 0) >= (d.get("max_turns") or 10**9)
    rows.append(d)
(ROOT / "results").mkdir(exist_ok=True)
# Non-Claude models driven through the adapter are priced at the launch model's rate, so their
# cost_usd is fictional: keep the tokens and the verdict, blank the cost and flag it, so it cannot
# slip into a project total.
for _r in rows:
    if _r.get("launch_model") and _r.get("launch_model") != _r.get("model_id"):
        _r["cost_usd_fabricated"] = _r.get("cost_usd")
        _r["cost_usd"] = None
        _r["adapter_cost_excluded"] = True
(ROOT / "results" / "summary.json").write_text(json.dumps(rows, indent=1))
hdr = ["task", "tier", "condition", "model", "run_id", "baseline", "restored", "turns",
       "tool_calls", "cost_usd", "agent_min", "files", "+lines", "-lines", "tests_touched", "leak", "interrupted", "failed_checks"]
lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
for d in rows:
    diff = d.get("diff", {})
    failed = [k for k, v in d.get("post_checks", {}).items() if not v]
    lines.append("| " + " | ".join(str(x) for x in [
        d["task"], d.get("tier"), d["condition"], d["model"], d["run_id"],
        "PASS" if d.get("baseline_pass") else "fail",
        "**PASS**" if d.get("post_pass") else "fail",
        d.get("num_turns", "-"), d.get("n_tool_calls", "-"),
        f"{d['cost_usd']:.2f}" if d.get("cost_usd") is not None else "-",
        f"{d['agent_wall_s']/60:.1f}" if d.get("agent_wall_s") else "-",
        diff.get("n_files", "-"), diff.get("lines_added", "-"), diff.get("lines_deleted", "-"),
        len(diff.get("visible_tests_modified", [])) if diff else "-",
        ",".join(d.get("leak_audit", [])) or "-",
        "YES" if d.get("interrupted") else "-",
        ",".join(failed) or "-"]) + " |")
# per (task, condition, model) success rate
agg = collections.defaultdict(list)
for d in rows:
    agg[(d["task"], d["condition"], f'{d["model"]}@{d.get("max_turns", "-")}')].append(d.get("post_pass", False))
lines += ["", "| task | condition | model@max_turns | n | restore rate |", "|---|---|---|---|---|"]
for (t, c, m), v in sorted(agg.items()):
    lines.append(f"| {t} | {c} | {m} | {len(v)} | {sum(v)}/{len(v)} |")
md = "\n".join(lines)
(ROOT / "results" / "summary.md").write_text(md + "\n")
print(md)
