#!/usr/bin/env python3
"""Independent geometric checker for a designed part (runs in the industrial_oracle env).

It reads the DXF the design agent produced and evaluates a constraint list that the agent
never sees, using ezdxf + shapely. The agent's own claims are ignored: every number here is
measured off its geometry.

usage: verify_part.py <part.dxf> <constraints.json> <out.json>
"""
import json
import math
import sys

import ezdxf
from ezdxf import path as ezpath
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union


def arc_radii_of(e):
    """radii of the circular-arc segments of an LWPOLYLINE, from its bulge values"""
    pts = [(p[0], p[1], p[4]) for p in e.get_points(format="xyseb")]
    out = []
    n = len(pts)
    for i, (x, y, b) in enumerate(pts):
        if abs(b) < 1e-9:
            continue
        x2, y2, _ = pts[(i + 1) % n]
        d = math.hypot(x2 - x, y2 - y)
        th = 4 * math.atan(b)
        r = d / (2 * math.sin(abs(th) / 2)) if abs(math.sin(th / 2)) > 1e-12 else 0.0
        out.append(round(r, 3))
    return out


def load(dxf_path):
    doc = ezdxf.readfile(dxf_path)
    outer_candidates, holes, texts = [], [], []
    arc_radii = []
    for e in doc.modelspace():
        t = e.dxftype()
        layer = (e.dxf.layer or "").upper()
        if t == "LWPOLYLINE":
            pts = [(v.x, v.y) for v in ezpath.make_path(e).flattening(0.02)]
            if len(pts) < 3:
                continue
            poly = Polygon(pts).buffer(0)
            if "HOLE" not in layer:
                arc_radii += arc_radii_of(e)
            (holes if "HOLE" in layer else outer_candidates).append(poly)
        elif t == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            poly = Point(c.x, c.y).buffer(r, 256)
            (holes if "HOLE" in layer else outer_candidates).append(poly)
        elif t == "TEXT":
            texts.append(e.dxf.text)
    if not outer_candidates:
        raise ValueError("no outer boundary polyline found")
    outer = max(outer_candidates, key=lambda p: p.area)
    # anything fully inside the outer boundary that is not the boundary itself counts as a hole
    inner = [p for p in outer_candidates if p is not outer and outer.contains(p.buffer(-1e-6))]
    holes = [h for h in holes + inner if h.area > 1e-9]
    return outer, holes, texts, arc_radii


