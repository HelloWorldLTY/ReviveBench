"""Shared pieces for hidden verifiers. Verifiers run with the run's venv python (sys.executable)
and import the code under test from PYTHONPATH=<workspace>."""
import json, os, pathlib, subprocess, sys, tarfile, tempfile, shutil, glob

PY = sys.executable


def sh(cmd, cwd, env, timeout):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + "\n" + p.stderr)[-6000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def make_env(workspace):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(workspace)
    env["TF_CPP_MIN_LOG_LEVEL"] = "3"
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS", "4")
    return env


def check_env_constraints(constraints, tmp, env):
    """constraints: {package: 'MAJOR.MINOR'} minimum versions; uses __version__ so that
    tensorflow-cpu / tensorflow both count. Empty constraints -> trivially pass."""
    if not constraints:
        return {"pass": True, "detail": "no constraints"}, {}
    code = ("import json,importlib;print('VERS='+json.dumps({k:importlib.import_module(k).__version__ for k in %r}))"
            % list(constraints))
    rc, out = sh([PY, "-c", code], tmp, env, 180)
    line = [l for l in out.splitlines() if l.startswith("VERS=")]
    if rc != 0 or not line:
        return {"pass": False, "detail": out[-1500:]}, {}
    vers = json.loads(line[-1][5:])
    ok, notes = True, []
    for k, mn in constraints.items():
        have = tuple(int(x) for x in vers[k].split(".")[:2] if x.isdigit())
        need = tuple(int(x) for x in mn.split("."))
        if have < need:
            ok = False; notes.append(f"{k} {vers[k]} < {mn}")
    return {"pass": ok, "detail": json.dumps(vers) + (" ; DOWNGRADED: " + ", ".join(notes) if notes else "")}, vers


def pristine_tests_per_file(pristine_tar, tmp, env, pattern, timeout=1500, pytest_args=(),
                            workspace=None, overlay=()):
    """Run the pinned upstream test files against the WORKSPACE code.
    Layout: tmp/testws = copy of the workspace (agent's code) with the pristine versions of the
    paths in `overlay` (test files / fixture data) copied over it, so an agent cannot weaken the
    tests, and cwd/sys.path[0] is the agent's code, not the pristine snapshot.
    Each test file runs in its own process (avoids order-dependent state such as TF thread-pool init)."""
    tmp = pathlib.Path(tmp)
    pdir = tmp / "pristine"; pdir.mkdir(exist_ok=True)
    with tarfile.open(pristine_tar) as tf_:
        tf_.extractall(pdir)
    if workspace is None:
        testws = pdir
    else:
        testws = tmp / "testws"
        shutil.copytree(workspace, testws, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "venv", "__pycache__", "*.egg-info", ".pytest_cache"))
        for rel in overlay:
            src, dst = pdir / rel, testws / rel
            if src.is_dir():
                shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
            elif src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
    env = dict(env); env["PYTHONPATH"] = str(testws)
    files = sorted(glob.glob(str(testws / pattern)))
    per, all_ok, detail = {}, True, []
    for f in files:
        rel = os.path.relpath(f, testws)
        rc, out = sh([PY, "-m", "pytest", rel, "-q", "--no-header", "-p", "no:cacheprovider", *pytest_args],
                     testws, env, timeout)
        per[rel] = rc == 0
        all_ok &= rc == 0
        detail.append(f"### {rel}: {'PASS' if rc == 0 else 'FAIL'}\n" + out[-1200:])
    return {"pass": all_ok and bool(files), "per_file": per, "detail": "\n".join(detail)[-6000:]}


def finish(out_path, checks, metrics, tmp):
    required = {k: v for k, v in checks.items() if not v.get("informational")}
    result = {"pass": all(c["pass"] for c in required.values()), "checks": checks, "metrics": metrics}
    pathlib.Path(out_path).write_text(json.dumps(result, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({k: v["pass"] for k, v in checks.items()}), "PASS" if result["pass"] else "FAIL")
