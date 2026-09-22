# solidx — a 3D solid modelling kernel

You are building the geometry core of a 3D CAD system (the class of kernel that Parasolid and ACIS
occupy). It reads a CSG model description, computes the solid's mass properties, answers
point-membership queries, and exports the solid as a triangle mesh.

## 1. Entry point

    bash run_solid.sh <model.json> <out.json>

`run_solid.sh` must sit at the workspace root and exit non-zero on any error. Use a shebang and an
explicit interpreter; do not assume an interpreter name that only exists inside one environment.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location (for example with
`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`), never relative to `$PWD`. Note that `stl_out`
below is the one path that *is* relative to the working directory you are invoked in.

## 2. Input: model.json

```json
{
  "name": "m07",
  "stl_out": "m07.stl",
  "tree": { ...node... },
  "queries": [[1.0, 2.0, 3.0], [4.0, 0.5, 1.0]]
}
```

`tree` is a CSG node. Every node is one of:

| node | fields | meaning |
|---|---|---|
| `box` | `dx, dy, dz` | corner at origin, extending along +X, +Y, +Z |
| `cylinder` | `r, h` | axis = +Z, base circle centred at the origin |
| `sphere` | `r` | centred at the origin |
| `cone` | `r1, r2, h` | axis = +Z, base radius `r1` at z=0, top radius `r2` at z=h (`r2` may be 0) |
| `torus` | `R, r` | centred at the origin, axis = +Z, `R` = ring radius, `r` = tube radius |
| `extrude` | `profile, h` | closed simple polygon `[[x,y],…]` in the z=0 plane, swept along +Z by `h` |
| `revolve` | `profile, angle` | closed simple polygon `[[x,z],…]` in the y=0 half-plane (`x ≥ 0`), revolved about the Z axis by `angle` degrees |
| `translate` | `by:[dx,dy,dz], shape` | |
| `rotate` | `axis:[x,y,z], origin:[x,y,z], deg, shape` | right-handed rotation about the directed axis through `origin` |
| `union` | `shapes:[…]` | regularised union |
| `intersect` | `shapes:[…]` | regularised intersection |
| `difference` | `shapes:[…]` | first shape minus every later shape, regularised |

Booleans are **regularised**: the result is the closure of the interior of the set-theoretic result.
Dangling faces, edges and points that bound no volume are not part of the answer. A difference that
removes everything yields the empty solid.

## 3. Output: out.json

```json
{
  "volume": 123.456789,
  "area": 246.8,
  "centroid": [1.0, 2.0, 3.0],
  "bbox": [xmin, ymin, zmin, xmax, ymax, zmax],
  "inside": [true, false]
}
```

* `volume` — enclosed volume. `area` — total boundary area, including the walls of internal cavities.
* `centroid` — centre of volume (not the centroid of the vertices, and not the bbox centre).
* `bbox` — axis-aligned bounds of the solid itself. For curved faces this is the true extent of the
  surface, not the extent of however finely you tessellated it.
* `inside` — one entry per entry of `queries`, `true` when the point is strictly inside the solid.
  Query points are never placed close to a boundary, so there is no ambiguous case to resolve.
* For the empty solid: `volume` 0, `area` 0, `centroid` `null`, `bbox` `null`, every query `false`.

## 4. Output: the STL

Write a binary or ASCII STL to the path named by `stl_out`, relative to the working directory.

The mesh must be **closed**, and the check is applied per shell, not to the file as a whole: after
degenerate (zero-area) facets are discarded, every connected shell must have each edge shared by
exactly two triangles and a consistent winding. Outward-facing shells wind outward; the shell
bounding an internal cavity winds inward, so that the signed volume of the whole mesh equals the
volume of the solid.

The mesh must also carry the same topology as the solid, checked by the total Euler characteristic
summed over shells and by the number of shells. A plain solid is one shell with χ = 2. A solid with
one through-hole is one shell with χ = 0 (genus 1). A solid with a fully enclosed cavity is **two**
shells with χ = 4 in total. A mesh that merely looks right will not pass.

## 5. Accuracy

Tessellate as finely as you need. The reference values come from an exact analytic kernel, so the
error budget is yours to spend on mesh density:

* volume — relative error ≤ 0.5%
* area — relative error ≤ 1.5%
* centroid, bbox — absolute error ≤ 0.5% of the model's bounding-box diagonal
* `inside` — must be exactly right for every query point, on every model. This is the check that
  actually tests whether your booleans are correct, and it admits no tolerance.

## 6. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed.
  No OpenCASCADE / OCP / cadquery / trimesh / manifold3d / open3d / pymesh / numpy-stl / scipy /
  shapely / gmsh / pyvista / VTK. The environment is checked.
* Implementing the kernel on tessellated meshes is allowed and is the expected route: convert each
  primitive to a triangle mesh yourself, then do mesh–mesh CSG. Working directly with exact surfaces
  is also allowed. What is graded is the answer, not the representation.
* Degenerate and near-degenerate configurations appear in the hidden set: coplanar faces meeting in a
  boolean, a subtrahend exactly touching a face, nested cavities, and a shape whose difference is
  empty. Robustness to these is part of the task.
