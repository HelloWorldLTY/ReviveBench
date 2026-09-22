#!/bin/bash
# fresh-env oracle: does each 2026 package install and pass its own tests? (no -x; collection errors tolerated)
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"/contamination
export PIP_CACHE_DIR=${REVIVE_PIP_CACHE:-$HOME/.cache/pip}
for n in brisc truecell scFair interelate binderranker figtracer kimlik BioSuite-Ultra sirna-data-grabber; do
  rm -rf envs/$n; ../envs/py312_base/bin/python -m venv envs/$n
  ( source envs/$n/bin/activate; cd cand/$n; (pip install -q -e ".[test,dev]" 2>/dev/null || pip install -q -e .) >/dev/null 2>&1; echo "$n: install_rc=$?"; pip install -q pytest pytest-timeout >/dev/null 2>&1
    timeout 1500 python -m pytest -q --timeout=300 -p no:cacheprovider --continue-on-collection-errors 2>&1 | grep -E "passed|failed|error" | tail -n 1 | sed "s/^/$n: SUMMARY /" )
done
echo ORACLE_TESTS_DONE
