# femx — specification of the linear finite element solver (Nastran SOL101/103, ABAQUS/CalculiX class)

Build `femx`: a clean-room linear-static and modal finite element solver for 2D continuum problems, reading the
ABAQUS/CalculiX input-deck subset below.

## Command line (must exist at the workspace root)
    bash run_fem.sh <model.inp> <out.json>

## Input deck subset (keywords case-insensitive; `**` comments; free-format comma-separated data lines)
- `*NODE` — `id, x, y, z` (z ignored).
- `*ELEMENT, TYPE=<CPS4|CPS8|CPE4|CPE8>, ELSET=<name>` — `id, n1, ..., n4|n8` (ABAQUS/CalculiX node ordering: corners
  counter-clockwise, then mid-side nodes 5..8 between 1-2, 2-3, 3-4, 4-1). CPS = plane stress, CPE = plane strain;
  4-node bilinear and 8-node serendipity isoparametric elements, full Gauss integration (2x2 for 4-node, 3x3 for 8-node).
- `*NSET, NSET=<name>` / `*ELSET, ELSET=<name>` — id lists (may span lines).
- `*MATERIAL, NAME=..` with `*ELASTIC` (`E, nu`) and `*DENSITY` (`rho`); `*SOLID SECTION, ELSET=.., MATERIAL=..` followed by an
  optional thickness line (plane stress; default 1.0).
- `*BOUNDARY` — `nset_or_node, first_dof[, last_dof][, value]` (dofs 1 = ux, 2 = uy; value 0 if omitted).
- `*STEP` ... `*END STEP` with either `*STATIC` and `*CLOAD` (`node, dof, value` nodal forces, accumulative) or
  `*FREQUENCY` followed by the number of eigenfrequencies requested (lowest ones, with the consistent mass matrix).
  Output request cards (`*NODE FILE`, `*EL FILE`, `*NODE PRINT`) may be ignored.

## Output JSON
- static: {"analysis":"static","displacements":{"<node>":[ux,uy],...},"stresses":{"<node>":[sxx,syy,sxy],...}}
  Nodal stresses = extrapolation of Gauss-point stresses to the element nodes, averaged over the elements sharing the node
  (the standard CalculiX/ABAQUS nodal averaging).
- modal: {"analysis":"modal","frequencies_hz":[f1, f2, ...]} in ascending order (the requested count).

## Grading
Hidden benchmark models (cantilever beam, thick cylinder under pressure, plate with a hole, cantilever modal analysis; up to
~4000 nodes). Nodal displacements are compared with a reference solver (max relative error over all nodes with |u| above 1% of
the maximum <= 1%); probe values are compared with analytical solutions (Timoshenko tip deflection, Lamé radial displacement,
Kirsch stress concentration 3σ within 6%); eigenfrequencies within 1% of the reference solver. All models must pass.

## Rules
Python + NumPy only (dense or your own sparse assembly; NumPy's linear algebra is fine). No SciPy, no existing FE libraries
(verification checks the environment). examples/ contains one static and one modal model with reference outputs.
