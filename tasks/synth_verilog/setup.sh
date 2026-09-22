#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples"
cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"
cp "$HERE/hidden/designs/cells.v" "$WS/cells.v"

cat > "$WS/examples/mux2.v" <<'EOF'
module mux2(input a, input b, input sel, output y);
  assign y = sel ? b : a;
endmodule
EOF

cat > "$WS/examples/mux2_netlist.v" <<'EOF'
// One legal netlist for examples/mux2.v — shown so the expected output form is unambiguous.
// Only gate primitives, wires, and (for sequential designs) the DFF cell from cells.v.
module mux2(input a, input b, input sel, output y);
  wire nsel, t0, t1;
  not g0 (nsel, sel);
  and g1 (t0, a, nsel);
  and g2 (t1, b, sel);
  or  g3 (y, t0, t1);
endmodule
EOF

cat > "$WS/examples/toggle.v" <<'EOF'
// A sequential example (no reference netlist given): synchronous reset and an enable must both
// be built out of gates around the plain DFF cell.
module toggle(input clk, input rst, input en, output reg q);
  always @(posedge clk) begin
    if (rst) q <= 1'b0;
    else if (en) q <= ~q;
  end
endmodule
EOF

cat > "$WS/examples/addsub4.v" <<'EOF'
// A wider combinational example: vectors, arithmetic and a conditional.
module addsub4(input [3:0] a, input [3:0] b, input sub, output [3:0] y, output cout);
  wire [4:0] t;
  assign t = sub ? (a - b) : (a + b);
  assign y = t[3:0];
  assign cout = t[4];
endmodule
EOF

cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with NumPy and pytest. No EDA tooling is installed and none may be added:
no Yosys, ABC, Verilator, Icarus Verilog, and no third-party Verilog parser (pyverilog, hdlConvertor, …).
Verification checks the environment.
EON

cat > "$WS/README.md" <<'EON'
# synthx
A clean-room logic synthesiser. Read SPEC.md for the accepted RTL subset, the netlist rules, and how the
result is judged. `cells.v` holds the one sequential cell you may instantiate. `examples/` has three RTL
designs and, for the simplest one, a legal netlist so the output form is unambiguous.

The hidden evaluation runs 13 designs — combinational (adders, ALU, multiplexer, priority encoder, barrel
shifter, comparator, multiplier, decoder) and sequential (counter with load and synchronous reset, shift
register, FSM, CRC LFSR, PWM) — and proves each netlist equivalent to its RTL with a SAT-based checker.
EON
