#!/usr/bin/env python3
"""Analyse a candidate's STL and report its topology. Runs in envs/cad3d_oracle (needs trimesh).

The hidden verifier itself runs in the candidate's environment, which has no geometry libraries,
so all mesh analysis is delegated here by subprocess — the same split cad2d_dxf uses for ezdxf.

Prints one JSON object: {closed, euler, shells, volume, faces, dropped}.
On any failure prints {"error": "..."} and exits 0, so the verifier can record the reason rather
than crashing.

usage: mesh_topo.py <mesh.stl>
"""
import json
import sys


def main():
    try:
        import trimesh
        m = trimesh.load(sys.argv[1], force="mesh", process=True)
        n_before = len(m.faces)

        # Drop zero-area facets before judging closure. OCC's own STL export leaves stray
        # degenerate triangles behind, and on a cavity model they make trimesh's whole-mesh
        # is_watertight False even though both real shells are closed and the signed volume is
        # right to 0.01%. Grading on the raw flag would fail every correct cavity model.
        keep = m.area_faces > 1e-12
        if not keep.all():
            m.update_faces(keep)
        m.remove_unreferenced_vertices()
        m.merge_vertices()

        parts = [p for p in m.split(only_watertight=False) if len(p.faces) > 3]
        out = {"closed": bool(all(p.is_watertight for p in parts)),
               "euler": int(sum(p.euler_number for p in parts)),
               "shells": len(parts),
               "volume": float(m.volume),
               "faces": int(len(m.faces)),
               "dropped": int(n_before - len(m.faces))}
    except Exception as e:  # noqa: BLE001 - the verifier wants the reason, not a traceback
        out = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
