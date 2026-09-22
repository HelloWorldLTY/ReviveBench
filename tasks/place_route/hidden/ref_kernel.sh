#!/usr/bin/env bash
# Reference entry point, used ONLY to calibrate the hidden verifier. It must score full marks;
# if it does not, the verifier or the assets are wrong, not the candidate.
#
# This is a genuine shell script invoked as `bash ref_kernel.sh ...`, and it resolves its own
# files from the script's location rather than $PWD — exactly the two contract points the SPEC
# imposes on the candidate. Both have already cost this suite real false negatives: a model once
# wrote Python statements straight into its .sh file and bash died on line 5, and another used a
# bare relative path so all 13 designs failed with "can't open file". Calibrating through the
# same contract keeps the calibration honest about it.
set -eu
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$HERE/ref_pnr.py" "$1" "$2"
