#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -rf "$WS"/.travis.yml "$WS"/.bumpversion.cfg
rm -f "$WS/deepimpute/multinet.py"            # <- the lost module
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.9 with TensorFlow 2.10 / Keras 2.10, NumPy 1.23, pandas 1.5, scipy, scikit-learn, pytest
(the versions this package was written for). Do not change these packages.
EON
cat > "$WS/SITUATION.md" <<'EON'
# Situation
The file `deepimpute/multinet.py` (the core of the package: class `MultiNet` plus module-level helpers
`get_distance_matrix`, `wMSE`, `inspect_data`) was lost. Everything else is intact: `deepImpute.py`
(CLI wrapper that shows how MultiNet is called), `parser.py` (CLI flags and their documented defaults),
`util.py`, `maskedArrays.py`, `tests/` (exercise the API), README.md and the paper:
Arisdakessian C, Poirion O, Yunits B, Garmire L. "DeepImpute: an accurate, fast, and scalable deep neural
network method to impute single-cell RNA-seq data." Genome Biology 2019, 20:211.
EON
