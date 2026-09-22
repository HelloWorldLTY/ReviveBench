#!/usr/bin/env python3
"""Reference place-and-route engine AND the independent layout checker for place_route.

Two clearly separated halves, and the separation matters:

  check_layout()  — judges a layout against SPEC §4/§5 using nothing but the design and the
                    candidate's own output. It never calls the placer or the router.
  solve()         — a reference row-placer + maze router, used to calibrate the verifier and to
                    provide the wirelength baseline.

Keeping them apart is the point. On the ERP task the calibration was structurally self-referential
(the oracle graded itself) and scored full marks while the oracle was wrong. Here the checker is
the oracle, and solve() is just another candidate that happens to be mine — so calibrating with it
genuinely exercises the checker.

All arithmetic is integer. Routing lives on grid points; a segment occupies every integer point
between its endpoints inclusive.

usage: ref_pnr.py <design.json> <out.json>
"""
import json
import pathlib
import sys
from collections import deque


# ------------------------------------------------------------------ geometry helpers

def cell_of(design, inst_id):
    for it in design["instances"]:
        if it["id"] == inst_id:
            return design["cells"][it["cell"]]
    raise KeyError(inst_id)


def pin_xy(design, placement, inst_id, pin):
    """Absolute grid coordinate of one instance pin, honouring `flip`."""
    c = cell_of(design, inst_id)
    p = placement[inst_id]
    px, py = c["pins"][pin]
    x = p["x"] + (c["w"] - px if p.get("flip") else px)
    return (x, p["y"] + py)


def seg_points(s):
    """Every integer grid point a segment covers, inclusive of both ends."""
    x1, y1, x2, y2 = s["x1"], s["y1"], s["x2"], s["y2"]
    if y1 == y2:
        lo, hi = sorted((x1, x2))
        return [(x, y1) for x in range(lo, hi + 1)]
    if x1 == x2:
        lo, hi = sorted((y1, y2))
        return [(x1, y) for y in range(lo, hi + 1)]
    return None                      # diagonal — illegal, caller reports it


# ------------------------------------------------------------------ the checker (oracle)

def check_layout(design, out):
    """Return (problems, metrics). `problems` empty means the layout satisfies SPEC §4 and §5."""
    probs = []
    die_w, die_h = design["die"]["w"], design["die"]["h"]
    rh, sw = design["row_height"], design["site_width"]
    placement = out.get("placement") or {}
    routes = out.get("routes") or {}

    # ---- §4 placement legality
    boxes = []
    for it in design["instances"]:
        iid = it["id"]
        if iid not in placement:
            probs.append(f"{iid}: no position given")
            continue
        p = placement[iid]
        c = design["cells"][it["cell"]]
        try:
            x, y = int(p["x"]), int(p["y"])
        except Exception:
            probs.append(f"{iid}: non-integer coordinates")
            continue
        w, h = c["w"], c["h"]
        if x < 0 or y < 0 or x + w > die_w or y + h > die_h:
            probs.append(f"{iid}: outside the die boundary ({x},{y},{w}x{h})")
        if y % rh:
            probs.append(f"{iid}: y={y} not aligned to row height {rh}")
        if x % sw:
            probs.append(f"{iid}: x={x} not aligned to site width {sw}")
        boxes.append((iid, x, y, w, h))

    for i in range(len(boxes)):
        ai, ax, ay, aw, ah = boxes[i]
        for j in range(i + 1, len(boxes)):
            bi, bx, by, bw, bh = boxes[j]
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                probs.append(f"{ai} and {bi} overlap")
        for b in design.get("blockages", []):
            if ax < b["x"] + b["w"] and b["x"] < ax + aw and ay < b["y"] + b["h"] and b["y"] < ay + ah:
                probs.append(f"{ai} sits on an obstacle")

    if probs:                        # routing checks are meaningless once the placement is illegal
        return probs, {}

    # ---- §5 routing: occupancy, shorts, direction, vias, connectivity
    occupied = {}                    # (layer,x,y) -> net
    routed_len = 0
    for net in design["nets"]:
        name = net["name"]
        r = routes.get(name)
        if not r:
            probs.append(f"net {name}: no routing")
            continue
        pts = {1: set(), 2: set()}
        for s in r.get("segments", []):
            lay = s.get("layer")
            if lay not in (1, 2):
                probs.append(f"net {name}: illegal layer {lay}")
                continue
            got = seg_points(s)
            if got is None:
                probs.append(f"net {name}: segment is neither horizontal nor vertical")
                continue
            if lay == 1 and s["y1"] != s["y2"]:
                probs.append(f"net {name}: layer 1 must be horizontal")
            if lay == 2 and s["x1"] != s["x2"]:
                probs.append(f"net {name}: layer 2 must be vertical")
            routed_len += len(got) - 1
            for (x, y) in got:
                if not (0 <= x <= die_w and 0 <= y <= die_h):
                    probs.append(f"net {name}: routing out of range ({x},{y})")
                    continue
                prev = occupied.get((lay, x, y))
                if prev is not None and prev != name:
                    probs.append(f"net {name} shorts with {prev} at L{lay}({x},{y})")
                occupied[(lay, x, y)] = name
                pts[lay].add((x, y))

        vias = [(v["x"], v["y"]) for v in r.get("vias", [])]
        for (vx, vy) in vias:
            if (vx, vy) not in pts[1] or (vx, vy) not in pts[2]:
                probs.append(f"net {name}: via ({vx},{vy}) lacks segments on both layers")

        # a pin must lie on a layer-1 segment of its own net
        pin_pts = []
        for (iid, pin) in net["pins"]:
            xy = pin_xy(design, placement, iid, pin)
            pin_pts.append(xy)
            if xy not in pts[1]:
                probs.append(f"net {name}: pin {iid}.{pin}@{xy} is not covered by a layer-1 segment")

        # connectivity: BFS over this net's grid points, with vias linking the two layers
        nodes = {(1, x, y) for (x, y) in pts[1]} | {(2, x, y) for (x, y) in pts[2]}
        if nodes:
            adj = {n: [] for n in nodes}
            for lay in (1, 2):
                for (x, y) in pts[lay]:
                    for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nb = (lay, x + dx, y + dy)
                        if nb in adj:
                            adj[(lay, x, y)].append(nb)
            for (vx, vy) in vias:
                a, b = (1, vx, vy), (2, vx, vy)
                if a in adj and b in adj:
                    adj[a].append(b); adj[b].append(a)
            start = (1, *pin_pts[0]) if pin_pts and (1, *pin_pts[0]) in adj else next(iter(nodes))
            seen = {start}
            dq = deque([start])
            while dq:
                for nb in adj[dq.popleft()]:
                    if nb not in seen:
                        seen.add(nb); dq.append(nb)
            missing = [p for p in pin_pts if (1, *p) not in seen]
            if missing:
                probs.append(f"net {name}: {len(missing)} pins disconnected, first {missing[0]}")

    # ---- HPWL self-consistency (recomputed from the candidate's own placement)
    hpwl = 0
    for net in design["nets"]:
        xs, ys = [], []
        for (iid, pin) in net["pins"]:
            if iid in placement:
                x, y = pin_xy(design, placement, iid, pin)
                xs.append(x); ys.append(y)
        if xs:
            hpwl += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return probs, {"hpwl": hpwl, "routed_len": routed_len}


