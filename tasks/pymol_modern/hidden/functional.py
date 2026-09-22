"""Hidden functional check for PyMOL (headless). Usage: functional.py <datadir> <out.json>"""
import sys, json, os, struct, tempfile
import numpy as np
datadir, out = sys.argv[1], sys.argv[2]
res = {}
import pymol2
with pymol2.PyMOL() as p:
    cmd = p.cmd
    cmd.load(os.path.join(datadir, "1ubq.pdb"), "u"); cmd.load(os.path.join(datadir, "1crn.pdb"), "c")
    cmd.load(os.path.join(datadir, "2lzm.pdb"), "l")
    res["n_atoms_1ubq"] = cmd.count_atoms("u"); res["n_ca_1ubq"] = cmd.count_atoms("u and polymer and name CA")
    res["n_atoms_2lzm"] = cmd.count_atoms("l"); res["n_waters_2lzm"] = cmd.count_atoms("l and resn HOH")
    res["dist_ca1_ca76"] = round(cmd.get_distance("u///1/CA", "u///76/CA"), 4)
    cmd.dss("u"); ss = {}
    cmd.iterate("u and name CA", "ss_.setdefault(ss or 'L', 0); ss_[ss or 'L'] += 1", space={"ss_": ss})
    res["ss_1ubq"] = ss
    res["fasta_1ubq"] = "".join(cmd.get_fastastr("u").split("\n")[1:]).strip()
    res["align_rmsd_lzm_ubq"] = round(float(cmd.align("l and name CA", "u and name CA", cycles=0)[0]), 3)
    xyz = cmd.get_coords("u"); res["coords_shape"] = list(xyz.shape); res["coords_dtype"] = str(xyz.dtype)
    res["coords_centroid"] = [round(float(v), 3) for v in xyz.mean(axis=0)]
    xyz2 = xyz + np.array([1.0, 2.0, 3.0]); cmd.load_coords(xyz2, "u")
    res["load_coords_ok"] = bool(np.allclose(cmd.get_coords("u"), xyz2, atol=1e-4))
    png = os.path.join(tempfile.mkdtemp(), "r.png")
    cmd.hide("everything"); cmd.show("cartoon", "u"); cmd.color("red", "u"); cmd.orient("u")
    cmd.png(png, width=320, height=240, ray=1)
    ok = os.path.exists(png)
    if ok:
        with open(png, "rb") as fh:
            hdr = fh.read(24)
        w, h = struct.unpack(">II", hdr[16:24]); res["png_size"] = [w, h]; res["png_bytes"] = os.path.getsize(png)
        ok = (w, h) == (320, 240) and res["png_bytes"] > 4000
    res["png_ok"] = bool(ok)
json.dump(res, open(out, "w"), indent=1); print("FUNC=" + json.dumps(res))
