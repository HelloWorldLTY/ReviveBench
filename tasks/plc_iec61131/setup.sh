#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples"; cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"
for n in motor_latch conveyor_count pulse_shaping; do mkdir -p "$WS/examples/$n"; cp "$HERE/hidden/programs/$n.st" "$HERE/hidden/programs/$n.csv" "$WS/examples/$n/"; cp "$HERE/hidden/ref/$n.csv" "$WS/examples/$n/expected_trace.csv"; done
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 (standard library + NumPy + pytest). No IEC 61131-3 toolchains.
EON
cat > "$WS/README.md" <<'EON'
# plcx
Clean-room IEC 61131-3 Structured Text runtime. Read SPEC.md. examples/<name>/ contain a program, a stimulus CSV
(one row per 10 ms scan) and the expected output trace; the hidden evaluation runs 10 programs (timers, counters, edge
detectors, set/reset flip-flops, CASE state machines, loops, user function blocks and functions, REAL arithmetic).
EON
