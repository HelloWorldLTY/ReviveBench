#!/usr/bin/env python3
"""Generic hidden verifier for reconstruction tasks: workspace code + pristine (hidden) test suite."""
import argparse, json, pathlib, re, shutil, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, finish
import tarfile
TASK = json.loads((HERE.parent / "task.json").read_text())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws); env.pop("PYTHONPATH", None)
    checks, metrics = {}, {}
    # overlay: agent's code + pristine tests
    testws = tmp / "testws"
    shutil.copytree(ws, testws, symlinks=True, ignore=shutil.ignore_patterns(".git", "venv", "__pycache__", "*.egg-info", ".pytest_cache"))
    pdir = tmp / "pristine"; pdir.mkdir()
    with tarfile.open(HERE / "pristine" / "repo.tar.gz") as t: t.extractall(pdir)
    for rel in TASK["hidden_tests"]:
        s, d = pdir / rel, testws / rel
        if s.is_dir(): shutil.rmtree(d, ignore_errors=True); shutil.copytree(s, d)
        elif s.exists(): d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(s, d)
    checks["target_module_present"] = {"pass": (ws / TASK["target_module"]).exists(), "detail": TASK["target_module"]}
    rc, out = sh(["bash", "-c", "pip install -q -e '.[test,dev]' 2>/dev/null || pip install -q -e . ; pip install -q pytest pytest-timeout >/dev/null 2>&1; echo INSTALL_RC=$?"], testws, env, 900)
    checks["install"] = {"pass": rc == 0 and "INSTALL_RC=0" in out, "detail": out[-1500:]}
    rc, out = sh([PY, "-c", f"import {TASK['package']}; import importlib; m=importlib.import_module('{TASK['package']}.' + {TASK['target_module']!r}.split('{TASK['package']}/')[-1][:-3].replace('/', '.')); print('IMPORT_OK', m.__file__)"], testws, env, 300)
    checks["import_target"] = {"pass": rc == 0 and "IMPORT_OK" in out, "detail": out[-1200:]}
    rc, out = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=300", "-x", "--maxfail=50"], testws, env, TASK.get("verify_timeout", 2400) - 300)
    summ = [l for l in out.splitlines() if re.search(r"\d+ (passed|failed|error)", l)]
    line = summ[-1] if summ else out[-300:]
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", line)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", line)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", line)) else 0
    metrics["tests"] = {"passed": passed, "failed": failed, "errors": errors, "oracle_passed": TASK["oracle_passed"], "summary": line}
    ok = failed == 0 and errors == 0 and passed >= 0.95 * TASK["oracle_passed"] and passed > 0
    checks["hidden_test_suite"] = {"pass": bool(ok), "detail": line + "\n" + out[-2500:]}
    finish(a.out, checks, metrics, tmp)

if __name__ == "__main__":
    main()
