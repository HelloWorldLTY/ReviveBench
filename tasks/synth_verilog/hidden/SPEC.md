# synthx — specification of the RTL synthesis engine (Synopsys DC / Cadence Genus class)

Build `synthx`: a logic synthesiser. It reads Verilog-2001 RTL and writes a **structural gate-level netlist**
built only from primitive gates and flip-flops. Correctness is proved formally, not sampled.

## Command line (must exist at the workspace root)

    bash run_synth.sh <design.v> <netlist.v>

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location (for example with
`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`), never relative to `$PWD`. A launcher that says
`python3 synthx.py` will not find its own engine.

## Input: the RTL subset you must accept

One module per file. Inside it:

- Ports with direction and optional vector range: `input clk`, `input [7:0] a`, `output reg [3:0] y`.
- `wire` / `reg` declarations, scalar or vectored; `parameter` with constant expressions.
- Continuous assignment: `assign lhs = expr;`
- Combinational blocks: `always @(*) begin ... end` with blocking assignment (`=`), `if/else`, `case`/`default`.
- Sequential blocks: `always @(posedge clk) begin ... end` with non-blocking assignment (`<=`), `if/else`, `case`.
  Reset is **synchronous** — it appears as an ordinary `if (rst)` inside the clocked block, and you must
  synthesise it from logic; there is no async-reset cell.
- Expressions: `& | ^ ~` (bitwise), `&& || !` (logical), `== != < <= > >=`, `+ - *`, `<< >>` (including
  variable shift amounts), the conditional `? :`, concatenation `{a, b}`, replication `{n{a}}`,
  bit select `a[3]` and part select `a[7:4]`.
- Literals: `8'd12`, `4'b1010`, `8'hFF`, plain decimal.

## Output: what the netlist may contain

- The **same module name** as the input, with the **same port names, directions and widths**.
- `wire` declarations.
- Instantiations of the Verilog gate primitives **`and or not nand nor xor xnor buf`** only, in the standard
  form `and u1 (out, in1, in2);` (multi-input forms are allowed).
- Instantiations of the flip-flop cell **`DFF`** defined in `cells.v` (provided in the workspace):
  `DFF u_ff (.Q(q), .D(d), .CLK(clk));` — positive edge, no reset, no enable. Anything else you need
  (load, enable, synchronous reset, count) must be built out of gates around it.
- `assign` **only** for direct aliasing (`assign y = w;`) or a constant (`assign y = 1'b0;`).

Not allowed anywhere in the netlist: `always`, `initial`, `case`, `if`, `for`, `function`, arithmetic or
logic operators inside expressions. If it survives in the netlist, it was not synthesised.

## How your work is graded

1. **Netlist legality** — the output is parsed and rejected if it contains anything outside the list above.
2. **Formal equivalence** — a SAT-based equivalence checker proves your netlist equivalent to the source RTL.
   Combinational designs get a complete proof over all input assignments; sequential designs get temporal
   induction, falling back to a bounded proof over many cycles. A single counterexample fails the design.
3. **Simulation differential** — both designs are simulated side by side on random stimulus as a backstop.
4. **Area** — your cell count is compared with a production synthesiser's. Reported, never pass/fail:
   a correct large netlist beats a small wrong one.

The hidden design set covers combinational logic (adders, ALU, multiplexers, priority encoder, barrel shifter,
comparator, multiplier) and sequential logic (counters with load and synchronous reset, shift registers, an
FSM, an LFSR-based CRC, a PWM generator). Most designs must pass.

## Rules

Pure Python standard library (NumPy allowed). **No existing synthesis or EDA tool** — no Yosys, ABC, Verilator,
Icarus, and no third-party Verilog parser (pyverilog, hdlConvertor, …). You write the lexer, the parser, the
elaborator and the logic construction yourself.

Write `NOTES.md`: how the front end, elaboration and gate mapping work, what optimisations you apply, and any
part of the subset you chose not to support.
