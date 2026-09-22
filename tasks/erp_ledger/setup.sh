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

    pandas / sqlalchemy / django / odoo / erpnext / frappe
    beancount / ledger / piecash / gnucash / openpyxl / xlrd / scipy

`run_erp.sh` is invoked as `bash run_erp.sh <scenario.json> <out.json>`, so it must be a **shell
script** with a shebang — not a Python file given a `.sh` name. Both `python` and `python3` exist
here; name an interpreter explicitly rather than relying on one being the default.
EON

cat > "$WS/README.md" <<'EON'
# erpcore

The transactional core of an ERP system: double-entry general ledger, perpetual inventory with
moving-average valuation, and MRP. Read SPEC.md first, then ENVIRONMENT.md.

`examples/` pairs three scenarios with their expected answers: `<name>.scenario.json` is the input,
`<name>.expected.json` is what a reference implementation produced for it.

Everything is exact integer arithmetic — money in minor units, quantities in whole pieces. The
hidden evaluation runs a larger set of scenarios through
`bash run_erp.sh <scenario.json> <out.json>` and grades the transactional invariants, the trial
balance and the MRP plan with **no tolerance at all**: one cent out of balance is a wrong answer.
EON
