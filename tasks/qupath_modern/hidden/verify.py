#!/usr/bin/env python3
"""Hidden verifier for qupath_modern: bytecode target, headless CLI cell detection vs the official 0.2.3 release."""
import argparse, json, pathlib, re, struct, sys, tempfile, zipfile, glob, os
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import sh, make_env, finish
TASK = json.loads((HERE.parent / "task.json").read_text())
REF = json.loads((HERE / "oracle_reference.json").read_text()) if (HERE / "oracle_reference.json").exists() else None


def class_major_version(ws):
    """Max class-file major version found in the built qupath-core jar(s)."""
    best, src = 0, None
    for jar in glob.glob(str(ws / "**" / "qupath-core*.jar"), recursive=True):
        if "sources" in jar or "javadoc" in jar: continue
        try:
            with zipfile.ZipFile(jar) as z:
                for n in z.namelist():
                    if n.endswith(".class") and "qupath/lib" in n:
                        b = z.read(n)[:8]; major = struct.unpack(">H", b[6:8])[0]
                        if major > best: best, src = major, jar
                        break
        except Exception: pass
    return best, src


def parse_result(out):
    m = re.search(r"QP_RESULT (.*)", out)
    if not m: return None
    d = {}
    for kv in m.group(1).split():
        k, v = kv.split("="); d[k] = float(v)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    ap.add_argument("--launcher", default=None, help="oracle calibration: explicit QuPath launcher")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws); env.pop("PYTHONPATH", None)
    checks, metrics = {}, {}

    if not a.launcher:
        major, jar = class_major_version(ws); metrics["class_major_version"] = major; metrics["core_jar"] = jar
        checks["built_with_modern_jdk"] = {"pass": major >= TASK["jdk_min_class_version"],
                                           "detail": f"qupath-core class major version {major} (need >= {TASK['jdk_min_class_version']}; 61=Java17, 65=Java21) from {jar}"}
        rc, out = sh(["bash", "-c", "grep -rl 'QuPath-0.2.3-Linux\\|releases/download' run_qupath.sh 2>/dev/null; ls run_qupath.sh"], ws, env, 60)
        checks["launcher_present"] = {"pass": rc == 0 and "run_qupath.sh" in out and "releases/download" not in out, "detail": out[-500:]}
        launcher = ["bash", str(ws / "run_qupath.sh")]
    else:
        launcher = [a.launcher]

    img = HERE / "data" / "CMU-1-Small-Region.svs"; script = HERE / "data" / "cell_detection.groovy"
    rc, out = sh(["xvfb-run", "-a", *launcher, "script", "--image", str(img), str(script)], tmp, env, 1800)
    res = parse_result(out); metrics["cell_detection"] = res
    if res is None:
        checks["headless_cell_detection"] = {"pass": False, "detail": out[-3000:]}
    elif REF:
        r = REF["cell_detection"]; bad = []
        if abs(res["n_cells"] - r["n_cells"]) > 0.02 * r["n_cells"]: bad.append("n_cells")
        if abs(res["mean_nucleus_area"] - r["mean_nucleus_area"]) > 0.03 * r["mean_nucleus_area"]: bad.append("mean_nucleus_area")
        if abs(res["mean_hema_od"] - r["mean_hema_od"]) > 0.03 * r["mean_hema_od"]: bad.append("mean_hema_od")
        if res["image_w"] != r["image_w"] or res["image_h"] != r["image_h"]: bad.append("image_dims")
        if abs(res["px_um"] - r["px_um"]) > 1e-3: bad.append("pixel_size")
        checks["headless_cell_detection"] = {"pass": not bad, "detail": f"got {res} ; oracle {r} ; mismatch {bad}"}
    else:
        checks["headless_cell_detection"] = {"pass": True, "detail": f"calibration: {res}"}

    if not a.launcher:
        rc, out = sh(["bash", "-c", "ls build/test-results/test/*.xml qupath-core/build/test-results/test/*.xml 2>/dev/null | wc -l; "
                      "grep -ho 'tests=\"[0-9]*\" skipped=\"[0-9]*\" failures=\"[0-9]*\" errors=\"[0-9]*\"' qupath-core/build/test-results/test/*.xml qupath-core-processing/build/test-results/test/*.xml 2>/dev/null | "
                      "awk -F'\"' '{t+=$2; s+=$4; f+=$6; e+=$8} END {print \"JUNIT tests=\"t\" skipped=\"s\" failures=\"f\" errors=\"e}'"], ws, env, 120)
        m = re.search(r"JUNIT tests=(\d+) skipped=(\d+) failures=(\d+) errors=(\d+)", out)
        ok = bool(m) and int(m.group(1)) > 50 and int(m.group(3)) == 0 and int(m.group(4)) == 0
        checks["core_unit_tests_reported"] = {"pass": ok, "detail": out[-800:], "informational": True}
    finish(a.out, checks, metrics, tmp)


if __name__ == "__main__":
    main()
