#!/usr/bin/env python3
"""Hidden verifier for cad2d_dxf: run agent's cadx on hidden commands; check JSON answers and written DXFs via ezdxf/shapely (oracle env)."""
import argparse, json, pathlib, shutil, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, finish
ORACLE_PY = str(HERE.parents[2] / "envs" / "industrial_oracle" / "bin" / "python")
FORBIDDEN = ("ezdxf", "shapely", "cadquery", "ocp", "pythonocc-core", "dxfgrabber", "matplotlib", "scipy", "pandas")
def rel(a, b): return abs(a - b) / max(abs(b), 1e-9)
def oracle(dxf, env):
    rc, out = sh([ORACLE_PY, str(HERE / "oracle_check.py"), str(dxf)], HERE, env, 300)
    line = [l for l in out.splitlines() if l.startswith("{")]
    return json.loads(line[-1]) if line else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true"); ap.add_argument("--engine", default=None)
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve(); tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws); env.pop("PYTHONPATH", None)
    checks, metrics = {}, {}
    if not a.skip_env_check:
        rc, out = sh(["bash", "-c", "pip list 2>/dev/null | awk '{print tolower($1)}'"], tmp, env, 120)
        bad = [p for p in FORBIDDEN if p in out.split()]
        checks["env_constraints"] = {"pass": not bad, "detail": "forbidden: " + ",".join(bad) if bad else "ok"}
        checks["launcher_present"] = {"pass": (ws / "run_cad.sh").exists(), "detail": "run_cad.sh"}
    engine = a.engine.split() if a.engine else ["bash", str(ws / "run_cad.sh")]
    cmds = json.loads((HERE / "ref" / "commands.json").read_text()); per, n_pass = {}, 0
    for c in cmds:
        wd = tmp / c["name"]; wd.mkdir()
        for d in HERE.glob("drawings/*.dxf"): shutil.copy(d, wd / d.name)
        (wd / "cmd.json").write_text(json.dumps(c["cmd"])); rc, log = sh(engine + ["cmd.json", "out.json"], wd, env, 300)
        rec = {"rc": rc}; ok = False; ref = c["ref"]; op = c["cmd"]["op"]
        try:
            res = json.loads((wd / "out.json").read_text())
            if op == "measure":
                ok = res.get("entities") == ref["entities"] and sorted(res.get("layers", [])) == ref["layers"] and all(rel(x, y) <= 1e-3 or abs(x - y) <= 1e-3 for x, y in zip(res["bbox"], ref["bbox"]))
                shapes = res.get("shapes", []); ok &= len(shapes) == len(ref["shapes"])
                for s_, r_ in zip(shapes, ref["shapes"]):
                    ok &= s_.get("type") == r_["type"] and rel(s_["area"], r_["area"]) <= 1e-3 and rel(s_["perimeter"], r_["perimeter"]) <= 1e-3 and max(abs(s_["centroid"][0] - r_["centroid"][0]), abs(s_["centroid"][1] - r_["centroid"][1])) <= 1e-3
                rec["detail"] = {"entities_ok": res.get("entities") == ref["entities"], "n_shapes": len(shapes)}
            elif op in ("offset", "fillet"):
                o = oracle(wd / c["cmd"]["out_dxf"], env); area = sum(p["area"] for p in o["polys"]) if o else None
                ok = o is not None and len(o["polys"]) == 1 and rel(area, ref["area"]) <= 5e-3 and rel(res.get("area", 0), ref["area"]) <= 5e-3 and rel(o["polys"][0]["perimeter"], ref["perimeter"]) <= 5e-3
                rec["detail"] = {"file_area": area, "json_area": res.get("area"), "ref_area": ref["area"]}
            elif op == "boolean":
                o = oracle(wd / c["cmd"]["out_dxf"], env)
                area = (sum(p["area"] for p in o["polys"]) - sum(h["area"] for h in o["holes"])) if o else None
                ok = o is not None and rel(area, ref["area"]) <= 5e-3 and rel(res.get("area", 0), ref["area"]) <= 5e-3 and len(o["polys"]) == ref["regions"]
                rec["detail"] = {"file_area": area, "json_area": res.get("area"), "ref_area": ref["area"], "regions": len(o["polys"]) if o else None}
            elif op == "transform":
                o = oracle(wd / c["cmd"]["out_dxf"], env); got = o["polys"] if o else []
                ok = o is not None and len(got) == len(ref["shapes"]) and all(rel(g["area"], r_["area"]) <= 1e-3 and max(abs(g["centroid"][0] - r_["centroid"][0]), abs(g["centroid"][1] - r_["centroid"][1])) <= 1e-2 for g, r_ in zip(got, ref["shapes"]))
                rec["detail"] = {"n": len(got)}
            elif op == "write":
                o = oracle(wd / c["cmd"]["out_dxf"], env)
                ok = o is not None and o["entities"] == {"LINE": 1, "CIRCLE": 1, "ARC": 1, "LWPOLYLINE": 1, "TEXT": 1} and o.get("texts") == ["HELLO"] and any(rel(p["area"], ref["poly_area"]) <= 1e-3 for p in o["polys"]) and res.get("written") == 5
                rec["detail"] = o["entities"] if o else "unreadable"
        except Exception as e:
            rec["error"] = (str(e) + " | " + log[-300:])[-500:]
        rec["pass"] = bool(ok); per[c["name"]] = rec; n_pass += bool(ok)
    metrics["per_command"] = per; metrics["n_pass"] = n_pass; metrics["n_total"] = len(per)
    checks["geometry_vs_oracle"] = {"pass": n_pass >= 0.8 * len(per), "detail": f"{n_pass}/{len(per)} operations correct; failures: " + ", ".join(k for k, v in per.items() if not v["pass"])}
    finish(a.out, checks, metrics, tmp)
if __name__ == "__main__": main()
