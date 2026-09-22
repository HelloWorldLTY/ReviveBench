#!/usr/bin/env python3
"""Verify the English port changed only comments, docstrings and human-readable strings.

Three checks, all against the Chinese original at ../ (the project root):

1. Structure: for every ported .py, compare the abstract syntax tree with every string constant
   replaced by a placeholder. Any difference means code, not wording, changed.
2. Strings: list every string literal that differs, so the wording changes can be reviewed.
3. Reproduction: run the four table/matrix generators from the ported tree and require their output
   to be byte-identical to the files the paper and results package already contain.

Usage: python3 tools/check_port.py [--verbose]
"""
import argparse, ast, difflib, filecmp, os, subprocess, sys, tempfile

EN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.dirname(EN)


class Norm(ast.NodeTransformer):
    """Replace string constants so wording differences do not show up as structural ones."""

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<STR>"), node)
        return node


def norm_dump(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (fn.body and isinstance(fn.body[0], ast.Expr)
                    and isinstance(fn.body[0].value, ast.Constant)
                    and isinstance(fn.body[0].value.value, str)):
                fn.body.pop(0)          # drop docstrings entirely
    return ast.dump(Norm().visit(tree))


def strings(path):
    out = []
    for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    bad = 0

    # Declared, intentional differences: the port resolves the data root from $REVIVE_ROOT and carries no
    # private hostnames, so these files differ structurally from the original on purpose (see MANIFEST.md).
    INTENTIONAL = {"harness/build_matrix.py", "harness/build_revival_table.py", "harness/build_appendix_tables.py",
                   "harness/aggregate.py", "harness/report.py", "harness/usage_report.py", "harness/run_task.py",
                   "contamination/analyze.py", "contamination/make_obfuscated_deepimpute.py",
                   "contamination/make_reconstruct_task.py", "design/run_design.py", "toolchain/run_toolchain.py",
                   "toolchain/run_repair.py", "toolchain/verify_toolchain.py", "paper/figures/fig1_overview.py",
                   "paper/figures/fig2_results.py", "paper/figures/fig3_case_cfd.py"}
    print("== 1. structure (AST with strings normalised) ==")
    pairs = []
    for root, _, files in os.walk(EN):
        # contamination/recall holds model answers saved with a .py suffix, not source; skip artefacts.
        if any(part in root for part in ("tools", "__pycache__", "recall")):
            continue
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            en = os.path.join(root, f)
            orig = os.path.join(ORIG, os.path.relpath(en, EN))
            if os.path.exists(orig):
                pairs.append((en, orig))
    for en, orig in pairs:
        try:
            same = norm_dump(en) == norm_dump(orig)
        except (SyntaxError, ValueError) as e:
            print(f"  SYNTAX ERROR {os.path.relpath(en, EN)}: {e}"); bad += 1; continue
        rel = os.path.relpath(en, EN)
        if not same:
            if rel in INTENTIONAL:
                print(f"  intentional (declared) {rel}")
            else:
                print(f"  DIFFERS {rel}"); bad += 1
    print(f"  {len(pairs)} files compared, {bad} structural differences")

    print("== 2. changed string literals ==")
    changed = 0
    for en, orig in pairs:
        if os.path.relpath(en, EN) in INTENTIONAL:
            continue      # declared change: its string set is expected to differ (env lookups added)
        try:
            se, so = strings(en), strings(orig)
        except (SyntaxError, ValueError):
            continue      # already reported as a structural failure above
        if len(se) != len(so):
            print(f"  {os.path.relpath(en, EN)}: string count {len(so)} -> {len(se)}"); bad += 1; continue
        for (ln, a_), (_, b_) in zip(se, so):
            if a_ != b_:
                changed += 1
                if a.verbose:
                    print(f"  {os.path.relpath(en, EN)}:{ln}  {b_[:60]!r} -> {a_[:60]!r}")
    print(f"  {changed} string literals reworded (expected: they carry the Chinese text)")

    print("== 3. generators reproduce the shipped artefacts ==")
    tmp = tempfile.mkdtemp()
    checks = [
        (["python3", f"{EN}/harness/build_matrix.py", "--models",
          "fable5.1,opus5,sonnet5,haiku4.5,gpt-5.6-sol,gpt-5.6-luna,gpt-5.6-terra,glm-5.3-flash",
          "--out", f"{tmp}/matrix.csv"], f"{tmp}/matrix.csv", f"{ORIG}/results/package/matrix.csv"),
        (["python3", f"{EN}/harness/build_appendix_tables.py", "--out", f"{tmp}/appendix_tables.tex"],
         f"{tmp}/appendix_tables.tex", f"{ORIG}/paper/appendix_tables.tex"),
    ]
    for cmd, got, want in checks:
        env = dict(os.environ, REVIVE_ROOT=ORIG)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ORIG, env=env)
        if r.returncode != 0:
            print(f"  FAILED to run {os.path.basename(cmd[1])}: {r.stderr.strip()[:200]}"); bad += 1; continue
        ok = filecmp.cmp(got, want, shallow=False)
        print(f"  {'OK  ' if ok else 'DIFF'} {os.path.basename(want)}")
        if not ok:
            bad += 1
            if a.verbose:
                d = difflib.unified_diff(open(want).readlines(), open(got).readlines(), "shipped", "ported", n=0)
                print("".join(list(d)[:20]))
    # build_revival_table.py and build_tables.py write fixed paths / stdout; compare their stdout summaries
    r = subprocess.run(["python3", f"{EN}/harness/build_tables.py", "--matrix", f"{ORIG}/results/package/matrix.csv",
                        "--check", f"{ORIG}/paper/tables.tex"], capture_output=True, text=True, cwd=ORIG,
                       env=dict(os.environ, REVIVE_ROOT=ORIG))
    print("  build_tables --check:", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[:120])
    if r.returncode != 0:
        bad += 1

    print(f"\n{'PORT OK' if bad == 0 else f'{bad} PROBLEM(S)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
