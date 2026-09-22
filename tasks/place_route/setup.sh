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

    openroad / klayout / gdstk / gdspy / shapely / networkx / scipy / rtree / matplotlib

`run_pnr.sh` is invoked as `bash run_pnr.sh <design.json> <out.json>`, so it must be a **shell
script** with a shebang — not a Python file given a `.sh` name. It is invoked with an arbitrary
working directory and absolute path arguments: resolve your own files from the script's location,
never from `$PWD`.
EON

cat > "$WS/README.md" <<'EON'
# prx

A standard-cell place-and-route engine: legalised row placement with blockages, then two-layer
grid routing with vias. Read SPEC.md first, then ENVIRONMENT.md.

`examples/` pairs three designs with a legal reference solution: `<name>.design.json` is the input,
`<name>.solution.json` is one valid answer produced by a reference engine. Note it is *a* valid
answer, not *the* answer — any layout satisfying the rules passes, and yours may differ.

The hidden evaluation runs a larger set of designs through
`bash run_pnr.sh <design.json> <out.json>`. Placement legality, routing correctness and the
self-consistency of your reported wirelength are graded with **no tolerance**; wirelength quality
against the reference router is informational only.
EON
