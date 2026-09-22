# flowx — a CFD and nonlinear-CAE solver

You are building the solver core of a computational-continuum-mechanics package, the class of tool
that ANSYS Fluent, STAR-CCM+ and Abaqus/Explicit occupy: incompressible flow on a structured grid,
one-dimensional nonlinear transport including a shock, and a solid under finite strain.

Every case here has a closed-form solution. An earlier draft also included the lid-driven cavity
graded against the Ghia et al. (1982) table; it was removed because I could not demonstrate that
the stated tolerance was reachable, and shipping a threshold one has not verified is how a
benchmark fails correct work.

This task is graded differently from the rest of the suite. Wherever the physics has a **closed-form
solution**, that is the reference — not an implementation. There is no reference solver to disagree
with, so a mismatch means your discretisation is wrong, not that someone's code and yours differ.

## 1. Entry point

    bash run_cfd.sh <case.json> <out.json>

Must sit at the workspace root, exit non-zero on error, and use an explicit interpreter in the
shebang. It is invoked as `bash run_cfd.sh ...`, so the file must be a **shell script**, not a
Python file with a `.sh` name.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location (for example with
`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`), never relative to `$PWD`.

## 2. Cases

Each case file names a `kind` and its parameters. Five kinds:

### `poiseuille` — steady plane channel flow
Solve steady incompressible Navier–Stokes between plates at `y = 0` and `y = H`, driven by a
constant pressure gradient `dpdx < 0`, no-slip at both walls.

Exact solution: `u(y) = -dpdx/(2*mu) * y * (H - y)`, `v = 0`.

Report `u` at the sample heights given in `probe_y`, the centreline velocity, and the volumetric
flow rate `Q = -dpdx*H^3/(12*mu)`.

### `couette_pg` — Couette flow with a pressure gradient
Top wall moves at `U`, bottom wall fixed, with pressure gradient `dpdx`.

Exact: `u(y) = U*y/H - dpdx/(2*mu) * y * (H - y)`.

### `taylor_green` — unsteady decaying vortex (2-D, periodic)
On `[0, 2π]²` with `u = sin(x)cos(y)e^{-2νt}`, `v = -cos(x)sin(y)e^{-2νt}`, an exact solution of
the unsteady incompressible Navier–Stokes equations. Integrate to `t_end` and report the velocity
at the probe points, plus the kinetic energy.

`kinetic_energy` is the **domain mean** of `(u²+v²)/2`, which is `0.25·e^{-4νt}`. Reporting the
domain *integral* instead — larger by the box area `(2π)² ≈ 39.478` — is also accepted, because the
two conventions are distinguishable by exactly that factor and an earlier draft of this spec failed
to say which was meant. Either is graded against its own exact value at the same tolerance.

### `burgers_viscous` — 1-D viscous Burgers
`u_t + u·u_x = ν·u_xx` on `[0, L]` with the initial condition and boundary conditions given.
For the travelling-wave case the exact solution is
`u(x,t) = (u_l + u_r)/2 - (u_l - u_r)/2 · tanh((x - x0 - s·t)·(u_l - u_r)/(4ν))`,
with `s = (u_l+u_r)/2` and `x0` the initial centre of the profile, given in the case.

### `burgers_shock` — inviscid Burgers, Riemann problem
`u_t + (u²/2)_x = 0` with a step initial condition `u_l > u_r`. The exact weak solution is a shock
travelling at the Rankine–Hugoniot speed `s = (u_l + u_r)/2`. Report the shock position at `t_end`,
the states either side, and `∫u dx` over the domain.

Note that on a bounded domain this integral is **not** constant — inflow at the left exceeds outflow
at the right. The flux form gives the exact balance

    d/dt ∫u dx = u_l²/2 − u_r²/2,   hence   ∫u dx (t) = u_l·x_s(t) + u_r·(L − x_s(t))

