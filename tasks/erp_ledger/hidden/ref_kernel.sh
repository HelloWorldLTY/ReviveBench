#!/usr/bin/env bash
# Reference entry point, used ONLY to calibrate the hidden verifier. It must score full marks;
# if it does not, the verifier or the assets are wrong, not the candidate.
#
# Note this is a genuine shell script invoked as `bash ref_kernel.sh ...`, exactly as the spec
# requires of the candidate's run_erp.sh. That contract is not a formality: on the cad3d task a
# model delivered a working 22KB engine but wrote Python statements straight into its .sh file,
# bash died with a syntax error, and all 13 models scored zero. Calibrating through a shell
# wrapper keeps this task's calibration honest about the same contract.
set -eu
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$HERE/ref_erp.py" "$1" "$2"
