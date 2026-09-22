#!/usr/bin/env python3
"""Recompute diff stats for every finished agent run (after a change to diff_stats)."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_task import ROOT, diff_stats
for r in ROOT.glob("runs/*/*/results.json"):
    d = json.loads(r.read_text())
    if d["condition"] == "noagent" or not (r.parent / "workspace").exists(): continue
    task = json.loads((ROOT / "tasks" / d["task"] / "task.json").read_text())
    d["diff"] = diff_stats(r.parent / "workspace", task.get("visible_tests", []))
    r.write_text(json.dumps(d, indent=1)); print(r.parent.name, d["diff"]["n_files"], d["diff"]["lines_added"], d["diff"]["lines_deleted"])
