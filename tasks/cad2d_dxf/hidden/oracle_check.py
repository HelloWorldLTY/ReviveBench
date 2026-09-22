"""Read an agent-written DXF with ezdxf and report closed-shape areas etc. (runs in the oracle env). Usage: oracle_check.py file.dxf -> JSON"""
import sys, json, math
import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.as_posix())
from make_drawings_lib import bulge_poly
doc = ezdxf.readfile(sys.argv[1]); msp = doc.modelspace(); out = {"entities": {}, "polys": [], "holes": []}
for e in msp:
    t = e.dxftype(); out["entities"][t] = out["entities"].get(t, 0) + 1
    if t == "LWPOLYLINE":
        pts = [(p[0], p[1], p[4]) for p in e.get_points(format="xyseb")]
        poly = (bulge_poly(pts).buffer(0)) if e.closed or len(pts) > 2 else None  # buffer(0): the same convention make_drawings.py used for the reference; a self-intersecting polygon is read as a union
        if poly is not None: (out["holes"] if e.dxf.layer.upper() == "HOLES" else out["polys"]).append({"area": abs(poly.area), "perimeter": poly.length, "centroid": list(poly.centroid.coords[0]), "layer": e.dxf.layer})
    elif t == "CIRCLE":
        c = Point(e.dxf.center.x, e.dxf.center.y).buffer(e.dxf.radius, 512); out["polys"].append({"area": c.area, "perimeter": c.length, "centroid": [e.dxf.center.x, e.dxf.center.y], "layer": e.dxf.layer})
    elif t == "ARC": out.setdefault("arcs", []).append({"center": [e.dxf.center.x, e.dxf.center.y], "radius": e.dxf.radius, "start": e.dxf.start_angle, "end": e.dxf.end_angle})
    elif t == "LINE": out.setdefault("lines", []).append([e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y])
    elif t == "TEXT": out.setdefault("texts", []).append(e.dxf.text)
print(json.dumps(out))
