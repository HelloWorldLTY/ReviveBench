#!/usr/bin/env python3
"""Hidden verifier for pymol_modern (headless). Compares against hidden/oracle_reference.json."""
import argparse, json, pathlib, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, check_env_constraints, finish
TASK = json.loads((HERE.parent / "task.json").read_text())
REF = json.loads((HERE / "oracle_reference.json").read_text())["metrics"]["functional"] if (HERE / "oracle_reference.json").exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws)
    env.pop("PYTHONPATH", None)   # PyMOL must be INSTALLED into the env; the workspace is only the source
    checks, metrics = {}, {}
    c, vers = check_env_constraints({} if a.skip_env_check else TASK["constraints"], tmp, env)
    if not a.skip_env_check:
        rc, out = sh([PY, "-c", "import sys,pymol,os; print('PYVER=%d.%d'%sys.version_info[:2]); print('PYMOL_FILE='+os.path.realpath(pymol.__file__))"], tmp, env, 120)
        pv = [l for l in out.splitlines() if l.startswith("PYVER=")]
        if not pv or tuple(int(x) for x in pv[-1][6:].split(".")) < tuple(int(x) for x in TASK["python_min"].split(".")):
            c = {"pass": False, "detail": c["detail"] + f" ; python {pv} < {TASK['python_min']}"}
        # anti-shortcut: the installed pymol must not be a conda-forge/pip prebuilt package
        rc2, out2 = sh(["bash", "-c", "ls $CONDA_PREFIX/conda-meta 2>/dev/null | grep -i '^pymol' ; pip show pymol 2>/dev/null | grep -i '^Version'"], tmp, env, 120)
        metrics["pymol_dist_hits"] = out2.strip()
        if "pymol-open-source" in out2 or "pymol-bundle" in out2:
            c = {"pass": False, "detail": c["detail"] + " ; prebuilt pymol package installed: " + out2.strip()}
    checks["env_constraints"] = c; metrics["versions"] = vers

    rc, out = sh([PY, "-c", "import pymol, pymol2; from pymol import cmd; import pymol._cmd; print('IMPORT_OK', pymol.__file__)"], tmp, env, 300)
    checks["import"] = {"pass": rc == 0 and "IMPORT_OK" in out, "detail": out[-1500:]}

    fout = tmp / "func.json"
    rc, out = sh([PY, str(HERE / "functional.py"), str(HERE / "data"), str(fout)], tmp, env, 1200)
    if fout.exists():
        f = json.loads(fout.read_text()); metrics["functional"] = f
        if REF:
            bad = []
            for k in ("n_atoms_1ubq", "n_ca_1ubq", "n_atoms_2lzm", "n_waters_2lzm", "fasta_1ubq", "coords_shape", "load_coords_ok"):
                if f.get(k) != REF.get(k): bad.append(k)
            if abs(f.get("dist_ca1_ca76", 1e9) - REF["dist_ca1_ca76"]) > 1e-3: bad.append("dist_ca1_ca76")
            if abs(f.get("align_rmsd_lzm_ubq", 1e9) - REF["align_rmsd_lzm_ubq"]) > 0.05: bad.append("align_rmsd")
            for kk in REF["ss_1ubq"]:
                if abs(f.get("ss_1ubq", {}).get(kk, 0) - REF["ss_1ubq"][kk]) > 3: bad.append("ss_" + kk)
            if max(abs(x - y) for x, y in zip(f.get("coords_centroid", [1e9]*3), REF["coords_centroid"])) > 1e-2: bad.append("centroid")
            checks["functional_vs_oracle"] = {"pass": not bad, "detail": "mismatch: " + ",".join(bad) if bad else "all match oracle"}
        else:
            checks["functional_vs_oracle"] = {"pass": True, "detail": "no oracle reference (calibration run)"}
        checks["ray_png_headless"] = {"pass": bool(f.get("png_ok")), "detail": json.dumps({k: f.get(k) for k in ("png_ok", "png_size", "png_bytes")})}
    else:
        checks["functional_vs_oracle"] = {"pass": False, "detail": out[-2500:]}
        checks["ray_png_headless"] = {"pass": False, "detail": out[-800:]}

    # CLI launcher headless
    pml = tmp / "s.pml"; pml.write_text(f"load {HERE/'data'/'1ubq.pdb'}, u\nprint('CLI_ATOMS', cmd.count_atoms('u'))\n")
    rc, out = sh(["bash", "-c", f"pymol -cq {pml}"], tmp, env, 600)
    n = REF["n_atoms_1ubq"] if REF else None
    checks["cli_headless"] = {"pass": rc == 0 and "CLI_ATOMS" in out and (n is None or str(n) in out), "detail": out[-1200:]}
    finish(a.out, checks, metrics, tmp)


if __name__ == "__main__":
    main()
