#!/usr/bin/env python3
"""Build hidden FEM benchmark models (CalculiX .inp) with gmsh and analytical references. Run in industrial_oracle env."""
import gmsh, math, json, pathlib, numpy as np
HERE = pathlib.Path(__file__).resolve().parent
E, NU, RHO = 210e9, 0.3, 7850.0

def mesh_rect(L, H, nx, ny, order=2):
    """structured quad mesh of a rectangle [0,L]x[0,H]; returns nodes {id:(x,y)}, elems [(id,[n...])] CPS4 or CPS8"""
    nodes, elems = {}, []
    if order == 1:
        nid = {}; k = 1
        for j in range(ny + 1):
            for i in range(nx + 1): nid[(i, j)] = k; nodes[k] = (L * i / nx, H * j / ny); k += 1
        e = 1
        for j in range(ny):
            for i in range(nx): elems.append((e, [nid[(i, j)], nid[(i + 1, j)], nid[(i + 1, j + 1)], nid[(i, j + 1)]])); e += 1
    else:  # serendipity 8-node: grid at half spacing, skip cell centres
        nid = {}; k = 1
        for j in range(2 * ny + 1):
            for i in range(2 * nx + 1):
                if i % 2 == 1 and j % 2 == 1: continue
                nid[(i, j)] = k; nodes[k] = (L * i / (2 * nx), H * j / (2 * ny)); k += 1
        e = 1
        for j in range(ny):
            for i in range(nx):
                a, b = 2 * i, 2 * j
                elems.append((e, [nid[(a, b)], nid[(a + 2, b)], nid[(a + 2, b + 2)], nid[(a, b + 2)], nid[(a + 1, b)], nid[(a + 2, b + 1)], nid[(a + 1, b + 2)], nid[(a, b + 1)]])); e += 1
    return nodes, elems

def write_inp(path, nodes, elems, etype, nsets, elsets, material, steps, thickness=None):
    L = ["*HEADING", path.stem, "*NODE"]
    L += [f"{k}, {x:.10g}, {y:.10g}, 0.0" for k, (x, y) in nodes.items()]
    L.append(f"*ELEMENT, TYPE={etype}, ELSET=EALL")
    L += [f"{e}, " + ", ".join(map(str, n)) for e, n in elems]
    for name, ids in nsets.items():
        L.append(f"*NSET, NSET={name}"); L += [", ".join(map(str, ids[i:i + 12])) for i in range(0, len(ids), 12)]
    for name, ids in elsets.items():
        L.append(f"*ELSET, ELSET={name}"); L += [", ".join(map(str, ids[i:i + 12])) for i in range(0, len(ids), 12)]
    L += ["*MATERIAL, NAME=STEEL", "*ELASTIC", f"{material['E']}, {material['nu']}", "*DENSITY", f"{material['rho']}",
          f"*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL" + (f"\n{thickness}" if thickness else "")]
    L += steps
    path.write_text("\n".join(L) + "\n")

models = {}
# 1. cantilever, plane stress CPS8, tip load (Timoshenko reference)
Lb, Hb, t, P = 1.0, 0.1, 0.01, 1000.0
nodes, elems = mesh_rect(Lb, Hb, 40, 4, 2)
left = [k for k, (x, y) in nodes.items() if abs(x) < 1e-9]; right = [k for k, (x, y) in nodes.items() if abs(x - Lb) < 1e-9]
tip = [k for k in right if abs(nodes[k][1] - Hb / 2) < 1e-9][0]
I = t * Hb ** 3 / 12; A = t * Hb; kappa = 5 / 6; G = E / (2 * (1 + NU))
v_tip = P * Lb ** 3 / (3 * E * I) + P * Lb / (kappa * G * A)
steps = ["*BOUNDARY", "LEFT, 1, 2", "*STEP", "*STATIC", "*CLOAD", f"{tip}, 2, {-P}", "*NODE FILE", "U", "*EL FILE", "S", "*NODE PRINT, NSET=NALL", "U", "*END STEP"]
write_inp(HERE / "models" / "cantilever_cps8.inp", nodes, elems, "CPS8", {"LEFT": left, "NALL": list(nodes)}, {}, {"E": E, "nu": NU, "rho": RHO}, steps, t)
models["cantilever_cps8"] = {"kind": "static", "probe": {"node": tip, "dof": 2, "analytic": -v_tip, "tol": 0.03}, "note": "tip deflection vs Timoshenko"}
# 2. Lamé thick cylinder, plane strain CPE8, quarter model, internal pressure
a, b, p = 0.05, 0.10, 50e6
gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
def gmsh_quad_mesh(build, order, size=None):
    """transfinite (mapped) all-quad mesh; build() must set transfinite curves/surfaces"""
    gmsh.model.add("m"); build(); gmsh.model.geo.synchronize()
    gmsh.option.setNumber("Mesh.ElementOrder", order); gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 1)
    gmsh.model.mesh.generate(2)
    tags, coords, _ = gmsh.model.mesh.getNodes(); nodes = {int(tg): (float(coords[3 * i]), float(coords[3 * i + 1])) for i, tg in enumerate(tags)}
    et, etags, enodes = gmsh.model.mesh.getElements(2); assert len(et) == 1, et
    npe = 8 if order == 2 else 4; elems = [(int(etags[0][i]), [int(x) for x in enodes[0][npe * i:npe * (i + 1)]]) for i in range(len(etags[0]))]
    gmsh.clear(); return nodes, elems
