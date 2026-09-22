#!/bin/bash
# Materialise the agent-facing workspace: spec, environment note, and three worked examples.
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples"
cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"
cp "$HERE"/hidden/examples/*.json "$WS/examples/"

cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)

`python` on PATH is Python 3.12 with NumPy and pytest, and nothing else. You may not install
anything. In particular none of these is available, and the verifier checks for them:

    scipy / fenics / firedrake / fipy / sympy / petsc4py / pyamg / numba / jax / torch

Writing your own linear solvers — Thomas algorithm, conjugate gradient, multigrid, SOR — is part of
the task. NumPy's `fft` and array operations are available and fair game.

`run_cfd.sh` is invoked as `bash run_cfd.sh <case.json> <out.json>`, so it must be a **shell
script** with a shebang — not a Python file given a `.sh` name. It is invoked with an arbitrary
working directory and absolute path arguments: resolve your own files from the script's location,
never from `$PWD`.
EON

cat > "$WS/README.md" <<'EON'
# flowx

A CFD and nonlinear-CAE solver: incompressible channel flows, the unsteady Taylor-Green vortex,
viscous and inviscid Burgers, and a hyperelastic bar. Read SPEC.md first, then ENVIRONMENT.md.

`examples/` pairs three cases with their expected answers: `<name>.case.json` is the input,
`<name>.expected.json` is the exact closed-form answer.

Every case in the hidden set has a closed-form solution, so a mismatch means your discretisation is
wrong rather than that two implementations disagree. The tolerances were measured, not guessed: a
correct second-order scheme reaches them with between one and eight orders of magnitude to spare at
the grid resolutions the cases specify. Two checks carry no tolerance at all — the reported
divergence for the incompressible case, and the shock case's flux balance.
EON
