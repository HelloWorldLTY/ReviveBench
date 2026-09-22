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

    simpy / pulp / ortools / pandas / networkx / scipy / matplotlib

Writing the discrete-event scheduling loop yourself is the task; there is no solver to call.

`run_mes.sh` is invoked as `bash run_mes.sh <scenario.json> <out.json>`, so it must be a **shell
script** with a shebang — not a Python file given a `.sh` name. It is invoked with an arbitrary
working directory and absolute path arguments: resolve your own files from the script's location,
never from `$PWD`.
EON

cat > "$WS/README.md" <<'EON'
# mesx

A manufacturing execution core: finite-capacity scheduling of work orders through routed
operations, FIFO lot consumption with genealogy, scrap and yield reconciliation, and OEE.
Read SPEC.md first, then ENVIRONMENT.md.

`examples/` pairs three scenarios with their expected answers: `<name>.scenario.json` is the input,
`<name>.expected.json` is the exact answer.

The dispatch rule is fully specified and the engine is deterministic, so there is exactly one
correct output per scenario. The schedule, the genealogy and the material balance are graded
**exactly** — an overlapping pair of operations on one work centre is not a near-miss, it is a plan
that cannot be executed. Only the OEE ratios carry a 1e-9 band.
EON
