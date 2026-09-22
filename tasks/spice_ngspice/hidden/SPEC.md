# spicex — specification of the circuit simulator (HSPICE / Spectre / ngspice class)

Build `spicex`, a clean-room SPICE-compatible circuit simulator. Results are compared against a reference simulator on
hidden netlists (DC operating point, DC sweep, transient).

## Command line (must exist at the workspace root)
    bash run_sim.sh <netlist.cir> <out.csv>

## Netlist subset (SPICE3/ngspice syntax; first line is a title; `*` comments; `.end` terminates; case-insensitive)
- Values with suffixes: f p n u m k meg g t (e.g. `4.7u`, `1meg`, `10k`).
- `R<name> n+ n- value`, `C<name> n+ n- value [IC=v]`, `L<name> n+ n- value [IC=i]`
- `V<name> n+ n- [DC] v` | `PULSE(v1 v2 td tr tf pw per)` | `SIN(vo va freq [td theta])` | `PWL(t1 v1 t2 v2 ...)`; `I<name>` likewise.
  Time-dependent sources take their t=0 value for .op/.dc.
- `D<name> n+ n- model` with `.model name D(IS=.. N=..)` (ideal exponential diode with emission coefficient; RS, CJO may be ignored).
- `M<name> nd ng ns nb model W=.. L=..` with `.model name NMOS|PMOS (LEVEL=1 VTO=.. KP=.. LAMBDA=.. [GAMMA=.. PHI=..])`
  (Shichman–Hodges level-1 model, cutoff/linear/saturation with channel-length modulation; body effect only if GAMMA given).
- Analyses: `.op`; `.dc <source> start stop step`; `.tran tstep tstop [tstart] [uic]`. Node `0` is ground.

## Output CSV
Header row, then values in full double precision.
- `.op`: columns `v(<node>)` for every non-ground node in order of first appearance, then `i(<Vname>)` for every voltage source
  (current flowing from n+ through the source to n-, SPICE convention: positive when current enters the + terminal), one row.
- `.dc`: first column `sweep`, then the same columns; one row per sweep point (start..stop inclusive).
- `.tran`: first column `time`, then the same columns; rows at your own time points from 0 to tstop (adaptive step allowed; the
  grader interpolates), with enough resolution to resolve the waveforms (max step <= tstep).

## Accuracy targets
DC/.op: relative error <= 0.5% (or 1 µV / 1 nA absolute). Transient: after interpolation onto the reference time grid, RMS error
<= 2% and max error <= 5% of each signal's peak-to-peak range. At least 80% of hidden netlists must pass; nonlinear (diode/MOSFET)
and stiff circuits are included, so Newton–Raphson with limiting/damping and an implicit integrator (trapezoidal or Gear) with
local truncation error control are expected.

## Rules
Python + NumPy only (no SciPy, PySpice, ngspice or other simulators; verification checks the environment). examples/ contains
three netlists with reference outputs.
