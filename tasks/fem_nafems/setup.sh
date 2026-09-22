#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples/cantilever_cps8" "$WS/examples/cantilever_modal_cps8"; cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"
cp "$HERE/hidden/models/cantilever_cps8.inp" "$WS/examples/cantilever_cps8/model.inp"; cp "$HERE/hidden/ref/cantilever_cps8.json" "$WS/examples/cantilever_cps8/reference.json"
cp "$HERE/hidden/models/cantilever_modal_cps8.inp" "$WS/examples/cantilever_modal_cps8/model.inp"; cp "$HERE/hidden/ref/cantilever_modal_cps8.json" "$WS/examples/cantilever_modal_cps8/reference.json"
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with NumPy and pytest only. No SciPy, no FE/mesh libraries (verification checks the environment).
EON
cat > "$WS/README.md" <<'EON'
# femx
Clean-room linear FE solver. Read SPEC.md. examples/ contain a static cantilever (tip load; reference nodal displacements
from a production solver) and its modal analysis (reference eigenfrequencies). Hidden benchmarks add a thick cylinder under
internal pressure (plane strain, CPE8, mapped mesh) and a plate with a hole under tension (CPS8, ~3700 nodes) where nodal
stresses at the hole are checked against the Kirsch solution.
EON
