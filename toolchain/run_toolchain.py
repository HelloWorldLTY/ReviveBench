#!/usr/bin/env python3
"""Build the plcforge toolchain with an agent, then run the hidden acceptance suite.

Two phases:
  arch  — the agent produces ARCHITECTURE.md plus module skeletons and interface contracts only
  build — the agent implements the toolchain (optionally resuming from an arch workspace)

usage: run_toolchain.py --run <name> --model <model> [--phase build] [--max-turns 200]
                        [--from-arch <run>] [--fuzz-n 120]
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import time

ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
TC = ROOT / "toolchain"
RUNS = TC / "runs"

ARCH_PROMPT = """You are the architect of a multi-module industrial software project.

Read `PROJECT.md` in the workspace: it specifies `plcforge`, an IEC 61131-3 toolchain (compiler front end,
scan-cycle runtime, ladder-diagram front end, PLCopen XML interop, Modbus TCP server, historian).

In this phase you do **architecture only**. Deliver:
1. `ARCHITECTURE.md` — module decomposition, the responsibility of each module, and the data that flows
   between them. State the IR design explicitly and justify it: the IR is the contract between the front
   end and everything downstream.
2. `contracts/` — for every module boundary, a machine-checkable contract: a JSON Schema (or an equivalent
   precise description) of the data crossing it, plus at least one worked example.
3. `bin/` — the seven entry points as executable stubs with correct argument parsing that exit non-zero with
   a clear "not implemented" message. Getting the CLI surface right now avoids rework later.
4. `PLAN.md` — the implementation order, and for each module what will prove it correct.

Do not implement the modules in this phase. Optimise for a decomposition that a later implementer can build
module by module, verifying each in isolation before integration.
"""

BUILD_PROMPT = """You are building a multi-module industrial software system.

Read `PROJECT.md` in the workspace. It specifies `plcforge`, an IEC 61131-3 toolchain: compiler front end,
scan-cycle runtime, ladder-diagram front end, PLCopen XML interop, Modbus TCP server, and historian.
{arch_note}
Implement the whole system. What you should know about how it will be judged:

- The heaviest check is **differential fuzzing**: randomly generated Structured Text programs and input
  stimuli are run against a reference implementation, and your `bin/plc-run` output trace must match cell for
  cell. The generator exercises the full language — nested IF/CASE/FOR/WHILE, INT/DINT/REAL/TIME arithmetic,
  and all nine standard function blocks. Assume hundreds of programs you have never seen.
- Correctness of the standard function blocks (TON/TOF/TP/CTU/CTD/R_TRIG/F_TRIG/SR/RS) against the IEC timing
  semantics is where most implementations fail. The runtime clock is `scan * cycle_ms`; there is no wall clock.
- Integer overflow wraps two's-complement; integer division truncates toward zero; operator precedence and
  CASE range semantics follow the standard.
- The other checks cover: the seven CLI entry points, the IR contract (your IR must be consumable on its own),
  compiler diagnostics on malformed programs (with line numbers), a 10-program regression suite, ladder
  equivalence, PLCopen XML round-trip semantic equivalence, Modbus TCP conformance against a standard client,
  and historian queries.

Build it module by module and test each module before moving on: write your own test programs, compare
against what the IEC semantics require, and keep a record in `TESTING.md`. Pure Python standard library
(NumPy allowed); no existing IEC 61131-3 toolchain and no third-party Modbus library.

Work autonomously; do not ask questions.
"""


def log(m):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", default="us.anthropic.claude-fable-5-1[1m]")
    ap.add_argument("--phase", default="build", choices=["arch", "build"])
    ap.add_argument("--from-arch", default=None)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=21600)
    ap.add_argument("--fuzz-n", type=int, default=120)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()

    run = RUNS / a.run
    ws = run / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    shutil.copy(TC / "PROJECT.md", ws / "PROJECT.md")
    arch_note = ""
    if a.from_arch:
        src = RUNS / a.from_arch / "workspace"
        for item in ("ARCHITECTURE.md", "PLAN.md", "contracts", "bin"):
            s = src / item
            if s.is_dir():
                shutil.copytree(s, ws / item, dirs_exist_ok=True)
            elif s.exists():
                shutil.copy(s, ws / item)
        arch_note = ("\nAn earlier architecture phase left `ARCHITECTURE.md`, `PLAN.md`, `contracts/` and CLI "
                     "stubs in `bin/`. Follow that decomposition unless you find a concrete reason not to; "
                     "if you deviate, say so in ARCHITECTURE.md.\n")

    prompt = ARCH_PROMPT if a.phase == "arch" else BUILD_PROMPT.format(arch_note=arch_note)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env["PATH"] = f"{ROOT / 'envs' / 'py312_numpy' / 'bin'}:" + env["PATH"]
    bp = pathlib.Path.home() / ".tailscale" / "bedrock_proxy.json"
    if bp.exists() and os.environ.get("REVIVE_USE_BEDROCK", "1") == "1":
        cfg = json.loads(bp.read_text())
        cfg["ANTHROPIC_BEDROCK_BASE_URL"] = os.environ.get("REVIVE_BEDROCK_URL", "")
        env.update(cfg)

    log(f"phase={a.phase} model={a.model} max_turns={a.max_turns}")
    t0 = time.time()
    traj = run / f"trajectory_{a.phase}.jsonl"
    with open(traj, "wb") as fh, open(run / f"stderr_{a.phase}.log", "wb") as eh:
        try:
            p = subprocess.run(["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
                                "--dangerously-skip-permissions", "--max-turns", str(a.max_turns),
                                "--model", a.model],
                               cwd=str(ws), env=env, stdout=fh, stderr=eh, stdin=subprocess.DEVNULL,
                               timeout=a.timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    wall = round(time.time() - t0, 1)
    cost = turns = None
    final = ""
    for line in open(traj, errors="replace"):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "result":
            cost, turns, final = ev.get("total_cost_usd"), ev.get("num_turns"), (ev.get("result") or "")[:3000]
            (run / f"result_{a.phase}.json").write_text(json.dumps(ev, indent=1))
    log(f"agent done rc={rc} turns={turns} cost=${cost} wall={wall}s")

    # code volume actually written
    loc = 0
    for f in ws.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        try:
            loc += len(f.read_text(errors="replace").splitlines())
        except Exception:
            pass
    res = {"run": a.run, "phase": a.phase, "model": a.model, "rc": rc, "turns": turns,
           "cost_usd": cost, "wall_s": wall, "python_loc": loc, "final_message": final}

    if a.phase == "build":
        log("running hidden acceptance suite")
        rep = run / "acceptance.json"
        cmd = [str(ROOT / "envs" / "py312_numpy" / "bin" / "python"), str(TC / "verify_toolchain.py"),
               "--workspace", str(ws), "--out", str(rep), "--fuzz-n", str(a.fuzz_n)]
        if a.quick:
            cmd.append("--quick")
        v = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
        if rep.exists():
            r = json.loads(rep.read_text())
            res["score"] = r["score"]
            res["all_pass"] = r["pass"]
            res["checks"] = {k: c["pass"] for k, c in r["checks"].items()}
            res["details"] = {k: c.get("detail", "")[:200] for k, c in r["checks"].items()}
        else:
            res["score"] = "0/9"
            res["error"] = (v.stdout + v.stderr)[-500:]
        log(f"RESULT {a.run} score={res.get('score')} loc={loc}")
    (run / f"result_{a.phase}_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