# ------------------------------------------------------------------ the reference solver

def solve(design):
    """Row-packing placement + per-net L-shaped maze routing with detour on collision."""
    die_w, die_h = design["die"]["w"], design["die"]["h"]
    rh, sw = design["row_height"], design["site_width"]
    n_rows = die_h // rh

    # Placement: pack cells into the free segments of each row, with backtracking.
    #
    # A greedy first-fit-decreasing packer strands cells whenever the rows are exactly full:
    # d08_tight has capacity 20 and cells {4,4,3,3,3,3}, where greedy puts 4+4 in row 0 and
    # 3+3+3 in row 1 and cannot place the last cell, even though 4+3+3 twice fits perfectly.
    # This is bin packing, so the reference placer backtracks. Blockages split a row into
    # several independent segments, which fall out of the same slot model for free.
    def free_segments(k):
        y0, y1 = k * rh, (k + 1) * rh
        blocks = sorted((b["x"], b["x"] + b["w"]) for b in design.get("blockages", [])
                        if b["y"] < y1 and y0 < b["y"] + b["h"])
        segs, cur = [], 0
        for (b0, b1) in blocks:
            if b0 > cur:
                segs.append((cur, b0))
            cur = max(cur, b1)
        if cur < die_w:
            segs.append((cur, die_w))
        return segs

    slots = [(k, s, e) for k in range(n_rows) for (s, e) in free_segments(k)]
    placement = {}
    insts = sorted(design["instances"], key=lambda i: -design["cells"][i["cell"]]["w"])
    cursors = [s for (_, s, _) in slots]
    steps = [0]

    def pack(idx):
        if idx == len(insts):
            return True
        steps[0] += 1
        if steps[0] > 200000:                     # safety valve against pathological backtracking
            raise SystemExit("ref_pnr: placement backtracking exceeded its limit; the design may be unplaceable")
        it = insts[idx]
        w = design["cells"][it["cell"]]["w"]
        # best fit: try the slot with the least space left first, forcing a tight arrangement
        order = sorted(range(len(slots)), key=lambda j: slots[j][2] - cursors[j])
        for j in order:
            k, _, e = slots[j]
            x = ((cursors[j] + sw - 1) // sw) * sw
            if x + w <= e:
                placement[it["id"]] = {"x": x, "y": k * rh, "flip": False}
                old = cursors[j]
                cursors[j] = x + w
                if pack(idx + 1):
                    return True
                cursors[j] = old
                placement.pop(it["id"], None)
        return False

    if not pack(0):
        need = sum(design["cells"][i["cell"]]["w"] for i in design["instances"])
        cap = sum(e - s for (_, s, e) in slots)
        raise SystemExit(f"ref_pnr: cannot place, needs {need} with {cap} available (including site-alignment loss)")

    occupied = {}                    # (layer,x,y) -> net name
    routes = {}

    # Pass 1 — reserve EVERY net's pin points before routing anything.
    # Without this, a net routed early runs its wire straight over a pin belonging to a net routed
    # later, and the collision only surfaces when that later net tries to claim its own pin. Real
    # routers treat other nets' pins as obstacles for exactly this reason. (Interior pin offsets
    # already make genuine pin-vs-pin collisions impossible, so the raise below is a guard, not a
    # path the generator is expected to hit.)
    net_pts = {}
    for net in design["nets"]:
        pts = [pin_xy(design, placement, i, p) for (i, p) in net["pins"]]
        net_pts[net["name"]] = pts
        for p in pts:
            key = (1, p[0], p[1])
            o = occupied.get(key)
            if o is not None and o != net["name"]:
                raise SystemExit(
                    f"ref_pnr: grid point {p} is occupied by pins of both net {net['name']} and net {o}. "
                    f"Two causes: the same instance pin referenced by two nets (violating SPEC §2), "
                    f"or a cell-library pin offset that is not interior (violating SPEC §2's 1<=px<=w-1).")
            occupied[key] = net["name"]

    # Pass 2 — route with a real maze router.
    #
    # The first version tried a fixed L-shaped pattern at a sweep of horizontal bands. Once every
    # net's pins were reserved as obstacles that heuristic ran out of candidates and simply gave
    # up ("no available path"). The insight it missed: pins occupy layer 1 only, so vertical (layer-2)
    # travel is always free of them — a router that can switch layers can nearly always get around.
    # BFS over (layer, x, y) finds a path whenever one exists, which is the reliability an oracle
    # needs; the grid here is a few thousand nodes, so cost is irrelevant.
    def neighbours(node):
        lay, x, y = node
        if lay == 1:
            yield (1, x - 1, y)
            yield (1, x + 1, y)
            yield (2, x, y)
        else:
            yield (2, x, y - 1)
            yield (2, x, y + 1)
            yield (1, x, y)

    def free(node, name):
        lay, x, y = node
        if not (0 <= x <= die_w and 0 <= y <= die_h):
            return False
        o = occupied.get(node)
        return o is None or o == name

    def maze(sources, goal, name):
        """Shortest path from any node in `sources` to `goal`, avoiding other nets."""
        prev = {s: None for s in sources}
        dq = deque(sources)
        while dq:
            cur = dq.popleft()
            if cur == goal:
                path = []
                while cur is not None:
                    path.append(cur)
                    cur = prev[cur]
                return path[::-1]
            for nb in neighbours(cur):
                if nb not in prev and free(nb, name):
                    prev[nb] = cur
                    dq.append(nb)
        return None

    def to_segments(path):
        """Group a node path into same-layer runs plus a via at every layer change."""
        segs, vias = [], []
        run = [path[0]]
        for node in path[1:]:
            if node[0] == run[-1][0]:
                run.append(node)
            else:
                segs.append({"layer": run[0][0], "x1": run[0][1], "y1": run[0][2],
                             "x2": run[-1][1], "y2": run[-1][2]})
                vias.append({"x": node[1], "y": node[2]})
                run = [node]
        segs.append({"layer": run[0][0], "x1": run[0][1], "y1": run[0][2],
                     "x2": run[-1][1], "y2": run[-1][2]})
        return segs, vias

    for net in design["nets"]:
        name = net["name"]
        pts = net_pts[name]
        segs = [{"layer": 1, "x1": p[0], "y1": p[1], "x2": p[0], "y2": p[1]} for p in pts]
        vias = []
        tree = {(1, pts[0][0], pts[0][1])}
        for target in pts[1:]:
            goal = (1, target[0], target[1])
            if goal in tree:
                continue
            path = maze(list(tree), goal, name)
            if path is None:
                raise SystemExit(f"ref_pnr: net {name} has no available path (maze routing failed; the design is too dense)")
            for node in path:
                occupied[node] = name
                tree.add(node)
            s, v = to_segments(path)
            segs += s
            vias += v
        routes[name] = {"segments": segs, "vias": vias}

    _, met = check_layout(design, {"placement": placement, "routes": routes})
    return {"placement": placement, "routes": routes, "hpwl": met.get("hpwl", 0)}


def main():
    design = json.loads(pathlib.Path(sys.argv[1]).read_text())
    pathlib.Path(sys.argv[2]).write_text(json.dumps(solve(design), indent=1))


if __name__ == "__main__":
    main()
