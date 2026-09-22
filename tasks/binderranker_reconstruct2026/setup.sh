#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -f "$WS/src/protein_design_agent/agent/providers/base.py"
rm -rf "$WS/tests"
find "$WS" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with pip and pytest; install the package with `pip install -e .` (add extras/dev deps as needed).
Internet (PyPI) is reachable. No GPU.
EON
cat > "$WS/SITUATION.md" <<'EON'
# Situation
The file `src/protein_design_agent/agent/providers/base.py` was lost. It is imported by 13 other module(s) of the package; the names they import
from it are: ProviderError, ProviderOutputError, RequestParserProvider, StructuredJSONProvider, validate_provider_payload. Its public definitions were: ProviderError, ProviderOutputError, RequestParserProvider, StructuredJSONProvider, validate_provider_payload.
The package's own test suite was also lost (tests); the package will be checked against it after restoration.
Everything else (README, docs, examples, the remaining modules and their call sites) is intact.
EON
