#!/bin/bash
# Materialise the agent-facing workspace: spec, environment note, and three worked examples.
# Everything under hidden/ stays out of the workspace.
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples"
cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"
cp "$HERE"/hidden/examples/*.json "$WS/examples/"

cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)

`python` on PATH is Python 3.12 with NumPy and pytest, and nothing else. You may not install
anything. In particular none of these is available, and the verifier checks for them:

    OCP / cadquery / pythonocc-core / opencascade / trimesh / manifold3d / open3d
    pymesh / numpy-stl / meshio / scipy / shapely / gmsh / pyvista / vtk / matplotlib

Write `run_solid.sh` with a shebang and an explicit interpreter. `python` and `python3` both exist
here, but do not rely on an interpreter name that happens to exist only in this environment.
EON

cat > "$WS/README.md" <<'EON'
# solidx

A clean-room 3D solid modelling kernel. Read SPEC.md first, then ENVIRONMENT.md.

`examples/` pairs three models with their expected answers: `<name>.model.json` is the input you
will be given, `<name>.expected.json` is the answer a reference kernel produced for it (mass
properties and the point-membership results). Use them to check yourself as you go.

The hidden evaluation runs a larger set of models through `bash run_solid.sh <model.json> <out.json>`
and grades three things: the mass properties against an exact analytic kernel, the topology of the
STL you export (watertightness and Euler characteristic), and the point-membership answers, which
must be exactly right on every model.
EON
