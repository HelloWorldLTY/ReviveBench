#!/usr/bin/env python3
"""Hidden verifier for the gapfill tasks. Never copied into the workspace."""
import argparse, json, pathlib, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, check_env_constraints, pristine_tests_per_file, finish

TASK = json.loads((HERE.parent / "task.json").read_text())
# calibrated on the oracle env (TF 2.10 / Keras 2.10), see hidden/oracle_reference.json:
# r_masked ~0.89 ; require most of that, plus that predictions carry per-cell signal (r_resid > 0)
R_MIN = TASK.get("thresholds", {}).get("r_masked_min", 0.80)
R_RESID_MIN = TASK.get("thresholds", {}).get("r_resid_min", 0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_"))
    env = make_env(ws)
    checks, metrics = {}, {}

    c, vers = check_env_constraints({} if a.skip_env_check else TASK.get("constraints", {}), tmp, env)
    checks["env_constraints"] = c; metrics["versions"] = vers

    rc, out = sh([PY, "-c", "from gapfill.subnet import SubnetImputer; from gapfill import gapfill_cli, cli_args, helpers, masking; print('IMPORT_OK')"], tmp, env, 300)
    checks["import"] = {"pass": rc == 0 and "IMPORT_OK" in out, "detail": out[-1500:]}

    csv = HERE / "data" / "test.csv"
    fout = tmp / "functional.json"
    rc, out = sh([PY, str(HERE / "functional.py"), str(csv), str(fout)], tmp, env, 1500)
    if fout.exists():
        f = json.loads(fout.read_text()); metrics["functional"] = f
        ok = all(f.get(k) for k in ("shape_ok", "nan_free", "nonneg", "restore_exact")) \
            and f.get("r_masked", 0) >= R_MIN and f.get("r_resid", 0) >= R_RESID_MIN
        checks["functional_masked_recovery"] = {"pass": bool(ok), "detail": json.dumps(f)}
    else:
        checks["functional_masked_recovery"] = {"pass": False, "detail": out[-2500:]}

    cli_out = tmp / "cli_out.csv"
    rc, out = sh([PY, "-m", "gapfill.gapfill_cli", str(csv), "-o", str(cli_out),
                  "--max-epochs", "50", "--cores", "4"], tmp, env, 900)
    ok = rc == 0 and cli_out.exists()
    if ok:
        chk = ("import pandas as pd,numpy as np,sys; a=pd.read_csv(sys.argv[1],index_col=0); b=pd.read_csv(sys.argv[2],index_col=0);"
               "assert a.shape==b.shape and (a.index==b.index).all(); obs=a.values>0;"
               "assert np.allclose(a.values[obs], b.values[obs]); assert (b.values>0).sum()>obs.sum(); print('CLI_OK')")
        rc2, out2 = sh([PY, "-c", chk, str(csv), str(cli_out)], tmp, env, 120)
        ok = rc2 == 0 and "CLI_OK" in out2; out += out2
    checks["cli_end_to_end"] = {"pass": bool(ok), "detail": out[-1500:]}

    checks["pristine_unit_tests"] = pristine_tests_per_file(HERE / "pristine" / "repo.tar.gz", tmp, env, "tests/*_test.py", workspace=ws, overlay=["tests", "examples"])
    finish(a.out, checks, metrics, tmp)


if __name__ == "__main__":
    main()
