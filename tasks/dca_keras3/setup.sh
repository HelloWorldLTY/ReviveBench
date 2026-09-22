#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
This workspace must work with the Python interpreter on PATH (`python`), which has:
- Python 3.11, TensorFlow >= 2.16 with Keras 3 (`import keras` -> 3.x), NumPy >= 2, pandas >= 2,
  scanpy >= 1.10, anndata >= 0.10, h5py, scipy, scikit-learn, pytest
You may `pip install` additional packages into this environment. You may NOT downgrade tensorflow, keras,
numpy, pandas, scanpy or anndata below those versions (verification checks this); `tf_keras`/legacy-Keras
shims are not allowed either: the code must run on Keras 3 itself.
EON
