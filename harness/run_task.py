#!/usr/bin/env python3
"""ReviveBench runner.

One run = materialize a broken repo -> baseline verify (expect FAIL) -> let an agent
(Claude Code, headless) restore it -> hidden verify (expect PASS) -> results.json.

  python3 harness/run_task.py --task deepimpute_keras3 --condition default \
      --model fable --max-turns 60 --run-id s1

Layout of one run directory (runs/<task>/<condition>__<model>__<run_id>/):
  workspace/        what the agent sees (a fresh git repo; hidden/ is never copied here)
  venv/             per-run virtualenv layered on the task's base conda env
  verify_baseline.json / verify_post.json   output of the hidden verifier
  trajectory.jsonl  full Claude Code stream-json trace
  agent_result.json final 'result' event (cost, turns, duration)
  results.json      one-line-per-run summary consumed by aggregate.py
"""
import os
import string
import pathlib
import argparse, json, os, pathlib, re, shutil, subprocess, sys, time, datetime

ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
CONDA_BIN = (os.environ.get("REVIVE_CONDA_BIN")
             or str(pathlib.Path(os.environ.get("CONDA_EXE", "/usr/bin/conda")).parent))


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd, cwd=None, env=None, timeout=None, logfile=None, stdin=None):
    """Run a command, tee output to logfile, return (rc, tail_of_output)."""
    with open(logfile, "ab") if logfile else open(os.devnull, "wb") as fh:
        fh.write(f"\n$ {' '.join(map(str, cmd))}\n".encode())
        fh.flush()
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout, stdin=stdin)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            fh.write(b"\n[TIMEOUT]\n")
            rc = 124
    return rc


def make_env(base_env, venv, extra=None):
    env = dict(os.environ)
    # never let the child think it is nested inside another Claude Code session
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "PYTHONPATH",
              "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONNOUSERSITE"):
        env.pop(k, None)
    env["PATH"] = f"{venv}/bin:{base_env}/bin:{CONDA_BIN}:" + env["PATH"]
    env["VIRTUAL_ENV"] = str(venv)
    env["PYTHONNOUSERSITE"] = "1"
    env["TF_CPP_MIN_LOG_LEVEL"] = "2"
    env["PIP_CACHE_DIR"] = os.environ.get("REVIVE_PIP_CACHE") or str(ROOT / ".pip_cache")
    # route the agent's LLM calls through the Bedrock proxy on the tailnet box (via the login-node forwarder)
    bp = pathlib.Path.home() / ".tailscale" / "bedrock_proxy.json"
    if bp.exists() and os.environ.get("REVIVE_USE_BEDROCK", "1") == "1":
        cfg = json.loads(bp.read_text())
        cfg["ANTHROPIC_BEDROCK_BASE_URL"] = os.environ.get("REVIVE_BEDROCK_URL", "")
        env.update(cfg)
    env["CONDA_PKGS_DIRS"] = os.environ.get("REVIVE_CONDA_PKGS") or str(ROOT / ".conda_pkgs")
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS", "4")
    if extra:
        env.update(extra)
    return env


def git(workspace, *args):
    return subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True)


