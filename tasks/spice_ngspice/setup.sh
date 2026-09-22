#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples"; cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"
for n in vdiv_ladder rc_step diode_dc; do mkdir -p "$WS/examples/$n"; cp "$HERE/hidden/netlists/$n.cir" "$WS/examples/$n/"; cp "$HERE/hidden/ref/$n.csv" "$WS/examples/$n/reference.csv"; done
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with NumPy and pytest only. No SciPy, no existing simulators (verification checks the environment).
EON
cat > "$WS/README.md" <<'EON'
# spicex
Clean-room SPICE-class circuit simulator. Read SPEC.md. examples/<name>/ contain a netlist and the reference output CSV
(from ngspice) in exactly the format the grader expects; the hidden evaluation uses 10 netlists (op / dc / tran, linear and
nonlinear: diodes, level-1 MOSFETs, PULSE/SIN/PWL sources, initial conditions with uic).
EON
