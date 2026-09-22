#!/usr/bin/env bash
# Reference synthesis flow (Yosys), used ONLY to calibrate the hidden verifier.
# It must score full marks: if it does not, the verifier is wrong, not the candidate.
#
# usage: ref_synth.sh <design.v> <netlist.v>
set -eu
SRC=$1
OUT=$2
# tools come from the conda env (the OSS CAD Suite bundle needs glibc 2.35; this cluster has 2.28)
RROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
EDA="$RROOT/envs/eda_oracle/bin"
TOP=$(basename "$SRC" .v)
DIR=$(mktemp -d)
trap 'rm -rf "$DIR"' EXIT

cat > "$DIR/flow.ys" <<EOF
read_verilog $SRC
hierarchy -top $TOP
proc
opt
fsm
opt
memory
opt
techmap
opt
dfflegalize -cell \$_DFF_P_ 0
# lower word-level cells to bit-level first: abc only maps bit-level gates and silently
# passes word-level ones straight through to the netlist
simplemap
abc -g AND,OR,XOR,XNOR,NAND,NOR,MUX
opt_clean
write_verilog -noattr -noexpr $DIR/net.v
EOF

"$EDA/yosys" -q -s "$DIR/flow.ys"
# Yosys cannot round-trip Verilog gate primitives (it lowers `and u (y,a,b)` back into its own
# word-level cells), so the netlist stops at bit-level cells and is converted textually here.
python3 "$(cd "$(dirname "$0")" && pwd)/cellmap.py" "$DIR/net.v" "$OUT"
