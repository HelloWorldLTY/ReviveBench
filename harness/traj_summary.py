#!/usr/bin/env python3
"""Print a compact view of a Claude Code stream-json trajectory: tool calls (with the command /
file), and assistant text. Usage: traj_summary.py <run_dir> [--full]"""
import json, sys, pathlib
run = pathlib.Path(sys.argv[1]); full = "--full" in sys.argv
i = 0
for line in open(run / "trajectory.jsonl"):
    try: ev = json.loads(line)
    except Exception: continue
    if ev.get("type") == "assistant":
        for blk in ev["message"].get("content", []):
            if blk.get("type") == "text" and blk["text"].strip():
                t = blk["text"].strip().replace("\n", " ")
                print(f"  [text] {t if full else t[:220]}")
            elif blk.get("type") == "tool_use":
                i += 1; inp = blk.get("input", {})
                arg = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("description") or ""
                arg = str(arg).replace("\n", " ")
                print(f"{i:3d} {blk['name']:<10} {arg if full else arg[:160]}")
    elif ev.get("type") == "result":
        print(f"== result: {ev.get('subtype')} turns={ev.get('num_turns')} cost=${ev.get('total_cost_usd'):.2f} dur={ev.get('duration_ms',0)/60000:.1f}min")
