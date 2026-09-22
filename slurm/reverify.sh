#!/bin/bash
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
python3 harness/reverify.py "$@"
