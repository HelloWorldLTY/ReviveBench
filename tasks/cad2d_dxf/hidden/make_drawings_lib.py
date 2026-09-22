import math
from shapely.geometry import Polygon

def bulge_poly(pts, n=256):
    """Polygon from LWPOLYLINE vertices with bulges (arcs densified with n segments each).
    DXF bulge b = tan(theta/4), theta = signed included angle (positive = CCW from this vertex to the next).
    Centre = chord midpoint + left-normal * d / (2 tan(theta/2)); verified against ezdxf path flattening."""
    out = []
    m = len(pts)
    for i, (x, y, b) in enumerate(pts):
        x2, y2, _ = pts[(i + 1) % m]
        if abs(b) < 1e-12:
            out.append((x, y)); continue
        th = 4.0 * math.atan(b)
        d = math.hypot(x2 - x, y2 - y)
        if d < 1e-15:
            out.append((x, y)); continue
        nx, ny = -(y2 - y) / d, (x2 - x) / d          # left normal of the chord direction
        t = math.tan(th / 2.0)
        off = d / (2.0 * t) if abs(t) > 1e-15 else 0.0
        cx, cy = (x + x2) / 2.0 + nx * off, (y + y2) / 2.0 + ny * off
        a0 = math.atan2(y - cy, x - cx)
        for k in range(n):
            a = a0 + th * k / n
            r = math.hypot(x - cx, y - cy)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return Polygon(out)
