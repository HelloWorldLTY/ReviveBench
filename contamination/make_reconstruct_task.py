#!/usr/bin/env python3
"""Generate a T3-style reconstruction task from any pip-installable Python repo:
delete its highest fan-in module, hide its own test suite, verify by re-running that suite.
Usage: make_reconstruct_task.py <repo_dir> <task_id> "<oracle pytest summary line>"  [--module rel/path.py]"""
import os
import pathlib
import ast, json, pathlib, re, shutil, subprocess, sys, tarfile
ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
repo = pathlib.Path(sys.argv[1]).resolve(); task_id = sys.argv[2]; oracle_line = sys.argv[3]
forced = sys.argv[sys.argv.index("--module") + 1] if "--module" in sys.argv else None

def find_packages():
    pk = []
    for base in (repo, repo / "src"):
        if not base.exists(): continue
        for d in base.iterdir():
            if d.is_dir() and (d / "__init__.py").exists() and not d.name.startswith((".", "test")) and d.name not in ("tests", "docs", "examples", "scripts"):
                pk.append(d)
    return pk
pkgs = find_packages(); assert pkgs, "no package found"
pkg = max(pkgs, key=lambda d: sum(1 for _ in d.rglob("*.py")))
pkgname = pkg.name
mods = [p for p in pkg.rglob("*.py") if p.name not in ("__init__.py", "__main__.py", "_version.py", "version.py", "cli.py", "main.py", "conftest.py")]
def modname(p): return ".".join(p.relative_to(pkg).with_suffix("").parts)
src = {p: p.read_text(errors="replace") for p in mods}
fanin, names_from = {}, {}
def imports_of(q):
    """(module, [names]) pairs imported by module q, resolved to package-relative dotted names."""
    out = []
    try: tree = ast.parse(src[q])
    except Exception: return out
    qparts = modname(q).split(".")
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module is not None or isinstance(n, ast.ImportFrom) and n.level:
            if n.level:
                base = qparts[:-n.level] if n.level <= len(qparts) else []
                mod = ".".join(base + (n.module.split(".") if n.module else []))
            else:
                mod = n.module[len(pkgname) + 1:] if n.module.startswith(pkgname + ".") else (None if n.module != pkgname else "")
            if mod is None: continue
            out.append((mod, [a.name for a in n.names]))
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith(pkgname + "."): out.append((a.name[len(pkgname) + 1:], []))
    return out
imp = {q: imports_of(q) for q in mods}
for p in mods:
    mn = modname(p); parent = ".".join(mn.split(".")[:-1]); last = mn.split(".")[-1]
    users, imported = [], set()
    for q in mods:
        if q == p: continue
        hit = False
        for mod, names in imp[q]:
            if mod == mn: hit = True; imported |= set(names)
            elif mod == parent and last in names: hit = True; imported.add(last)
        if hit: users.append(q)
    fanin[p] = len(users); names_from[p] = sorted(x for x in imported if x != "*")
def nlines(p): return src[p].count("\n")
if forced:
    target = repo / forced
else:
    cands = [p for p in mods if 80 <= nlines(p) <= 900] or mods
    target = max(cands, key=lambda p: (fanin[p], nlines(p)))
try:
    tree = ast.parse(src[target]); public = sorted({n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith("_")})
except Exception: public = []
tests = sorted({str(p.relative_to(repo)).split("/")[0] if str(p.relative_to(repo)).startswith(("tests/", "test/")) else str(p.relative_to(repo))
                for p in repo.rglob("*.py") if re.search(r"(^|/)(tests?/|test_[^/]+\.py$|[^/]+_test\.py$|conftest\.py$)", str(p.relative_to(repo)))})
tests = [t for t in tests if not t.startswith(".")]
rel_target = str(target.relative_to(repo))
print(f"package={pkgname} target={rel_target} fanin={fanin[target]} lines={nlines(target)} public={public[:12]} tests={tests}")

T = ROOT / "tasks" / task_id
if T.exists(): shutil.rmtree(T)
(T / "hidden" / "pristine").mkdir(parents=True)
subprocess.run(["git", "archive", "--format=tar.gz", "-o", str(T / "hidden/pristine/repo.tar.gz"), "HEAD"], cwd=repo, check=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
(T / "hidden/pristine/commit.txt").write_text(head)
m = re.search(r"(\d+) passed", oracle_line); oracle_passed = int(m.group(1)) if m else 0
json.dump({"id": task_id, "tier": "T3-reconstruct-2026", "cohort": "post-cutoff-2026",
           "description": f"{pkgname}: module {rel_target} ({nlines(target)} lines, imported by {fanin[target]} modules) deleted and the package's own test suite hidden; verifier = the hidden suite ({oracle_passed} tests pass in a fresh env).",
           "source": f"{repo.name} @ {head}", "env": "py312_base", "package": pkgname, "target_module": rel_target,
           "public_names": public, "imported_names": names_from[target], "hidden_tests": tests, "visible_tests": [],
           "oracle_passed": oracle_passed, "oracle_summary": oracle_line, "verify_timeout": 2400, "constraints": {}},
          open(T / "task.json", "w"), indent=2)
(T / "setup.sh").write_text(f'''#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -f "$WS/{rel_target}"
{chr(10).join(f'rm -rf "$WS/{t}"' for t in tests)}
find "$WS" -name "__pycache__" -type d -prune -exec rm -rf {{}} + 2>/dev/null || true
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with pip and pytest; install the package with `pip install -e .` (add extras/dev deps as needed).
Internet (PyPI) is reachable. No GPU.
EON
cat > "$WS/SITUATION.md" <<'EON'
# Situation
The file `{rel_target}` was lost. It is imported by {fanin[target]} other module(s) of the package; the names they import
from it are: {", ".join(names_from[target]) or "(see call sites)"}. Its public definitions were: {", ".join(public) or "(unknown)"}.
The package's own test suite was also lost ({", ".join(tests) or "tests"}); the package will be checked against it after restoration.
Everything else (README, docs, examples, the remaining modules and their call sites) is intact.
EON
''')
(T / "setup.sh").chmod(0o755)
prompt = f'''You are restoring a Python scientific software package whose core module was lost.

Read SITUATION.md and ENVIRONMENT.md first. The file `{rel_target}` of package `{pkgname}` is missing, and so is the package's test suite. Reconstruct the module so that the package works exactly as it did before:
- Every name that other modules import from it must exist with the semantics implied by its call sites, README, docs and examples; keep the same public API (function/class names, signatures, return types, error behaviour) so that the original hidden test suite passes.
- Implement the actual functionality described by the documentation, not stubs. Match documented defaults, edge cases and numerical conventions exactly.
- `pip install -e .` must work and `import {pkgname}` must succeed; write your own tests for the reconstructed module and run them.

Finish by writing `RESTORE_NOTES.md` describing what you reconstructed and any uncertainty. Work autonomously; do not ask questions.
'''
(T / "prompt_default.md").write_text(prompt)
(T / "prompt_protocol.md").write_text(prompt.replace("Read SITUATION.md and ENVIRONMENT.md first.",
    "Follow this protocol strictly: (1) INVENTORY every call site, README/docs/example that references the missing module and write down the exact required signatures and behaviours; (2) map each documented behaviour to code; (3) IMPLEMENT the module faithfully; (4) VERIFY by exercising every call site and the documented examples end to end, and by writing tests for the reconstructed module; (5) REPORT. Read SITUATION.md and ENVIRONMENT.md first."))
shutil.copy(ROOT / "contamination" / "generic_reconstruct_verify.py", T / "hidden" / "verify.py")
print("task written:", T)
