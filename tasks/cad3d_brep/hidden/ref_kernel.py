#!/usr/bin/env python3
"""Reference solid kernel, used ONLY to calibrate the hidden verifier.

It must score full marks. If it does not, the verifier or the assets are wrong, not the candidate.
Deliberately answers through the same OCC path the references came from, except that the STL is a
*coarser* tessellation than the reference one — a candidate is allowed to tessellate differently,
so calibrating with an identical mesh would prove nothing about the tolerances.

usage: ref_kernel.py <model.json> <out.json>
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_models import bbox, build, classify, props  # noqa: E402

from OCP.BRepMesh import BRepMesh_IncrementalMesh  # noqa: E402
from OCP.StlAPI import StlAPI_Writer  # noqa: E402


def main():
    model = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out_path = pathlib.Path(sys.argv[2])
    shape = build(model["tree"])

    volume, area, centroid = props(shape)
    answer = {"volume": volume, "area": area, "centroid": centroid, "bbox": bbox(shape),
              "inside": [bool(classify(shape, p)) for p in model.get("queries", [])]}

    # coarser than the reference tessellation on purpose: exercises the tolerances
    stl = pathlib.Path.cwd() / model["stl_out"]
    BRepMesh_IncrementalMesh(shape, 0.02, False, 0.3, True)
    StlAPI_Writer().Write(shape, str(stl))

    out_path.write_text(json.dumps(answer, indent=1))


if __name__ == "__main__":
    main()