def diff_stats(workspace, visible_tests):
    """Patch size vs the baseline commit; existing visible tests that were modified/deleted are
    flagged separately from tests the agent added."""
    git(workspace, "add", "-A")
    # If the agent commits by itself, `diff --cached HEAD` is empty and the patch is recorded as 0 lines.
    # Eleven runs were affected (opus on CFD: +3258 lines recorded as 0; haiku on 2D CAD: +2397 as 0).
    # The right baseline is the first commit (the snapshot), which measures the same thing either way.
    base = git(workspace, "rev-list", "--max-parents=0", "HEAD").stdout.split()
    ref = base[0] if base else "HEAD"
    ns = git(workspace, "diff", "--cached", "--numstat", ref).stdout.strip().splitlines()
    status = git(workspace, "diff", "--cached", "--name-status", ref).stdout.strip().splitlines()
    IGNORE = ("build/", "dist/", ".gradle/", "__pycache__/", ".egg-info", "restore_logs/", "node_modules/", ".pytest_cache/", "/generated/")
    CODE_EXT = (".py", ".pyx", ".c", ".cc", ".cpp", ".h", ".hpp", ".cu", ".java", ".groovy", ".gradle", ".kts", ".sh",
                ".toml", ".cfg", ".ini", ".yml", ".yaml", ".json", ".txt", ".pml", ".properties", ".cmake", "CMakeLists.txt", "Makefile", "makefile")
    files, added, deleted, code_files, code_added, code_deleted = [], 0, 0, [], 0, 0
    for line in ns:
        a, d, f = line.split("\t", 2)
        if any(p in f or f.startswith(p) for p in IGNORE):
            continue
        files.append(f)
        ai, di = (int(a) if a.isdigit() else 0), (int(d) if d.isdigit() else 0)
        added += ai; deleted += di
        if f.endswith(CODE_EXT) and "/data/" not in f and not f.endswith(".md"):
            code_files.append(f); code_added += ai; code_deleted += di
    git(workspace, "reset", "-q")
    st = {}
    for line in status:
        parts = line.split("\t"); st[parts[-1]] = parts[0][0]
    is_test = lambda f: any(f.startswith(p) for p in visible_tests)
    return {"files_changed": files, "n_files": len(files), "lines_added": added, "lines_deleted": deleted,
            "code_files": len(code_files), "code_added": code_added, "code_deleted": code_deleted,
            "visible_tests_modified": [f for f in files if is_test(f) and st.get(f) in ("M", "D", "R")],
            "tests_added": [f for f in files if is_test(f) and st.get(f) == "A"]}


