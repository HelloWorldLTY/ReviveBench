#!/usr/bin/env python3
"""Build the hidden model set for cad3d_brep and compute reference answers with OpenCASCADE.

Runs in envs/cad3d_oracle (OCP + trimesh + scipy). Emits, into hidden/:
    models/<name>.model.json      the CSG description handed to the candidate
    ref/<name>.json               exact mass properties, query answers, reference topology
    examples/<name>.model.json    three worked examples copied into the workspace
    examples/<name>.expected.json  ... with their answers
    manifest.json                 the model list

Reference values come from OCC's analytic kernel, never from a tessellation, with two exceptions
that are inherently mesh-level and are documented as such: the Euler characteristic and the shell
count, which are read off a very fine reference tessellation.

Query points are sampled with a safe margin off the boundary. The margin is measured against a
compound of the solid's FACES, not against the solid: the distance from an interior point to a
solid is zero, so measuring against the solid would call every interior point a boundary point.

usage: make_models.py [--out <hidden dir>]
"""
import argparse
import json
import math
import pathlib
import random
import tempfile

import trimesh
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon,
                                BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform)
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import (BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder,
                             BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeSphere,
                             BRepPrimAPI_MakeTorus)
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.StlAPI import StlAPI_Writer
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound

# ---------------------------------------------------------------- CSG evaluation


def build(node):
    """Evaluate a CSG node from the spec into an OCC shape."""
    op = node["op"]
    if op == "box":
        return BRepPrimAPI_MakeBox(float(node["dx"]), float(node["dy"]), float(node["dz"])).Shape()
    if op == "cylinder":
        return BRepPrimAPI_MakeCylinder(float(node["r"]), float(node["h"])).Shape()
    if op == "sphere":
        return BRepPrimAPI_MakeSphere(float(node["r"])).Shape()
    if op == "cone":
        return BRepPrimAPI_MakeCone(float(node["r1"]), float(node["r2"]), float(node["h"])).Shape()
    if op == "torus":
        return BRepPrimAPI_MakeTorus(float(node["R"]), float(node["r"])).Shape()
    if op == "extrude":
        mp = BRepBuilderAPI_MakePolygon()
        for x, y in node["profile"]:
            mp.Add(gp_Pnt(float(x), float(y), 0.0))
        mp.Close()
        face = BRepBuilderAPI_MakeFace(mp.Wire()).Face()
        return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, float(node["h"]))).Shape()
    if op == "revolve":
        mp = BRepBuilderAPI_MakePolygon()
        for x, z in node["profile"]:
            mp.Add(gp_Pnt(float(x), 0.0, float(z)))
        mp.Close()
        face = BRepBuilderAPI_MakeFace(mp.Wire()).Face()
        ax = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        return BRepPrimAPI_MakeRevol(face, ax, math.radians(float(node["angle"]))).Shape()
    if op == "translate":
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(*[float(v) for v in node["by"]]))
        return BRepBuilderAPI_Transform(build(node["shape"]), t, True).Shape()
    if op == "rotate":
        t = gp_Trsf()
        t.SetRotation(gp_Ax1(gp_Pnt(*[float(v) for v in node["origin"]]),
                             gp_Dir(*[float(v) for v in node["axis"]])),
                      math.radians(float(node["deg"])))
        return BRepBuilderAPI_Transform(build(node["shape"]), t, True).Shape()
    if op in ("union", "intersect", "difference"):
        shapes = [build(s) for s in node["shapes"]]
        acc = shapes[0]
        for s in shapes[1:]:
            api = {"union": BRepAlgoAPI_Fuse, "intersect": BRepAlgoAPI_Common,
                   "difference": BRepAlgoAPI_Cut}[op](acc, s)
            acc = api.Shape()
        return acc
    raise SystemExit(f"make_models: unknown op {op!r}")


# ---------------------------------------------------------------- measurement


def props(shape):
    from OCP.GProp import GProp_GProps
    v = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, v)
    a = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, a)
    c = v.CentreOfMass()
    return v.Mass(), a.Mass(), [c.X(), c.Y(), c.Z()]


def bbox(shape):
    b = Bnd_Box()
    b.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, b)
    lo, hi = b.CornerMin(), b.CornerMax()
    return [lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()]


