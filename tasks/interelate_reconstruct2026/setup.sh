#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -f "$WS/interelate/calculate_overlap_counts.py"
rm -rf "$WS/conftest.py"
rm -rf "$WS/test"
find "$WS" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with pip and pytest; install the package with `pip install -e .` (add extras/dev deps as needed).
Internet (PyPI) is reachable. No GPU.
EON
cat > "$WS/SITUATION.md" <<'EON'
# Situation
The file `interelate/calculate_overlap_counts.py` was lost. It is imported by 3 other module(s) of the package; the names they import
from it are: GenomicDistances, OverlapCounts, calculate_overlap_counts. Its public definitions were: calculate_overlap_counts, calculate_query_overlap_count.
The package's own test suite was also lost (conftest.py, test); the package will be checked against it after restoration.
Everything else (README, docs, examples, the remaining modules and their call sites) is intact.
EON
