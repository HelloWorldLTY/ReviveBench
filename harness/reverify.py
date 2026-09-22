#!/usr/bin/env python3
"""Re-run the hidden verifier on finished runs (after a verifier fix) and update results.json.
Usage: reverify.py <run_dir> [<run_dir> ...]"""
import json, pathlib, subprocess, sys, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_task import make_env, ROOT, diff_stats
for rd in sys.argv[1:]:
    rd = pathlib.Path(rd).resolve(); res = json.loads((rd / "results.json").read_text())
    task = json.loads((ROOT / "tasks" / res["task"] / "task.json").read_text())
    base_env = ROOT / "envs" / task["env"]; venv = rd / "venv"
    extra = dict(task.get("extra_env", {})); pp = extra.pop("PATH_PREPEND", None)
    env = make_env(base_env, venv, extra)
    if pp: env["PATH"] = pp + ":" + env["PATH"]
    if task.get("per_run_env") == "conda-clone": env["CONDA_PREFIX"] = str(venv)
    out = rd / "verify_post.json"
    with open(rd / "verify_post.log", "ab") as lg:
        lg.write(b"\n=== reverify ===\n")
        subprocess.run([str(venv / "bin" / "python"), str(ROOT / "tasks" / res["task"] / "hidden" / "verify.py"),
                        "--workspace", str(rd / "workspace"), "--out", str(out)], cwd=str(rd), env=env,
                       stdout=lg, stderr=subprocess.STDOUT, timeout=task.get("verify_timeout", 1800))
    post = json.loads(out.read_text())
    res["post_pass"] = bool(post["pass"]); res["post_checks"] = {k: v["pass"] for k, v in post["checks"].items()}
    res["post_metrics"] = post.get("metrics", {}); res["reverified"] = True
    if res.get("condition") != "noagent":
        res["diff"] = diff_stats(rd / "workspace", task.get("visible_tests", []))
    (rd / "results.json").write_text(json.dumps(res, indent=1))
    print(rd.name, res["post_pass"], res["post_checks"])
