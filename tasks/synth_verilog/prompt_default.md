You are building a clean-room reimplementation of the core of a commercial logic synthesiser (Synopsys Design Compiler / Cadence Genus class). Read README.md, SPEC.md and ENVIRONMENT.md first.

Deliver `synthx` in this workspace:
- `bash run_synth.sh <design.v> <netlist.v>` reads the Verilog-2001 subset described in SPEC.md and writes a structural gate-level netlist containing nothing but wires, the gate primitives `and or not nand nor xor xnor buf`, and the `DFF` cell from `cells.v`.
- You write the whole flow yourself: lexer, parser, elaboration (parameters, vectors, part selects, concatenation and replication), then logic construction — adders and comparators from gates, multiplexer trees for `case` and `if/else`, barrel shifters for variable shift amounts, a multiplier, and flip-flop inference for `always @(posedge clk)` with synchronous reset and enable built out of gates around the plain DFF.
- Correctness is proved, not sampled: a SAT-based equivalence checker compares your netlist against the source RTL, completely for combinational designs and by temporal induction for sequential ones. One counterexample fails a design, so reason about the semantics rather than testing a few vectors — signed vs unsigned widths, truncation and extension in assignments, the exact width of intermediate results, and what a `case` without a `default` implies.
- Python standard library only (NumPy allowed). No Yosys, ABC, Verilator, Icarus, and no third-party Verilog parser.

Verify your own work before finishing: the examples in `examples/` are a starting point, but write more RTL of your own across the whole subset, and check your netlists by evaluating both the RTL and the gates yourself (an interpreter you write for this purpose is a reasonable investment).

Finish with `NOTES.md` describing the front end, the elaboration and the gate mapping, plus any part of the subset you chose not to support. Work autonomously; do not ask questions.
