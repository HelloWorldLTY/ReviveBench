#!/usr/bin/env python3
"""Hidden verifier for dca_keras3. Never copied into the workspace."""
import argparse, json, pathlib, sys, tempfile
import numpy as np, pandas as pd
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, check_env_constraints, pristine_tests_per_file, finish
TASK = json.loads((HERE.parent / "task.json").read_text())
R_MIN = TASK["thresholds"]["r_masked_min"]; R_RESID_MIN = TASK["thresholds"]["r_resid_min"]
# zinb-elempi is broken upstream even in the native env (oracle), so it is reported but not required
AE_TYPES = ["poisson", "nb", "nb-conddisp", "nb-shared", "nb-fork", "zinb", "zinb-conddisp", "zinb-shared", "zinb-fork"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws)
    checks, metrics = {}, {}

    c, vers = check_env_constraints({} if a.skip_env_check else TASK["constraints"], tmp, env)
    checks["env_constraints"] = c; metrics["versions"] = vers
    if not a.skip_env_check:   # legacy-keras shim is not an acceptable restoration
        rc, out = sh([PY, "-c", "import keras,sys; print('KERAS3_OK' if keras.__version__.startswith('3') else 'NOT_KERAS3'); import importlib; print('TFKERAS_SHIM' if importlib.util.find_spec('tf_keras') else 'NO_SHIM')"], tmp, env, 120)
        if "TFKERAS_SHIM" in out:
            checks["env_constraints"] = {"pass": False, "detail": c["detail"] + " ; tf_keras shim installed"}

    rc, out = sh([PY, "-c", "from dca.api import dca; from dca.network import AE_types; from dca.loss import NB, ZINB; from dca.layers import ConstantDispersionLayer, SliceLayer, ColwiseMultLayer, ElementwiseDense; import dca.train, dca.io; print('IMPORT_OK', sorted(AE_types))"], tmp, env, 300)
    checks["import"] = {"pass": rc == 0 and "IMPORT_OK" in out, "detail": out[-1500:]}

    csv = HERE / "data" / "test.csv"; fout = tmp / "functional.json"
    rc, out = sh([PY, str(HERE / "functional.py"), str(csv), str(fout)], tmp, env, 2400)
    if fout.exists():
        f = json.loads(fout.read_text()); metrics["functional"] = f
        ok = all(f.get(k) for k in ("shape_ok", "nan_free", "nonneg", "latent_ok", "info_ok")) \
            and f.get("r_masked", 0) >= R_MIN and f.get("r_resid", 0) >= R_RESID_MIN
        checks["functional_masked_recovery"] = {"pass": bool(ok), "detail": json.dumps(f)}
    else:
        checks["functional_masked_recovery"] = {"pass": False, "detail": out[-2500:]}

    # every autoencoder type builds + trains for 2 epochs on a tiny matrix
    code = ("import numpy as np, anndata as ad, sys, warnings; warnings.filterwarnings('ignore'); from dca.api import dca\n"
            "rng=np.random.RandomState(1); X=rng.negative_binomial(2,0.3,size=(120,60)).astype(np.float32)\n"
            "bad=[]\n"
            f"for t in {AE_TYPES}:\n"
            "    try:\n"
            "        a=ad.AnnData(X=X.copy()); a.obs_names=[f'c{i}' for i in range(120)]; a.var_names=[f'g{i}' for i in range(60)]\n"
            "        r=dca(a, ae_type=t, mode='denoise', copy=True, epochs=2, threads=2, verbose=False)\n"
            "        assert np.isfinite(np.asarray(r.X)).all()\n"
            "    except Exception as e: bad.append(f'{t}: {type(e).__name__}: {str(e)[:200]}')\n"
            "print('AE_BAD=' + ';'.join(bad))")
    rc, out = sh([PY, "-c", code], tmp, env, 1500)
    line = [l for l in out.splitlines() if l.startswith("AE_BAD=")]
    ok = rc == 0 and bool(line) and line[-1] == "AE_BAD="
    checks["all_ae_types_train"] = {"pass": ok, "detail": (line[-1] if line else out[-2000:])}

    # CLI: gene x cell csv -> outdir/mean.tsv
    df = pd.read_csv(csv, index_col=0)
    gxc = tmp / "counts_gxc.csv"; df.T.to_csv(gxc)
    outdir = tmp / "cli_out"
    # upstream __main__.py has no __name__ guard: the CLI is the console-script entry `dca.__main__:main`
    cli = f"import sys; sys.argv=['dca', {str(gxc)!r}, {str(outdir)!r}, '-e', '20', '--threads', '4']; from dca.__main__ import main; main()"
    rc, out = sh([PY, "-c", cli], tmp, env, 1500)
    ok = rc == 0 and (outdir / "mean.tsv").exists()
    if ok:
        m = pd.read_csv(outdir / "mean.tsv", sep="\t", index_col=0)
        ok = (df.shape[0] in m.shape) and np.isfinite(m.values).all()
        out += f"\nmean.tsv shape={m.shape}"
    checks["cli_end_to_end"] = {"pass": bool(ok), "detail": out[-1500:]}

    pt = pristine_tests_per_file(HERE / "pristine" / "repo.tar.gz", tmp, env, "dca/test.py", timeout=2400, workspace=ws, overlay=["dca/test.py", "data", "pytest.ini"])
    pt["informational"] = True   # depends on an external paul15 download; reported, not required
    checks["pristine_unit_tests"] = pt
    finish(a.out, checks, metrics, tmp)


if __name__ == "__main__":
    main()
