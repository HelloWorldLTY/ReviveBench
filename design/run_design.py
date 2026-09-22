#!/usr/bin/env python3
"""Design-on-demand: a natural-language part requirement goes in, a verified DXF comes out.

The agent gets a sandbox containing the CAD engine an earlier agent wrote from scratch
(playground/cadx) plus its spec, and must produce part.dxf using that engine's CLI.
It never sees the constraint list: an independent checker (design/verify_part.py, oracle env)
measures the geometry it produced.

usage: run_design.py --job <jobdir> --model <model> [--max-turns N]
  jobdir must contain: requirement.txt (free text) and constraints.json (hidden from the agent)
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
ORACLE_PY = ROOT / "envs" / "industrial_oracle" / "bin" / "python"
ENGINE = ROOT / "playground" / "cadx"

PROMPT = """You are a mechanical CAD design agent. Produce a 2D part that satisfies the requirement below.

## Requirement
{requirement}

## What you have
`cad_engine/` is a 2D CAD geometry kernel with a command-line interface. Read `cad_engine/SPEC.md` for the
exact command schema. Run it as:

    bash run_cad.sh <command.json> <out.json>

Supported operations: `write` (create a DXF from LINE / CIRCLE / ARC / LWPOLYLINE-with-bulges / TEXT entities),
`measure` (entity counts, layers, bbox, per-shape area / perimeter / centroid), `boolean` (union / intersection /
difference), `offset` (round-corner outward or inward offset), `fillet` (tangent arcs at every corner),
`transform` (scale, rotate, translate).

## Rules
- **All geometry must be produced by that engine.** You may use Python to compute coordinates and to drive the
  engine, but every boolean, offset, fillet and DXF write goes through `run_cad.sh`. Do not install or use ezdxf,
  shapely, OpenCASCADE or any other geometry library, and do not hand-write DXF files yourself.
- Deliver `part.dxf` at the workspace root: the finished part. Put through-holes on a layer whose name contains
  `HOLE`; the outer boundary goes on any other layer.
- Deliver `design_notes.md`: the dimensions you chose, why, and the engine calls you made.
- Verify your own work with the engine's `measure` before finishing, and state the measured numbers in the notes.
  Your part will then be checked independently against a hidden list of quantitative requirements, so be exact:
  where the requirement gives a number, hit it.

Work autonomously; do not ask questions.
"""


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--model", default="us.anthropic.claude-sonnet-5")
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--timeout", type=int, default=5400)
    a = ap.parse_args()

    job = pathlib.Path(a.job).resolve()
    requirement = (job / "requirement.txt").read_text().strip()
    ws = job / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    shutil.copytree(ENGINE, ws / "cad_engine", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    # the launcher lives at the workspace root for convenience
    (ws / "run_cad.sh").write_text(f'#!/usr/bin/env bash\nexec bash "{ws / "cad_engine" / "run_cad.sh"}" "$@"\n')
    (ws / "run_cad.sh").chmod(0o755)
    (ws / "REQUIREMENT.txt").write_text(requirement + "\n")

    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env["PATH"] = f"{ROOT / 'envs' / 'py312_numpy' / 'bin'}:" + env["PATH"]
    bp = pathlib.Path.home() / ".tailscale" / "bedrock_proxy.json"
    if bp.exists() and os.environ.get("REVIVE_USE_BEDROCK", "1") == "1":
        cfg = json.loads(bp.read_text())
        cfg["ANTHROPIC_BEDROCK_BASE_URL"] = os.environ.get("REVIVE_BEDROCK_URL", "")
        env.update(cfg)

    prompt = PROMPT.format(requirement=requirement)
    log(f"design agent: model={a.model} turns={a.max_turns}")
    t0 = time.time()
    traj = job / "trajectory.jsonl"
    with open(traj, "wb") as fh, open(job / "agent_stderr.log", "wb") as eh:
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
            cost, turns, final = ev.get("total_cost_usd"), ev.get("num_turns"), (ev.get("result") or "")[:2000]
            (job / "agent_result.json").write_text(json.dumps(ev, indent=1))
    log(f"agent done rc={rc} turns={turns} cost=${cost} wall={wall}s")

    part = ws / "part.dxf"
    res = {"job": job.name, "model": a.model, "requirement": requirement, "rc": rc,
           "turns": turns, "cost_usd": cost, "wall_s": wall, "final_message": final,
           "produced_part": part.exists()}
    if part.exists():
        out = job / "verification.json"
        v = subprocess.run([str(ORACLE_PY), str(ROOT / "design" / "verify_part.py"), str(part),
                            str(job / "constraints.json"), str(out)],
                           capture_output=True, text=True, timeout=900)
        if out.exists():
            res["verification"] = json.loads(out.read_text())
        else:
            res["verification"] = {"loaded": False, "error": (v.stdout + v.stderr)[-400:]}
    else:
        res["verification"] = {"loaded": False, "error": "no part.dxf produced"}
    res["score"] = res["verification"].get("score")
    res["all_pass"] = bool(res["verification"].get("all_pass"))
    (job / "result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    log(f"RESULT {job.name} score={res['score']} all_pass={res['all_pass']}")


if __name__ == "__main__":
    main()
