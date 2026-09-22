You are building a clean-room reimplementation of the geometry core of a 2D CAD system (AutoCAD class). Read README.md, SPEC.md and ENVIRONMENT.md first.

Deliver `cadx` in this workspace:
- `bash run_cad.sh <command.json> <out.json>` implements every operation in SPEC.md: a DXF R2010 reader/writer (group codes, LINE/CIRCLE/ARC/LWPOLYLINE with bulges/TEXT, layers, handles) and exact geometry for polylines with circular-arc segments: area, perimeter, centroid, bounding box (true arc extents), round-corner offsetting (inward and outward), fillets, polygon booleans (union/intersection/difference with holes), and affine transforms that keep arcs as arcs.
- Python + NumPy only. DXF files you write must load in standard DXF readers (respect section structure, required group codes, handles, and the closed flag / bulge conventions).
- Validate against every example in examples/ (command + expected answer) and write your own tests, including bulge-arc polygons, inward offsets that split, and booleans with holes.

Finish with `NOTES.md` describing the algorithms. Work autonomously; do not ask questions.
