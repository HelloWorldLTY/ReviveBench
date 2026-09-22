Build `solidx`, a clean-room 3D solid modelling kernel (Parasolid / ACIS class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_solid.sh <model.json> <out.json>`: it must implement every CSG node type in the spec (primitives, transforms, extrusion, revolution, and regularised union / intersection / difference), write the solid's volume, area, centroid, bounding box and point-membership answers to `out.json`, and export a watertight STL to the path the model names.

Python + NumPy only — no geometry libraries, and the environment is checked. Validate against every example in examples/, which pairs a model with its expected answer.

Work autonomously; do not ask questions.
