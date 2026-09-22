#!/usr/bin/env python3
"""Usage accounting for runs made through the tailnet Bedrock proxy.
Reads every run's agent_result.json (tokens + cost) and reports by model / task / day."""
import os
import pathlib
import json, pathlib, collections, sys
ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
rows = []
for r in sorted(ROOT.glob("runs/*/*/results.json")):
    d = json.loads(r.read_text())
    if d["condition"] == "noagent": continue
    ar = r.parent / "agent_result.json"
    u = (json.loads(ar.read_text()).get("usage") or {}) if ar.exists() else {}
    rows.append({"task": d["task"], "model": d["model"], "run": r.parent.name,
                 "cost": d.get("cost_usd") or 0.0, "turns": d.get("num_turns") or 0,
                 "in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
                 "cache_r": u.get("cache_read_input_tokens", 0), "cache_w": u.get("cache_creation_input_tokens", 0),
                 "pass": d.get("post_pass"), "day": (d.get("finished") or "")[:10],
                 "model_id": d.get("model_id", ""),
                 "proxy": str(d.get("model_id") or "").startswith("us.anthropic"),
                 # Non-Claude models via the local adapter: Claude Code prices them at the launch model's
                 # rate (claude-opus-4-8), so the dollar figure has nothing to do with the real upstream
                 # and is fictional. The tokens are real (passed through from the OpenAI usage field).
                 # They get their own section: tokens only, no cost, never added to any dollar total.
                 "adapter": bool(d.get("launch_model") and d.get("launch_model") != d.get("model_id"))})
def fmt(n): return f"{n/1e6:.2f}M" if n >= 1e6 else (f"{n/1e3:.0f}K" if n >= 1000 else str(n))
adapter_rows = [r for r in rows if r.get("adapter")]
rows = [r for r in rows if not r.get("adapter")]
proxy = [r for r in rows if r["proxy"]]
print(f"=== runs through the Bedrock proxy: {len(proxy)} ===")
if proxy:
    agg = collections.defaultdict(lambda: dict(n=0, ok=0, cost=0.0, i=0, o=0, cr=0, cw=0, turns=0))
    for r in proxy:
        a = agg[r["model"]]
        a["n"] += 1; a["ok"] += bool(r["pass"]); a["cost"] += r["cost"]; a["turns"] += r["turns"]
        a["i"] += r["in"]; a["o"] += r["out"]; a["cr"] += r["cache_r"]; a["cw"] += r["cache_w"]
    print(f"{'model':42s} {'n':>3s} {'pass':>5s} {'$':>8s} {'in':>7s} {'out':>7s} {'cache_r':>8s} {'cache_w':>8s} {'turns':>6s}")
    for m, a in sorted(agg.items(), key=lambda kv: -kv[1]["cost"]):
        print(f"{m[:42]:42s} {a['n']:>3d} {a['ok']:>2d}/{a['n']:<2d} {a['cost']:>8.2f} {fmt(a['i']):>7s} {fmt(a['o']):>7s} {fmt(a['cr']):>8s} {fmt(a['cw']):>8s} {a['turns']:>6d}")
    t = dict(cost=sum(r["cost"] for r in proxy), i=sum(r["in"] for r in proxy), o=sum(r["out"] for r in proxy),
             cr=sum(r["cache_r"] for r in proxy), cw=sum(r["cache_w"] for r in proxy))
    print(f"\ntotal: ${t['cost']:.2f} | new tokens {fmt(t['i']+t['o']+t['cw'])} (in {fmt(t['i'])} + out {fmt(t['o'])} + cache write {fmt(t['cw'])}) | cache read {fmt(t['cr'])}")
    byday = collections.Counter()
    for r in proxy: byday[r["day"]] += r["cost"]
    print("by day: " + " | ".join(f"{d} ${c:.2f}" for d, c in sorted(byday.items()) if d))
sub = [r for r in rows if not r["proxy"]]
print(f"\n=== earlier runs on the Claude Code subscription: {len(sub)}, ${sum(r['cost'] for r in sub):.2f} ===")
json.dump(rows, open(ROOT / "results" / "usage.json", "w"), indent=1)

# ---- non-Claude models via the adapter: tokens only, cost always shown as an em dash
if adapter_rows:
    agg = collections.defaultdict(lambda: dict(n=0, ok=0, i=0, o=0, turns=0))
    for r in adapter_rows:
        a = agg[r["model"]]
        a["n"] += 1; a["ok"] += bool(r["pass"]); a["turns"] += r["turns"]
        a["i"] += r["in"]; a["o"] += r["out"]
    print(f"\n=== runs through the local adapter (non-Claude models): {len(adapter_rows)} ===")
    print("cost column is an em dash: Claude Code prices these at the launch model's rate, which is\n"
          "fictional for them; the token counts are real.")
    print(f"{'model':30s} {'n':>3s} {'pass':>6s} {'$':>6s} {'in':>8s} {'out':>8s} {'turns':>6s}")
    for m, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        print(f"{m[:30]:30s} {a['n']:>3d} {a['ok']:>2d}/{a['n']:<2d} {'—':>6s} "
              f"{fmt(a['i']):>8s} {fmt(a['o']):>8s} {a['turns']:>6d}")