def faces_compound(shape):
    """A compound of the shape's faces — the *boundary*, for distance queries."""
    b = BRep_Builder()
    c = TopoDS_Compound()
    b.MakeCompound(c)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        b.Add(c, ex.Current())
        ex.Next()
    return c


def classify(shape, pt):
    c = BRepClass3d_SolidClassifier(shape)
    c.Perform(gp_Pnt(*pt), 1e-7)
    return c.State() == TopAbs_IN


def dist_to_boundary(boundary, pt):
    v = BRepBuilderAPI_MakeVertex(gp_Pnt(*pt)).Vertex()
    d = BRepExtrema_DistShapeShape(boundary, v)
    d.Perform()
    return d.Value()


def clean_mesh(m, area_eps=1e-12):
    """Drop zero-area facets, then re-merge.

    OCC's STL export leaves stray degenerate triangles behind. On a cavity model those two
    single-triangle fragments make trimesh's whole-mesh `is_watertight` False even though both
    real shells are closed and the signed volume is right to 0.01%. Grading on the raw flag would
    have failed every candidate that models an enclosed cavity correctly.
    """
    m = m.copy()
    keep = m.area_faces > area_eps
    if not keep.all():
        m.update_faces(keep)
    m.remove_unreferenced_vertices()
    m.merge_vertices()
    return m


def topology(m):
    """(every shell closed?, total Euler characteristic, shell count) for a cleaned mesh."""
    parts = [p for p in m.split(only_watertight=False) if len(p.faces) > 3]
    return (bool(all(p.is_watertight for p in parts)),
            int(sum(p.euler_number for p in parts)),
            len(parts))


def ref_mesh(shape, lin=0.004):
    """Very fine reference tessellation, only for topology (Euler characteristic, shells)."""
    BRepMesh_IncrementalMesh(shape, lin, False, 0.1, True)
    p = tempfile.mktemp(suffix=".stl")
    StlAPI_Writer().Write(shape, p)
    return clean_mesh(trimesh.load(p, force="mesh", process=True))


def sample_queries(shape, bb, n, rng, margin_frac=0.02):
    """Points strictly inside or outside, each at least `margin` from the boundary.

    A point closer than the margin is discarded rather than resolved: the spec promises the
    candidate that no query is near a face, so an ambiguous point would be a defect in the
    asset, not a hard case for the candidate.
    """
    boundary = faces_compound(shape)
    diag = math.dist(bb[:3], bb[3:])
    margin = margin_frac * diag
    pad = 0.15 * diag
    lo = [bb[0] - pad, bb[1] - pad, bb[2] - pad]
    hi = [bb[3] + pad, bb[4] + pad, bb[5] + pad]
    pts, ans, tries = [], [], 0
    want_in = n // 2
    n_in = 0
    while len(pts) < n and tries < n * 400:
        tries += 1
        p = [rng.uniform(lo[i], hi[i]) for i in range(3)]
        if dist_to_boundary(boundary, p) < margin:
            continue
        inside = classify(shape, p)
        # keep the set balanced so a kernel that answers a constant cannot score well
        if inside and n_in >= want_in:
            continue
        if not inside and (len(pts) - n_in) >= n - want_in:
            continue
        pts.append([round(v, 6) for v in p])
        ans.append(bool(inside))
        n_in += bool(inside)
    return pts, ans


# ---------------------------------------------------------------- the model set

