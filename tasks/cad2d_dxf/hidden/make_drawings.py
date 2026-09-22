#!/usr/bin/env python3
"""Generate hidden drawings (ezdxf), commands and reference answers (shapely). Run in the industrial_oracle env."""
import json, math, pathlib, random
import ezdxf, numpy as np
from shapely.geometry import Polygon, Point, LineString
from shapely import affinity
HERE = pathlib.Path(__file__).resolve().parent; random.seed(11)
from make_drawings_lib import bulge_poly
def rand_convex(k, cx, cy, R):
    ang = sorted(random.uniform(0, 2 * math.pi) for _ in range(k)); return [(cx + R * random.uniform(0.7, 1.0) * math.cos(a), cy + R * random.uniform(0.7, 1.0) * math.sin(a), 0.0) for a in ang]
def star(cx, cy, R, r, k): return [(cx + (R if i % 2 == 0 else r) * math.cos(i * math.pi / k), cy + (R if i % 2 == 0 else r) * math.sin(i * math.pi / k), 0.0) for i in range(2 * k)]
drawings, cmds, refs = {}, [], {}
for di in range(6):
    doc = ezdxf.new("R2010"); msp = doc.modelspace()
    for ln in ("WALLS", "PARTS", "NOTES"): doc.layers.add(ln)
    shapes = []
    p1 = rand_convex(random.randint(5, 8), 50, 50, 20); shapes.append(("LWPOLYLINE", p1, "PARTS"))
    p2 = star(150, 60, 25, 12, random.randint(5, 7)); shapes.append(("LWPOLYLINE", p2, "PARTS"))
    slot = [(80, 120, 0.0), (140, 120, 1.0), (140, 140, 0.0), (80, 140, 1.0)]; shapes.append(("LWPOLYLINE", slot, "WALLS"))  # stadium with two semicircles
    b = random.uniform(0.2, 0.6); tri = [(30, 150, b), (70, 150, 0.0), (50, 185, -b)]; shapes.append(("LWPOLYLINE", tri, "PARTS"))
    circ = (110 + di * 3, 30, 12 + di); shapes.append(("CIRCLE", circ, "WALLS"))
    rect = [(40 + di, 40, 0.0), (75, 40, 0.0), (75, 70 + di, 0.0), (40 + di, 70 + di, 0.0)]; shapes.append(("LWPOLYLINE", rect, "PARTS"))  # overlaps shape 0
    for typ, g, ln in shapes:
        if typ == "LWPOLYLINE": msp.add_lwpolyline([(x, y, 0, 0, bb) for x, y, bb in g], format="xyseb", close=True, dxfattribs={"layer": ln})
        else: msp.add_circle((g[0], g[1]), g[2], dxfattribs={"layer": ln})
    msp.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"}); msp.add_line((0, 0), (0, 200), dxfattribs={"layer": "WALLS"})
    msp.add_arc((160, 160), 20, 30, 250, dxfattribs={"layer": "NOTES"}); msp.add_text(f"DRAWING {di}", dxfattribs={"layer": "NOTES", "height": 5}).set_placement((10, 190))
    name = f"d{di}"; doc.saveas(HERE / "drawings" / f"{name}.dxf")
    polys = [(bulge_poly(g) if typ == "LWPOLYLINE" else Point(g[0], g[1]).buffer(g[2], 512)).buffer(0) for typ, g, ln in shapes]
    # bbox: arc extents
    def arc_pts(cx, cy, r, a0, a1): return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in np.linspace(a0, a1, 400)]
    allpts = [q for p in polys for q in p.exterior.coords] + [(0, 0), (200, 0), (0, 200)] + arc_pts(160, 160, 20, 30, 250)
    xs, ys = [q[0] for q in allpts], [q[1] for q in allpts]
    refs[name] = {"entities": {"LWPOLYLINE": 5, "CIRCLE": 1, "LINE": 2, "ARC": 1, "TEXT": 1}, "layers": sorted(["0", "WALLS", "PARTS", "NOTES"]),
                  "bbox": [min(xs), min(ys), max(xs), max(ys)],
                  "shapes": [{"index": i, "type": typ, "layer": ln, "area": polys[i].area, "perimeter": polys[i].length, "centroid": list(polys[i].centroid.coords[0])} for i, (typ, g, ln) in enumerate(shapes)]}
    cmds.append({"name": f"{name}_measure", "cmd": {"op": "measure", "dxf": f"{name}.dxf"}, "ref": refs[name]})
    d = random.choice([3.0, -2.0, 5.0]); idx = random.choice([0, 2, 3])
    cmds.append({"name": f"{name}_offset", "cmd": {"op": "offset", "dxf": f"{name}.dxf", "index": idx, "distance": d, "out_dxf": f"{name}_offset.dxf"},
                 "ref": {"area": polys[idx].buffer(d, 512).area, "perimeter": polys[idx].buffer(d, 512).length}})
    kind = ["union", "intersection", "difference"][di % 3]; a_, b_ = 0, 5
    pa, pb = polys[a_], polys[b_]
    if not pa.intersects(pb):  # make sure they overlap: shift circle/star reference accordingly
        pb = affinity.translate(pb, 50 - pb.centroid.x + 10, 50 - pb.centroid.y + 5)
        cmds.append({"name": f"{name}_boolean", "cmd": {"op": "boolean", "kind": kind, "dxf": f"{name}.dxf", "a": a_, "b": b_, "out_dxf": f"{name}_bool.dxf"}, "ref": None, "skip": "disjoint"})
    else:
        res = getattr(pa, kind)(pb); cmds.append({"name": f"{name}_boolean", "cmd": {"op": "boolean", "kind": kind, "dxf": f"{name}.dxf", "a": a_, "b": b_, "out_dxf": f"{name}_bool.dxf"}, "ref": {"area": res.area, "regions": (0 if res.is_empty else len(getattr(res, "geoms", [res])))}})
    r = 2.0; f = polys[0].buffer(-r, 512).buffer(r, 512)
    cmds.append({"name": f"{name}_fillet", "cmd": {"op": "fillet", "dxf": f"{name}.dxf", "index": 0, "radius": r, "out_dxf": f"{name}_fillet.dxf"}, "ref": {"area": f.area, "perimeter": f.length}})
    ang, sc, tr = random.choice([30, 45, 90, 137.5]), random.choice([0.5, 2.0, 1.25]), [random.uniform(-50, 50), random.uniform(-50, 50)]
    tp = [affinity.translate(affinity.rotate(affinity.scale(p, sc, sc, origin=(0, 0)), ang, origin=(0, 0)), tr[0], tr[1]) for p in polys]
    cmds.append({"name": f"{name}_transform", "cmd": {"op": "transform", "dxf": f"{name}.dxf", "rotate_deg": ang, "scale": sc, "translate": tr, "out_dxf": f"{name}_xf.dxf"}, "ref": {"shapes": [{"area": p.area, "centroid": list(p.centroid.coords[0])} for p in tp]}})
cmds = [c for c in cmds if not c.get("skip")]
w = {"op": "write", "entities": [{"type": "LINE", "start": [1, 2], "end": [30, 40], "layer": "WALLS"}, {"type": "CIRCLE", "center": [10, 10], "radius": 7.5, "layer": "PARTS"},
     {"type": "ARC", "center": [50, 50], "radius": 10, "start_deg": 20, "end_deg": 200, "layer": "PARTS"}, {"type": "LWPOLYLINE", "points": [[0, 0, 0], [20, 0, 0.5], [20, 20, 0], [0, 20, 0]], "closed": True, "layer": "WALLS"},
     {"type": "TEXT", "insert": [5, 60], "height": 3.5, "text": "HELLO", "layer": "NOTES"}], "out_dxf": "written.dxf"}
cmds.append({"name": "write_roundtrip", "cmd": w, "ref": {"written": 5, "poly_area": bulge_poly([(0, 0, 0), (20, 0, 0.5), (20, 20, 0), (0, 20, 0)]).area}})
json.dump(cmds, open(HERE / "ref" / "commands.json", "w"), indent=1); print(len(cmds), "commands", [c["name"] for c in cmds][:8])
