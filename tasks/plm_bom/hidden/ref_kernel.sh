#!/usr/bin/env bash
# Reference entry point, used ONLY to calibrate the hidden verifier. It must score full marks;
# if it does not, the verifier or the assets are wrong, not the candidate.
#
# A genuine shell script resolving its own files from the script's location — the same two contract
# points the SPEC imposes on candidates, both of which have already cost this suite real false
# negatives (Python statements written into a .sh; a bare relative path that broke once the verifier
# invoked the launcher from a scratch directory).
set -eu
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$HERE/ref_plm.py" "$1" "$2"
