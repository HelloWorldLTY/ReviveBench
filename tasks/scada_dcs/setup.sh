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

    pymodbus / pyscada / opcua / asyncua / scipy / pandas / simpy / twisted

There is no network and no real Modbus transport involved: the "register image" is simply the array
of values you compute at the final scan.

`run_scada.sh` is invoked as `bash run_scada.sh <scenario.json> <out.json>`, so it must be a **shell
script** with a shebang — not a Python file given a `.sh` name. It is invoked with an arbitrary
working directory and absolute path arguments: resolve your own files from the script's location,
never from `$PWD`.
EON

cat > "$WS/README.md" <<'EON'
# scadax

A SCADA/DCS runtime: deterministic scan engine, alarm state machine with deadband and delays, PID
loops with anti-windup, historian aggregates, and a Modbus holding-register image. Read SPEC.md
first, then ENVIRONMENT.md.

`examples/` pairs three scenarios with their expected answers: `<name>.scenario.json` is the input,
`<name>.expected.json` is the exact answer.

The engine is deterministic, so there is exactly one correct output for each scenario. The alarm
journal, the `count`/`min`/`max` queries and the register image are graded **exactly** — one
spurious event, one missing event, or one event at the wrong scan is a wrong answer. Only genuine
floats (PID outputs, `twavg`/`avg`) carry a 1e-9 band.
EON
