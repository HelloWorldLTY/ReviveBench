# plcx — specification of the IEC 61131-3 Structured Text runtime (TIA Portal / Studio 5000 class)

Build `plcx`: a compiler/interpreter for an IEC 61131-3 Structured Text (ST) subset plus a deterministic cyclic PLC runtime.

## Command line (must exist at the workspace root)
    bash run_plc.sh <program.st> <stimulus.csv> <trace.csv> <cycle_ms>

## Execution model
- One PROGRAM per file (FUNCTION_BLOCK and FUNCTION definitions may precede it). All variables are initialised to their
  declared initial value or the IEC default (FALSE, 0, 0.0, T#0s) before the first scan.
- The stimulus CSV has a header naming the PROGRAM's VAR_INPUT variables and one row per scan. Scan k (k = 0,1,2,...):
  1) inputs are sampled from row k; 2) the program body executes once; 3) all VAR_OUTPUT variables are written as row k of the
  trace CSV (header = output names in declaration order). The runtime clock at scan k is t = k * cycle_ms (timers use this
  clock; there is no wall-clock time). The run ends after the last stimulus row.
- Values in CSVs: BOOL as 0/1; INT/DINT as integers; REAL as decimal floats (repr precision); TIME as integer milliseconds.

## Language subset
- Types: BOOL, INT (16-bit), DINT (32-bit), REAL, TIME. Literals: TRUE/FALSE, integers, reals (1.5, 2.0E3), TIME
  (T#500ms, T#1s, T#1m30s, T#2s500ms). Integer overflow wraps (two's complement); INT/DINT division truncates toward zero.
- Declarations: VAR_INPUT / VAR_OUTPUT / VAR ... END_VAR with `name : TYPE [:= init];`, FB instances `t1 : TON;`.
- Statements: `x := expr;`, IF/ELSIF/ELSE/END_IF, CASE expr OF value: ... value1, value2: ... ELSE ... END_CASE,
  FOR i := a TO b [BY s] DO ... END_FOR, WHILE ... DO ... END_WHILE, REPEAT ... UNTIL ... END_REPEAT, EXIT,
  FB invocation `inst(IN := expr, PT := expr);` then outputs read as `inst.Q`, `inst.ET`.
- Expressions: + - * / MOD, unary -, comparisons = <> < <= > >=, NOT AND OR XOR (with & as AND), parentheses;
  standard precedence; mixed INT/REAL arithmetic promotes to REAL; functions ABS, MIN, MAX, LIMIT(mn, in, mx), SEL(g, a, b),
  INT_TO_REAL, REAL_TO_INT (round to nearest), TIME_TO_DINT (ms), DINT_TO_TIME.
- Standard function blocks with IEC 61131-3 semantics evaluated against the runtime clock:
  TON(IN, PT) -> Q, ET; TOF(IN, PT) -> Q, ET; TP(IN, PT) -> Q, ET; CTU(CU, R, PV) -> Q, CV (rising edge of CU);
  CTD(CD, LD, PV) -> Q, CV; R_TRIG(CLK) -> Q; F_TRIG(CLK) -> Q; SR(S1, R) -> Q1 (set dominant); RS(S, R1) -> Q1 (reset dominant).
  Timer ET saturates at PT; TON.Q becomes TRUE on the first scan where t - t_start >= PT.
- User FUNCTION_BLOCKs with VAR_INPUT/VAR_OUTPUT/VAR and nested standard FB instances; user FUNCTIONs returning a value.

## Grading
Hidden programs with stimulus files; traces must match the reference exactly for BOOL/INT/DINT/TIME and to 1e-6 relative for
REAL. At least 80% of programs must match. examples/ holds three programs with stimulus and reference trace.

## Rules
Python only (standard library; NumPy allowed). Do not use existing IEC 61131-3 toolchains (MatIEC, OpenPLC, etc.).
