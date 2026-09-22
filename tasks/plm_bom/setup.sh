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

    networkx / pandas / scipy / sqlalchemy / python-dateutil / arrow / pendulum / matplotlib

Graph traversal and date arithmetic are yours to write; the standard library's `datetime` is
available and is all you need.

`run_plm.sh` is invoked as `bash run_plm.sh <query.json> <out.json>`, so it must be a **shell
script** with a shebang — not a Python file given a `.sh` name. It is invoked with an arbitrary
working directory and absolute path arguments: resolve your own files from the script's location,
never from `$PWD`.
EON

cat > "$WS/README.md" <<'EON'
# plmx

A product lifecycle management core: revision-controlled parts with date effectivity,
variant-conditioned bills of material, BOM explosion with quantity roll-up, where-used analysis,
and engineering change impact. Read SPEC.md first, then ENVIRONMENT.md.

`examples/` pairs three query files with their expected answers: `<name>.query.json` is the input,
`<name>.expected.json` is the exact answer.

Every answer is a set or an integer fixed exactly by the rules, so **nothing in this task carries a
tolerance**. A part missing from an explosion, a quantity off by one, or an assembly missing from a
change's impact set is simply wrong.
EON