def build_cyl():
    g = gmsh.model.geo; c = g.addPoint(0, 0, 0); p1 = g.addPoint(a, 0, 0); p2 = g.addPoint(b, 0, 0); p3 = g.addPoint(0, b, 0); p4 = g.addPoint(0, a, 0)
    l1 = g.addLine(p1, p2); l2 = g.addCircleArc(p2, c, p3); l3 = g.addLine(p3, p4); l4 = g.addCircleArc(p4, c, p1)
    sf = g.addPlaneSurface([g.addCurveLoop([l1, l2, l3, l4])]); g.synchronize()
    for l, n in ((l1, 13), (l3, 13), (l2, 25), (l4, 25)): g.mesh.setTransfiniteCurve(l, n)
    g.mesh.setTransfiniteSurface(sf); g.mesh.setRecombine(2, sf)
nodes, elems = gmsh_quad_mesh(build_cyl, 2)
bottom = [k for k, (x, y) in nodes.items() if abs(y) < 1e-7]; leftn = [k for k, (x, y) in nodes.items() if abs(x) < 1e-7]
inner_el = []  # faces on inner radius: element edges with all nodes at r=a -> use *DLOAD with face numbers is mesh dependent; apply pressure via consistent nodal loads instead
inner = [k for k, (x, y) in nodes.items() if abs(math.hypot(x, y) - a) < 1e-6]
# consistent nodal loads for quadratic edges on the inner arc: integrate p along arc for each element edge
edge_loads = {}
for e, n in elems:
    corners, mids = n[:4], n[4:]
    for i in range(4):
        n1, n2, nm = corners[i], corners[(i + 1) % 4], mids[i]
        if all(abs(math.hypot(*nodes[q]) - a) < 1e-6 for q in (n1, n2, nm)):
            x1, y1 = nodes[n1]; x2, y2 = nodes[n2]; th1, th2 = math.atan2(y1, x1), math.atan2(y2, x2); dth = abs(th2 - th1); Larc = a * dth
            # quadratic edge shape functions: end weights 1/6, mid 2/3 of total force p*Larc*t, direction = radial (outward from centre)
            for q, w in ((n1, 1 / 6), (n2, 1 / 6), (nm, 2 / 3)):
                xq, yq = nodes[q]; r = math.hypot(xq, yq); F = p * Larc * w
                fx, fy = edge_loads.get(q, (0.0, 0.0)); edge_loads[q] = (fx + F * xq / r, fy + F * yq / r)
cl = [f"{q}, 1, {fx:.10g}\n{q}, 2, {fy:.10g}" for q, (fx, fy) in edge_loads.items()]
steps = ["*BOUNDARY", "BOTTOM, 2", "LEFTN, 1", "*STEP", "*STATIC", "*CLOAD"] + cl + ["*NODE FILE", "U", "*EL FILE", "S", "*NODE PRINT, NSET=NALL", "U", "*END STEP"]
write_inp(HERE / "models" / "lame_cylinder_cpe8.inp", nodes, elems, "CPE8", {"BOTTOM": bottom, "LEFTN": leftn, "NALL": list(nodes), "INNER": inner}, {}, {"E": E, "nu": NU, "rho": RHO}, steps, None)
# Lamé plane strain radial displacement u(r) = (1+nu) p a^2 /(E (b^2-a^2)) * ((1-2nu) r + b^2/r)
def u_lame(r): return (1 + NU) * p * a * a / (E * (b * b - a * a)) * ((1 - 2 * NU) * r + b * b / r)
probe = [k for k in bottom if abs(nodes[k][0] - b) < 1e-6][0]
models["lame_cylinder_cpe8"] = {"kind": "static", "probe": {"node": probe, "dof": 1, "analytic": u_lame(b), "tol": 0.02}, "note": "outer radius displacement vs Lame plane strain"}
# 3. Kirsch plate with hole, plane stress CPS8, quarter model, uniform tension: hoop stress at hole = 3*sigma
W, R, sig = 0.5, 0.05, 100e6
def build_plate():
    g = gmsh.model.geo; c = g.addPoint(0, 0, 0); p1 = g.addPoint(R, 0, 0); p2 = g.addPoint(W, 0, 0); p3 = g.addPoint(W, W, 0); p4 = g.addPoint(0, W, 0); p5 = g.addPoint(0, R, 0)
    p6 = g.addPoint(R / math.sqrt(2), R / math.sqrt(2), 0)
    l1 = g.addLine(p1, p2); l2 = g.addLine(p2, p3); l3 = g.addLine(p3, p6); a1 = g.addCircleArc(p6, c, p1)
    l4 = g.addLine(p3, p4); l5 = g.addLine(p4, p5); a2 = g.addCircleArc(p5, c, p6)
    sA = g.addPlaneSurface([g.addCurveLoop([l1, l2, l3, a1])]); sB = g.addPlaneSurface([g.addCurveLoop([-l3, l4, l5, a2])]); g.synchronize()
    for l in (l1, l3, l5): g.mesh.setTransfiniteCurve(l, 31, "Progression", 1.08)
    for l in (l2, a1, l4, a2): g.mesh.setTransfiniteCurve(l, 21)
    for sf in (sA, sB): g.mesh.setTransfiniteSurface(sf); g.mesh.setRecombine(2, sf)
