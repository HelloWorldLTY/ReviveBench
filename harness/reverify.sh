#!/usr/bin/env bash
# Re-score a finished run with the CURRENT hidden verifier, in the same environment run_task.py used.
#
# Why this exists: verify.py launches the candidate's entrypoint as a subprocess, so the entrypoint
# inherits PATH. run_task.py puts the per-run venv on PATH, and agents legitimately rely on that
# (one wrote `exec python ...`, and this cluster has only python3 outside the venv). Re-scoring by
# hand with `./venv/bin/python verify.py` therefore fails every design with "python: not found" and
# looks exactly like a total agent failure. That cost a full debug round once — don't repeat it.
#
# usage: reverify.sh <run_dir> [out.json]        # default out: <run_dir>/verify_reverify.json
#        reverify.sh <run_dir> --in-place        # overwrite verify_post.json, keeping a backup
set -euo pipefail

RUN=$(cd "$1" && pwd)
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TASK=$(basename "$(dirname "$RUN")")
VERIFY="$ROOT/tasks/$TASK/hidden/verify.py"

[ -x "$RUN/venv/bin/python" ] || { echo "no per-run venv at $RUN/venv" >&2; exit 1; }
[ -f "$VERIFY" ] || { echo "no verifier at $VERIFY" >&2; exit 1; }

OUT=${2:-$RUN/verify_reverify.json}
INPLACE=0
if [ "${2:-}" = "--in-place" ]; then
  INPLACE=1
  OUT=$RUN/verify_post.json
  cp -n "$RUN/verify_post.json" "$RUN/verify_post.bak.json" 2>/dev/null || true
fi

cd "$RUN"
PATH="$RUN/venv/bin:$PATH" ./venv/bin/python "$VERIFY" \
  --workspace "$RUN/workspace" --out "$OUT"

if [ "$INPLACE" = 1 ]; then
  echo "(previous verify_post.json kept as verify_post.bak.json)"
  # aggregate.py collects runs/*/*/results.json and reads post_pass/post_checks from THERE, not from
  # verify_post.json. Re-scoring in place without this write-back leaves results.json carrying the
  # old verdict, so the next aggregate silently reports the pre-fix scores as if nothing had been
  # fixed. That is exactly how a corrected scada_dcs (3 models at 6/6) came back out of the
  # aggregate as 0/4 and nearly went into the report that way.
  "$RUN/venv/bin/python" - "$RUN" <<'PY'
import json, pathlib, sys
run = pathlib.Path(sys.argv[1])
res, post = run / "results.json", run / "verify_post.json"
if res.exists() and post.exists():
    d = json.loads(res.read_text())
    v = json.loads(post.read_text())
    before = d.get("post_pass")
    d["post_pass"] = bool(v.get("pass"))
    d["post_checks"] = {k: bool(c.get("pass")) for k, c in v.get("checks", {}).items()}
    d["post_metrics"] = v.get("metrics", d.get("post_metrics"))
    res.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    print(f"results.json updated: post_pass {before} -> {d['post_pass']} ({v.get('score')})")
PY
fi
