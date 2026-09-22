Build `flowx`, a clean-room CFD and nonlinear-CAE solver (ANSYS Fluent / STAR-CCM+ / Abaqus class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_cfd.sh <case.json> <out.json>`: it must handle all six case kinds — steady channel flow (Poiseuille and Couette with a pressure gradient), the unsteady Taylor–Green vortex, viscous Burgers, the inviscid Burgers shock, a neo-Hookean bar under finite strain, and the lid-driven cavity — and report exactly the keys named in each case's `report` array.

It is invoked as `bash run_cfd.sh ...` with an arbitrary working directory, so it must be a shell script that resolves its own files from the script's own location.

Python + NumPy only — no SciPy, no FEM or PDE libraries; writing your own linear solvers is part of the task, and the environment is checked. Most cases are graded against closed-form analytic solutions, so a mismatch means your discretisation is wrong. Two checks carry no tolerance at all: the reported maximum divergence for the incompressible cases, and the shock case's flux balance. Validate against every example in examples/.

Work autonomously; do not ask questions.