def models():
    """13 models: primitives, transforms, sweeps, then booleans and the degenerate cases."""
    M = {}
    M["m01_box"] = {"op": "box", "dx": 20, "dy": 12, "dz": 8}
    M["m02_cyl"] = {"op": "cylinder", "r": 5, "h": 14}
    M["m03_sphere"] = {"op": "sphere", "r": 7}
    M["m04_cone"] = {"op": "cone", "r1": 6, "r2": 2, "h": 11}
    M["m05_torus"] = {"op": "torus", "R": 9, "r": 3}
    # L-shaped prism: tests extrusion of a non-convex profile
    M["m06_extrude_L"] = {"op": "extrude", "h": 6,
                          "profile": [[0, 0], [14, 0], [14, 5], [5, 5], [5, 12], [0, 12]]}
    # revolved trapezoid -> a truncated conical ring
    M["m07_revolve"] = {"op": "revolve", "angle": 360,
                        "profile": [[4, 0], [9, 0], [7, 6], [4, 6]]}
    # rotated + translated box: transforms must not change volume
    M["m08_rot_box"] = {"op": "rotate", "axis": [0, 0, 1], "origin": [0, 0, 0], "deg": 37,
                        "shape": {"op": "translate", "by": [3, 4, 1],
                                  "shape": {"op": "box", "dx": 10, "dy": 6, "dz": 4}}}
    # union of two overlapping cylinders (a cross)
    M["m09_union_cross"] = {"op": "union", "shapes": [
        {"op": "cylinder", "r": 3, "h": 20},
        {"op": "translate", "by": [0, 0, 10],
         "shape": {"op": "rotate", "axis": [0, 1, 0], "origin": [0, 0, 0], "deg": 90,
                   "shape": {"op": "cylinder", "r": 3, "h": 20}}}]}
    # intersection of box and sphere -> spherical cap solid
    M["m10_intersect"] = {"op": "intersect", "shapes": [
        {"op": "translate", "by": [-6, -6, 0], "shape": {"op": "box", "dx": 12, "dy": 12, "dz": 6}},
        {"op": "sphere", "r": 7}]}
    # through-hole: genus 1, and the cylinder pokes out both faces (coplanar-free but open)
    M["m11_through_hole"] = {"op": "difference", "shapes": [
        {"op": "box", "dx": 16, "dy": 16, "dz": 6},
        {"op": "translate", "by": [8, 8, -2], "shape": {"op": "cylinder", "r": 4, "h": 10}}]}
    # fully enclosed cavity: two shells, Euler 4 — the topology check's discriminator
    M["m12_cavity"] = {"op": "difference", "shapes": [
        {"op": "box", "dx": 12, "dy": 12, "dz": 12},
        {"op": "translate", "by": [6, 6, 6], "shape": {"op": "sphere", "r": 3}}]}
    # subtrahend exactly flush with a face (coplanar boolean) and a second cut that empties nothing
    M["m13_coplanar"] = {"op": "difference", "shapes": [
        {"op": "box", "dx": 10, "dy": 10, "dz": 10},
        {"op": "translate", "by": [2, 2, 5], "shape": {"op": "box", "dx": 6, "dy": 6, "dz": 5}}]}
    return M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    ap.add_argument("--queries", type=int, default=40)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("models", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260910)

    manifest = []
    for name, tree in models().items():
        shape = build(tree)
        vol, area, cen = props(shape)
        bb = bbox(shape)
        pts, ans = sample_queries(shape, bb, a.queries, rng)
        mesh = ref_mesh(shape)
        closed, euler, shells = topology(mesh)
        if not closed:
            raise SystemExit(f"make_models: reference mesh for {name} is not closed — fix the "
                             f"asset before grading anyone against it")
        model = {"name": name, "stl_out": f"{name}.stl", "tree": tree, "queries": pts}
        ref = {"name": name, "volume": vol, "area": area, "centroid": cen, "bbox": bb,
               "inside": ans, "euler": euler, "shells": shells,
               "mesh_volume": float(mesh.volume), "closed": closed}
        (out / "models" / f"{name}.model.json").write_text(json.dumps(model, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(ref, indent=1))
        manifest.append(name)
        print("%-18s vol=%12.5f area=%12.5f euler=%3d shells=%d closed=%s in=%d/%d" % (
            name, vol, area, ref["euler"], ref["shells"], ref["closed"],
            sum(ans), len(ans)))

    # three worked examples for the workspace: one primitive, one sweep, one boolean
    for name in ("m02_cyl", "m06_extrude_L", "m11_through_hole"):
        model = json.loads((out / "models" / f"{name}.model.json").read_text())
        ref = json.loads((out / "ref" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.model.json").write_text(json.dumps(model, indent=1))
        (out / "examples" / f"{name}.expected.json").write_text(json.dumps(
            {k: ref[k] for k in ("volume", "area", "centroid", "bbox", "inside")}, indent=1))

    (out / "manifest.json").write_text(json.dumps({"models": manifest}, indent=1))
    print(f"\n{len(manifest)} models written to {out}")


if __name__ == "__main__":
    main()