with `x_s(t) = x0 + s·t`. A scheme written in flux form reproduces this identity to round-off at any
resolution; a non-conservative scheme does not. That is what is being tested.

### `hyperelastic_bar` — finite-strain uniaxial extension
An incompressible neo-Hookean bar, shear modulus `mu`, stretched to `lambda`. The exact nominal
(first Piola–Kirchhoff) stress is `P = mu*(lambda - 1/lambda²)` and the Cauchy stress is
`sigma = mu*(lambda² - 1/lambda)`. Report both, plus the strain energy density
`W = mu/2*(lambda² + 2/lambda - 3)`.

## 3. Input and output

```json
{"name": "c03", "kind": "poiseuille",
 "params": {"H": 1.0, "mu": 0.1, "dpdx": -2.0, "ny": 129},
 "probe_y": [0.1, 0.25, 0.5, 0.75, 0.9]}
```

```json
{"name": "c03",
 "fields": {"u_at_probe_y": [0.09, 0.1875, 0.25, 0.1875, 0.09]},
 "scalars": {"u_center": 0.25, "Q": 0.16666667},
 "grid": {"ny": 129}}
```

Report floats. Every case's required keys are listed in the case file's `report` array; a missing
key is a failed case.

Probe coordinates arrive under a key named for the case's geometry. The list below is fixed and
exhaustive — read the names from it, do not infer them from the one worked example above:

| kind | probe input key | probe output field(s) |
|---|---|---|
| `poiseuille`, `couette_pg` | `probe_y` — list of `y` | `u_at_probe_y` |
| `burgers_viscous`, `burgers_shock` | `probe_x` — list of `x` | `u_at_probe_x` |
| `taylor_green` | `probe_xy` — list of `[x, y]` pairs | `u_at_probe`, `v_at_probe` |
| `hyperelastic_bar` | none | none |

The 2-D case deliberately breaks the 1-D pattern: its input key is `probe_xy`, and its two output
keys carry no coordinate suffix.

## 4. Accuracy

Analytic cases are graded on **relative L2 error** against the closed form:

| case | tolerance |
|---|---|
| `poiseuille`, `couette_pg` | 1e-6 — these are exactly representable by a second-order scheme |
| `hyperelastic_bar` | 1e-9 — algebraic, no discretisation at all |
| `taylor_green` | 2e-3 on velocity, 2e-3 on kinetic energy |
| `burgers_viscous` | 5e-3 |
| `burgers_shock` | shock position within one cell width; `∫u dx` within 1e-8 of the flux-balance value (§2) |

Two checks carry **no tolerance at all**, because they are exact statements rather than
approximations:

* **Flux balance**: for `burgers_shock`, the reported `∫u dx` must equal the exact
  `u_l·x_s + u_r·(L − x_s)` to 1e-8. This is the discrete conservation statement, and a scheme in
  flux form satisfies it to round-off independently of grid resolution, so a violation proves the
  scheme is not conservative. (It is a *balance*, not a constant — see the note in §2.)
* **Incompressibility**: for `taylor_green`, the reported maximum absolute divergence
  `max|∇·u|` must be below 1e-8. A projection/pressure step that actually enforces the constraint
  achieves this to round-off; one that does not, does not.

## 5. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed. In
  particular no `scipy`, `fenics`, `firedrake`, `fipy`, `sympy`, `petsc4py`, `pyamg`, `numba`.
  Writing your own linear solvers (Thomas algorithm, conjugate gradient, multigrid) is the task.
* Grid resolutions are given in the case; do not silently change them. The tolerances above are
  reachable at the stated resolutions with a correct second-order scheme — if you need a finer grid
  than the case specifies, your scheme is the problem.
* The hidden set includes a Poiseuille case whose grid is deliberately coarse (`ny = 9`) to check
  that your scheme is genuinely second-order rather than tuned, a Taylor–Green case integrated far
  enough that a first-order-in-time scheme drifts out of tolerance, and a shock case where a
  non-conservative scheme lands the shock in the wrong place.
