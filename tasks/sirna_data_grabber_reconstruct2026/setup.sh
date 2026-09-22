#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -f "$WS/src/sirna_data/rank_confidence.py"
rm -rf "$WS/tests"
find "$WS" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with pip and pytest; install the package with `pip install -e .` (add extras/dev deps as needed).
Internet (PyPI) is reachable. No GPU.
EON
cat > "$WS/SITUATION.md" <<'EON'
# Situation
The file `src/sirna_data/rank_confidence.py` was lost. It is imported by 2 other module(s) of the package; the names they import
from it are: _default_k_values, min_top_k_for_confidence, probability_curves_for_pccs. Its public definitions were: min_top_k_for_confidence, min_top_k_for_confidence_multi, probability_curves_for_pccs, probability_true_top_in_predicted_top_k, spearman_to_pearson.
The package's own test suite was also lost (tests); the package will be checked against it after restoration.
Everything else (README, docs, examples, the remaining modules and their call sites) is intact.
EON
