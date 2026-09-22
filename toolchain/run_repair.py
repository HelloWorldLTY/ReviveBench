#!/usr/bin/env python3
"""Repair round: hand the agent the failing acceptance checks (symptoms only, as a CI report would),
let it fix its own toolchain, then re-run the hidden suite.

The report deliberately contains no hidden test data — only the check names, pass/fail, and the
first observable symptom, which is what a real CI run would surface.

usage: run_repair.py --run <run> --model <model> [--max-turns 80] [--fuzz-n 150]
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
TC = ROOT / "toolchain"
RUNS = TC / "runs"

PROMPT = """Your `plcforge` toolchain was run against the acceptance suite. Here is the report.

{report}

Fix what is failing. Notes on how to read this:

- The report gives symptoms, not the tests. Reproduce each failure yourself from the symptom, using
  programs you write, before changing anything.
- A failing check may be a small defect in one module rather than a design problem; find the root cause
  instead of special-casing the symptom.
- Do not weaken your own checks to make a failure disappear. If you believe a reported failure is
  actually correct behaviour on your side, say so explicitly in `REPAIR_NOTES.md` with the reasoning,
  and leave the behaviour alone.
- Everything the original brief said still holds: pure standard library, no existing IEC 61131-3
  toolchain, no third-party Modbus library, module boundaries intact.

When you are done, write `REPAIR_NOTES.md`: what each failure turned out to be, what you changed, and
how you convinced yourself it is fixed. Work autonomously; do not ask questions.
"""


def log(m):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def render(acc):
    lines = [f"total {acc['score']}", ""]
    for name, c in acc["checks"].items():
        mark = "PASS" if c["pass"] else "FAIL"
        lines.append(f"[{mark}] {name}")
        if not c["pass"]:
            lines.append(f"       symptom: {c.get('detail', '')[:300]}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", default="us.anthropic.claude-fable-5-1[1m]")
    ap.add_argument("--max-turns", type=int, default=80)
    ap.add_argument("--timeout", type=int, default=14400)
    ap.add_argument("--fuzz-n", type=int, default=150)
    a = ap.parse_args()

    run = RUNS / a.run
    ws = run / "workspace"
    acc = json.loads((run / "acceptance.json").read_text())
    before = acc["score"]
    report = render(acc)
    (run / "repair_report_in.txt").write_text(report)

    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env["PATH"] = f"{ROOT / 'envs' / 'py312_numpy' / 'bin'}:" + env["PATH"]
    bp = pathlib.Path.home() / ".tailscale" / "bedrock_proxy.json"
    if bp.exists() and os.environ.get("REVIVE_USE_BEDROCK", "1") == "1":
        cfg = json.loads(bp.read_text())
        cfg["ANTHROPIC_BEDROCK_BASE_URL"] = os.environ.get("REVIVE_BEDROCK_URL", "")
        env.update(cfg)

    log(f"repair round on {a.run}, before={before}")
    t0 = time.time()
    traj = run / "trajectory_repair.jsonl"
    with open(traj, "wb") as fh, open(run / "stderr_repair.log", "wb") as eh:
        try:
            p = subprocess.run(["claude", "-p", PROMPT.format(report=report), "--output-format", "stream-json",
                                "--verbose", "--dangerously-skip-permissions", "--max-turns", str(a.max_turns),
                                "--model", a.model],
                               cwd=str(ws), env=env, stdout=fh, stderr=eh, stdin=subprocess.DEVNULL,
                               timeout=a.timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    wall = round(time.time() - t0, 1)
    cost = turns = None
    for line in open(traj, errors="replace"):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "result":
            cost, turns = ev.get("total_cost_usd"), ev.get("num_turns")
    log(f"repair agent done rc={rc} turns={turns} cost=${cost} wall={wall}s")

    rep = run / "acceptance_after_repair.json"
    subprocess.run([str(ROOT / "envs" / "py312_numpy" / "bin" / "python"), str(TC / "verify_toolchain.py"),
                    "--workspace", str(ws), "--out", str(rep), "--fuzz-n", str(a.fuzz_n)],
                   capture_output=True, text=True, timeout=14400)
    after = json.loads(rep.read_text()) if rep.exists() else {"score": "?", "checks": {}}
    res = {"run": a.run, "model": a.model, "before": before, "after": after.get("score"),
           "turns": turns, "cost_usd": cost, "wall_s": wall, "rc": rc,
           "checks_after": {k: c["pass"] for k, c in after.get("checks", {}).items()},
           "details_after": {k: c.get("detail", "")[:200] for k, c in after.get("checks", {}).items()}}
    (run / "repair_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    log(f"REPAIR RESULT {a.run} {before} -> {after.get('score')}")


if __name__ == "__main__":
    main()