nodes, elems = gmsh_quad_mesh(build_plate, 2)
bottom = [k for k, (x, y) in nodes.items() if abs(y) < 1e-7]; leftn = [k for k, (x, y) in nodes.items() if abs(x) < 1e-7]; rightn = [k for k, (x, y) in nodes.items() if abs(x - W) < 1e-7]
loads = {}
for e, n in elems:
    corners, mids = n[:4], n[4:]
    for i in range(4):
        n1, n2, nm = corners[i], corners[(i + 1) % 4], mids[i]
        if all(abs(nodes[q][0] - W) < 1e-7 for q in (n1, n2, nm)):
            Le = abs(nodes[n2][1] - nodes[n1][1]); F = sig * Le * t
            for q, w in ((n1, 1 / 6), (n2, 1 / 6), (nm, 2 / 3)): loads[q] = loads.get(q, 0.0) + F * w
cl = [f"{q}, 1, {f:.10g}" for q, f in loads.items()]
steps = ["*BOUNDARY", "BOTTOM, 2", "LEFTN, 1", "*STEP", "*STATIC", "*CLOAD"] + cl + ["*NODE FILE", "U", "*EL FILE", "S", "*NODE PRINT, NSET=NALL", "U", "*END STEP"]
write_inp(HERE / "models" / "kirsch_plate_cps8.inp", nodes, elems, "CPS8", {"BOTTOM": bottom, "LEFTN": leftn, "RIGHT": rightn, "NALL": list(nodes)}, {}, {"E": E, "nu": NU, "rho": RHO}, steps, t)
top_hole = [k for k in leftn if abs(nodes[k][1] - R) < 1e-6][0]
models["kirsch_plate_cps8"] = {"kind": "static", "probe_stress": {"node": top_hole, "component": "sxx", "analytic": 3 * sig, "tol": 0.06}, "note": "stress concentration at hole (Kirsch), finite-width correction ~ +2%"}
# 4. cantilever modal, CPS8, first 3 bending frequencies (Euler-Bernoulli reference)
nodes, elems = mesh_rect(Lb, Hb, 40, 4, 2)
left = [k for k, (x, y) in nodes.items() if abs(x) < 1e-9]
steps = ["*BOUNDARY", "LEFT, 1, 2", "*STEP", "*FREQUENCY", "6", "*NODE FILE", "U", "*END STEP"]
write_inp(HERE / "models" / "cantilever_modal_cps8.inp", nodes, elems, "CPS8", {"LEFT": left, "NALL": list(nodes)}, {}, {"E": E, "nu": NU, "rho": RHO}, steps, t)
bl = [1.8751, 4.6941, 7.8548]; fa = [(x ** 2) / (2 * math.pi * Lb ** 2) * math.sqrt(E * I / (RHO * A)) for x in bl]
models["cantilever_modal_cps8"] = {"kind": "modal", "analytic_bending_hz": fa, "tol": 0.05, "note": "first bending modes vs Euler-Bernoulli (shear/rotary inertia lower the FE values by ~1-2%)"}
gmsh.finalize()
json.dump(models, open(HERE / "ref" / "models.json", "w"), indent=1); print(json.dumps(models, indent=0)[:1200]); print({m: len(open(HERE / "models" / f"{m}.inp").read().splitlines()) for m in models})