def check(outer, holes, cons, arc_radii=()):
    net = outer.difference(unary_union(holes)) if holes else outer
    minx, miny, maxx, maxy = outer.bounds
    W, H = maxx - minx, maxy - miny
    out = []
    for c in cons:
        kind = c["type"]
        ok, got = False, None
        if kind == "hole_count":
            got = len(holes)
            ok = got == c["value"]
        elif kind == "hole_diameter":
            ds = sorted(round(2 * math.sqrt(h.area / math.pi), 4) for h in holes)
            got = ds
            tol = c.get("tol", 0.15)
            ok = bool(ds) and all(abs(d - c["value"]) <= tol for d in ds)
        elif kind == "hole_positions":
            # the requirement may not fix an origin; then compare positions relative to the part centre
            if c.get("relative_to_center"):
                cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
                wx = sum(p[0] for p in c["value"]) / len(c["value"])
                wy = sum(p[1] for p in c["value"]) / len(c["value"])
                cen = sorted([round(h.centroid.x - cx, 3), round(h.centroid.y - cy, 3)] for h in holes)
                want = sorted([round(p[0] - wx, 3), round(p[1] - wy, 3)] for p in c["value"])
            else:
                cen = sorted([round(h.centroid.x, 3), round(h.centroid.y, 3)] for h in holes)
                want = sorted([round(p[0], 3), round(p[1], 3)] for p in c["value"])
            got = cen
            tol = c.get("tol", 0.5)
            ok = len(cen) == len(want) and all(
                abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol for a, b in zip(cen, want))
        elif kind == "bbox_within":
            got = [round(W, 3), round(H, 3)]
            tol = c.get("tol", 0.01)
            ok = W <= c["value"][0] + tol and H <= c["value"][1] + tol
        elif kind == "bbox_equals":
            got = [round(W, 3), round(H, 3)]
            tol = c.get("tol", 0.5)
            ok = abs(W - c["value"][0]) <= tol and abs(H - c["value"][1]) <= tol
        elif kind == "min_wall":
            d = float("inf")
            for h in holes:
                d = min(d, h.exterior.distance(outer.exterior))
            for i, a in enumerate(holes):
                for b in holes[i + 1:]:
                    d = min(d, a.exterior.distance(b.exterior))
            got = None if d == float("inf") else round(d, 3)
            ok = got is not None and got >= c["value"] - 1e-3
        elif kind == "net_area_range":
            got = round(net.area, 3)
            ok = c["value"][0] <= got <= c["value"][1]
        elif kind == "outer_area_range":
            got = round(outer.area, 3)
            ok = c["value"][0] <= got <= c["value"][1]
        elif kind == "symmetric_about_x":
            axis = c.get("axis", (miny + maxy) / 2)
            mir = Polygon([(x, 2 * axis - y) for x, y in outer.exterior.coords]).buffer(0)
            got = round(outer.symmetric_difference(mir).area / max(outer.area, 1e-9), 5)
            ok = got <= c.get("tol", 0.01)
        elif kind == "symmetric_about_y":
            axis = c.get("axis", (minx + maxx) / 2)
            mir = Polygon([(2 * axis - x, y) for x, y in outer.exterior.coords]).buffer(0)
            got = round(outer.symmetric_difference(mir).area / max(outer.area, 1e-9), 5)
            ok = got <= c.get("tol", 0.01)
        elif kind == "corner_radius_min":
            # every convex corner must be rounded: no vertex with interior angle < threshold
            cs = list(outer.exterior.coords)[:-1]
            sharp = 0
            for i in range(len(cs)):
                a, b, cc = cs[i - 1], cs[i], cs[(i + 1) % len(cs)]
                v1 = (a[0] - b[0], a[1] - b[1])
                v2 = (cc[0] - b[0], cc[1] - b[1])
                n1 = math.hypot(*v1) or 1e-9
                n2 = math.hypot(*v2) or 1e-9
                ang = math.degrees(math.acos(max(-1, min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))))
                if ang < c.get("angle_deg", 100) and min(n1, n2) > c.get("min_edge", 0.6):
                    sharp += 1
            got = sharp
            ok = sharp == 0
        elif kind == "arc_radii":
            got = sorted(arc_radii)
            want = sorted(c["value"])
            tol = c.get("tol", 0.25)
            ok = len(got) == len(want) and all(abs(a - b) <= tol for a, b in zip(got, want))
        elif kind == "hole_inside":
            got = all(outer.contains(h) for h in holes)
            ok = bool(got) and len(holes) > 0
        elif kind == "single_region":
            got = 1 if net.geom_type == "Polygon" else len(net.geoms)
            ok = got == 1
        else:
            got = "unknown constraint"
        out.append({"type": kind, "want": c.get("value"), "got": got, "pass": bool(ok),
                    "label": c.get("label", kind)})
    return out


def main():
    dxf, cons_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    cons = json.loads(open(cons_path).read())
    try:
        outer, holes, texts, arc_radii = load(dxf)
    except Exception as e:
        json.dump({"loaded": False, "error": str(e)[:300], "checks": [], "score": "0/%d" % len(cons)},
                  open(out_path, "w"), indent=1)
        print("LOAD_FAILED", str(e)[:200])
        return
    checks = check(outer, holes, cons, arc_radii)
    npass = sum(1 for c in checks if c["pass"])
    minx, miny, maxx, maxy = outer.bounds
    res = {"loaded": True, "checks": checks, "score": f"{npass}/{len(checks)}",
           "all_pass": npass == len(checks),
           "measured": {"outer_area": round(outer.area, 3), "perimeter": round(outer.length, 3),
                        "bbox": [round(v, 3) for v in (minx, miny, maxx, maxy)],
                        "n_holes": len(holes), "texts": texts[:5]}}
    json.dump(res, open(out_path, "w"), indent=1)
    print(json.dumps({"score": res["score"], "measured": res["measured"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
