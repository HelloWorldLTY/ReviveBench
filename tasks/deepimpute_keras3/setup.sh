#!/bin/bash
# materialize the broken workspace: pristine repo snapshot, nothing else
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -rf "$WS"/.travis.yml "$WS"/.bumpversion.cfg
# the agent gets a note describing the environment it must target
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
This workspace must work with the Python interpreter on PATH (`python`), which has:
- Python 3.11, TensorFlow >= 2.16 with Keras 3 (`import keras` -> 3.x), NumPy >= 2, pandas >= 2, scipy, scikit-learn, pytest
You may `pip install` additional packages into this environment. You may NOT downgrade
tensorflow, keras, numpy or pandas below those versions; verification checks this.
EON