def parse_trajectory(traj_path):
    """Summarize a stream-json trace: tool-call histogram + final result event."""
    tools, result, n_assistant = {}, None, 0
    with open(traj_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                n_assistant += 1
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "tool_use":
                        tools[blk["name"]] = tools.get(blk["name"], 0) + 1
            elif ev.get("type") == "result":
                result = ev
    return tools, result, n_assistant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--condition", default="default",
                    help="prompt variant: default | protocol | noagent (baseline only)")
    ap.add_argument("--model", default="fable")
    ap.add_argument("--max-turns", type=int, default=80)
    ap.add_argument("--agent-timeout", type=int, default=5400, help="seconds")
    ap.add_argument("--run-id", default="s1")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    task_dir = ROOT / "tasks" / args.task
    task = json.loads((task_dir / "task.json").read_text())
    base_env = ROOT / "envs" / task["env"]
    assert (base_env / "bin" / "python").exists(), f"base env missing: {base_env}"

    # model ids from the Bedrock proxy contain dots/colons/brackets: keep a filesystem-safe slug for paths
    MODEL_SLUG = {"us.anthropic.claude-fable-5-1[1m]": "fable5.1", "us.anthropic.claude-opus-5[1m]": "opus5",
                  "us.anthropic.claude-sonnet-5": "sonnet5", "us.anthropic.claude-haiku-4-5-20251001-v1:0": "haiku4.5"}
    model_slug = MODEL_SLUG.get(args.model) or re.sub(r"[^A-Za-z0-9._-]", "-", args.model)
    run_name = f"{args.condition}__{model_slug}__{args.run_id}"
    run_dir = ROOT / "runs" / args.task / run_name
    if (run_dir / "results.json").exists() and not args.force:
        log(f"already done: {run_dir}")
        return
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    workspace = run_dir / "workspace"
    venv = run_dir / "venv"
    setup_log = run_dir / "setup.log"
    t_start = time.time()
    results = {"task": args.task, "tier": task.get("tier"), "condition": args.condition,
               "model": model_slug, "model_id": args.model, "run_id": args.run_id, "max_turns": args.max_turns,
               "started": datetime.datetime.now().isoformat(timespec="seconds"),
               "host": os.uname().nodename}

    # 1. per-run venv on top of the base env (agent's pip installs stay inside this run)
    if task.get("per_run_env") == "conda-clone":
        # full conda clone: the agent may `mamba install -p $CONDA_PREFIX ...` system libraries
        log("cloning conda env")
        rc = run([f"{CONDA_BIN}/mamba", "create", "-y", "-q", "-p", str(venv), "--clone", str(base_env)],
                 logfile=setup_log, timeout=3600,
                 env={**os.environ, "CONDA_PKGS_DIRS": os.environ.get("REVIVE_CONDA_PKGS") or str(ROOT / ".conda_pkgs")})
        assert rc == 0, "conda clone failed"
    else:
        log("creating venv")
        rc = run([str(base_env / "bin" / "python"), "-m", "venv", "--system-site-packages", str(venv)],
                 logfile=setup_log)
        assert rc == 0, "venv creation failed"
    extra = dict(task.get("extra_env", {}))
    # task.json names site-specific paths as ${VAR} so the task definition carries no machine paths.
    # Expand them here and fail loudly on an unset one: a half-expanded path would otherwise become a
    # silently wrong JAVA_HOME or CUDA_HOME, and the task would fail for an unrelated-looking reason.
    expand_env = dict(os.environ, REVIVE_ROOT=str(ROOT))
    for k, v in list(extra.items()):
        if isinstance(v, str):
            extra[k] = string.Template(v).safe_substitute(expand_env)
            assert "${" not in extra[k], (
                f"{task['id']}: extra_env[{k}] needs an environment variable that is not set: {v}")
    pp = extra.pop("PATH_PREPEND", None)
    env = make_env(base_env, venv, extra)
    if task.get("per_run_env") == "conda-clone":
        env["CONDA_PREFIX"] = str(venv)
    if pp:
        env["PATH"] = pp + ":" + env["PATH"]

    # 2. materialize the broken workspace
    log("materializing workspace")
    rc = run(["bash", str(task_dir / "setup.sh"), str(workspace)], env=env, logfile=setup_log,
             timeout=1800)
    assert rc == 0, "setup.sh failed (see setup.log)"
    if args.condition == "labagent" and task.get("domain_skill"):
        sk = ROOT / "industrial" / "skills" / task["domain_skill"] / "skills"
        assert sk.exists(), f"LabAgent skill missing: {sk}"
        shutil.copytree(sk, workspace / "skills", dirs_exist_ok=True)
        log(f"injected LabAgent skill {task['domain_skill']}")
    shutil.rmtree(workspace / ".git", ignore_errors=True)
    git(workspace, "init", "-q")
    git(workspace, "config", "user.email", "revive@bench")
    git(workspace, "config", "user.name", "revive")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-q", "-m", "baseline (broken)")

    verify = task_dir / "hidden" / "verify.py"
    vtimeout = task.get("verify_timeout", 1800)

    priv = ROOT / "private" / args.task / run_name   # not under the agent's reach while it runs
    priv.mkdir(parents=True, exist_ok=True)

    def do_verify(stage, where):
        out = where / f"verify_{stage}.json"
        rc = run([str(venv / "bin" / "python"), str(verify), "--workspace", str(workspace),
                  "--out", str(out)], cwd=str(where), env=env, timeout=vtimeout,
                 logfile=where / f"verify_{stage}.log")
        if out.exists():
            return json.loads(out.read_text())
        return {"pass": False, "checks": {}, "error": f"verifier crashed/timeout rc={rc}"}

    # 3. baseline: does it work without any agent?
    log("baseline verify")
    base = do_verify("baseline", priv)
    results["baseline_pass"] = bool(base.get("pass"))
    results["baseline_checks"] = {k: v.get("pass") for k, v in base.get("checks", {}).items()}
    log(f"baseline pass={results['baseline_pass']} checks={results['baseline_checks']}")

    # 4. agent
    if args.condition != "noagent":
        prompt_file = task_dir / f"prompt_{args.condition}.md"
        prompt = prompt_file.read_text()
        traj = priv / "trajectory.jsonl"
        # Non-Claude models driven through the local Anthropic<->OpenAI adapter must be launched under a
        # model name Claude Code recognises (otherwise its client-side check reports unrecognized_model);
        # the adapter substitutes the real upstream model. The run directory and results.json must still
        # record the real model, or a whole batch carries the wrong label. REVIVE_CLAUDE_MODEL overrides
        # only the argument passed to claude.
        launch_model = os.environ.get("REVIVE_CLAUDE_MODEL", args.model)
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions", "--max-turns", str(args.max_turns),
               "--model", launch_model]
        # Reasoning-effort ablation: the CLI silently falls back to the default level for an invalid value
        # and prints one warning line, so validate it here: better to refuse than to run an ablation in
        # which every arm is really the default.
        effort = os.environ.get("REVIVE_EFFORT")
        if effort:
            assert effort in ("low", "medium", "high", "xhigh", "max"), \
                f"REVIVE_EFFORT={effort!r} is not a valid level (low/medium/high/xhigh/max)"
            cmd += ["--effort", effort]
        results["effort"] = effort
        results["launch_model"] = launch_model
        results["upstream_model"] = args.model
        log(f"running agent: launch={launch_model} recorded={args.model} max_turns={args.max_turns}")
        t0 = time.time()
        with open(traj, "wb") as fh, open(run_dir / "agent_stderr.log", "wb") as eh:
            try:
                p = subprocess.run(cmd, cwd=str(workspace), env=env, stdout=fh, stderr=eh,
                                   timeout=args.agent_timeout, stdin=subprocess.DEVNULL)
                agent_rc = p.returncode
            except subprocess.TimeoutExpired:
                agent_rc = 124
        results["agent_wall_s"] = round(time.time() - t0, 1)
        results["agent_rc"] = agent_rc
        tools, res_ev, n_assist = parse_trajectory(traj)
        results["tool_calls"] = tools
        results["n_tool_calls"] = sum(tools.values())
        results["n_assistant_msgs"] = n_assist
        # 22 runs ended in an API error (502 / connection refused / DNS) yet were counted as genuine
        # failures because `interrupted` was never set, which depressed the overall pass rate by 11.7
        # points and hit models unevenly (opus5 8 runs vs sonnet5 3).
        # Detect infrastructure failures from the final message at write time, so no batch needs manual
        # triage afterwards.
        _api = re.compile(r"API Error|Connection refused|502 status|503 status|stopped arriving"
                          r"|Connection lost|reach the API server|overloaded", re.I)
        _final = ""
        if res_ev:
            _final = str(res_ev.get("result") or res_ev.get("error") or "")
        if agent_rc != 0 and _api.search(_final):
            results["infra_error"] = True
            results["infra_error_detail"] = _final[:200]
        if res_ev:
            (run_dir / "agent_result.json").write_text(json.dumps(res_ev, indent=1))
            results["cost_usd"] = res_ev.get("total_cost_usd")
            results["num_turns"] = res_ev.get("num_turns")
            results["agent_duration_ms"] = res_ev.get("duration_ms")
            results["agent_subtype"] = res_ev.get("subtype")
            u = res_ev.get("usage", {})
            results["tokens"] = {k: u.get(k) for k in ("input_tokens", "output_tokens",
                                                      "cache_read_input_tokens",
                                                      "cache_creation_input_tokens")}
            results["agent_final_message"] = (res_ev.get("result") or "")[:4000]
        log(f"agent done rc={agent_rc} turns={results.get('num_turns')} cost=${results.get('cost_usd')}")
        shutil.move(str(traj), run_dir / "trajectory.jsonl"); traj = run_dir / "trajectory.jsonl"
        results["diff"] = diff_stats(workspace, task.get("visible_tests", []))

    # 5. hidden verify after the agent
    log("post verify")
    for f in priv.glob("verify_baseline.*"):
        shutil.move(str(f), run_dir / f.name)
    post = do_verify("post", run_dir)
    results["post_pass"] = bool(post.get("pass"))
    results["post_checks"] = {k: v.get("pass") for k, v in post.get("checks", {}).items()}
    results["post_metrics"] = post.get("metrics", {})
    results["total_wall_s"] = round(time.time() - t_start, 1)
    results["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    (run_dir / "results.json").write_text(json.dumps(results, indent=1))
    log(f"RESULT task={args.task} cond={args.condition} baseline={results['baseline_pass']} "
        f"post={results['post_pass']} checks={results['post_checks']}")


if __name__ == "__main__":
    main()
