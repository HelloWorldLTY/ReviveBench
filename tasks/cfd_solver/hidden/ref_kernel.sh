#!/usr/bin/env bash
# Reference entry point, used ONLY to calibrate the hidden verifier. It must score full marks;
# if it does not, the verifier or the assets are wrong, not the candidate.
#
# A genuine shell script that resolves its own files from the script's location — the same two
# contract points the SPEC imposes on candidates, both of which have already cost this suite real
# false negatives elsewhere (Python statements written into a .sh, and a bare relative path).
set -eu
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec ${REVIVE_ROOT}/envs/py312_numpy/bin/python "$HERE/ref_flow.py" "$1" "$2"
