#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
mkdir -p "$WS/examples_data"; cp "$HERE/hidden/data/1ubq.pdb" "$WS/examples_data/"
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 (no `distutils` module) in a conda environment at $CONDA_PREFIX, with NumPy >= 2, pip, pytest,
and a conda-forge C/C++ toolchain (gcc/g++, cmake, make, pkg-config). You may install more packages with
`pip install ...` or `mamba install -y -p $CONDA_PREFIX -c conda-forge ...` (e.g. glew, glm, libpng, freetype, libxml2,
msgpack-cxx, netcdf). You may NOT downgrade Python below 3.12 or NumPy below 2.0 (verification checks this), and you may not
install a pre-built PyMOL (conda `pymol-open-source`, pip `pymol` wheels): the PyMOL that runs must be built from THIS source tree.
No display is available: everything must work headless (`pymol -cq`, `pymol2.PyMOL()`, ray-traced `png`).
EON
