#!/bin/bash
#SBATCH --job-name=effort_ablation
#SBATCH --partition=week,day
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x_%j.out
#
# opus5 reasoning-effort ablation. Key differences from batch_via_gateway.sbatch:
#   * the model really is claude-opus-5, served by the gateway's /anthropic side, so no OpenAI adapter is needed.
#     cost_usd is therefore real and comparable with the other Claude models, unlike the fictional dollars
#     of the gpt-5.6 batch.
#   * but it must pass through a proxy that filters beta headers only: this gateway's upstream returns 400
#     for `advisor-tool-2026-03-01`, which Claude Code sends on every request, so without the filter
#     no claude -p call gets through at all (nothing to do with effort).
#     Note: dropping advisor-tool changes the tool set available to the model. That is a change to the
#     experimental conditions and must be disclosed in the report.
#
# How effort actually travels (measured, not assumed):
#   output_config = {"effort": "low|medium|high|xhigh|max"}
#   -- not a top-level effort field, and not thinking (the main query is always adaptive).
#   The five levels really are five distinct request signatures on the wire, so the five arms differ.
#
# usage: sbatch slurm/batch_effort_ablation.sbatch <specfile> [parallel]
set -u
ROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}

SPECFILE="$1"
if [ ! -f "$SPECFILE" ]; then
  echo "FATAL: spec file $SPECFILE does not exist, refusing to run empty" >&2
  exit 1
fi
SPEC=$1
PAR=${2:-3}
cd "$ROOT"

KEYFILE=${REVIVE_GW_KEYFILE:-$ROOT/.secrets/ngrok_gw.key}
[ -r "$KEYFILE" ] || { echo "FATAL: key file not readable: $KEYFILE" >&2; exit 1; }

# ---- guard 1: the harness must already honour REVIVE_EFFORT.
# Without it all five levels quietly run at the default and produce a perfect null result that measured nothing.
# Same family as defects #18 (the 0.9 tolerance) and #28 (full marks for copying the formula): it looks like
# a measurement and is not.
if ! grep -q "REVIVE_EFFORT" "$ROOT/harness/run_task.py"; then
  echo "FATAL: run_task.py does not honour REVIVE_EFFORT yet; all five levels would collapse into one, refusing to start" >&2
  exit 1
fi

export REVIVE_USE_BEDROCK=0
unset CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_SKIP_BEDROCK_AUTH ANTHROPIC_BEDROCK_BASE_URL \
      ANTHROPIC_CUSTOM_HEADERS ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL \
      ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_EFFORT 2>/dev/null

PORT=${REVIVE_PT_PORT:-8910}
PTLOG="logs/passthrough_${SLURM_JOB_ID:-local}.log"
python3 "$ROOT/harness/logging_passthrough.py" --port "$PORT" \
    --upstream ${REVIVE_GW_HOST:?set REVIVE_GW_HOST to your Anthropic-compatible gateway}/anthropic/v1/messages \
    --key-file "$KEYFILE" --drop-betas advisor-tool-2026-03-01 > "$PTLOG" 2>&1 &
PTPID=$!
trap 'kill $PTPID 2>/dev/null' EXIT
for i in $(seq 1 20); do sleep 1; curl -s --max-time 3 "http://127.0.0.1:$PORT/healthz" | grep -q ok && break; done
curl -s --max-time 3 "http://127.0.0.1:$PORT/healthz" | grep -q ok || {
  echo "FATAL: pass-through proxy did not start (see $PTLOG)" >&2; exit 1; }
echo "[$(date +%T)] proxy ready pid=$PTPID port=$PORT  node=$(hostname)"

export ANTHROPIC_BASE_URL=http://127.0.0.1:$PORT
export ANTHROPIC_API_KEY=dummy-local-passthrough
export OMP_NUM_THREADS=4

# ---- guard 2: confirm effort really reaches the wire, rather than being silently dropped.
# grep -c prints 0 AND exits 1 when nothing matches, so with `|| echo 0` you get two lines, "0\n0",
# then $((BEFORE+1)) is a syntax error, the tail offset is wrong, and the guard kills a healthy batch by
# concluding that effort was not transmitted.
# This is the third time this project has been bitten by that idiom (curl ... || echo 000 once gave "000000").
# Count with wc -l: it does not exit non-zero when nothing matches.
BEFORE=$(grep -c '^REQ' "$PTLOG" 2>/dev/null | head -1)
BEFORE=${BEFORE:-0}
( cd "$(mktemp -d)" && timeout 90 claude -p "Reply with DONE." --effort xhigh \
    --model claude-opus-5 --max-turns 1 --dangerously-skip-permissions </dev/null >/dev/null 2>&1 )
if ! tail -n +$((BEFORE+1)) "$PTLOG" | grep '^REQ' | grep -q '"effort": "xhigh"'; then
  echo "FATAL: the probe request shows no output_config.effort=xhigh; effort is not reaching the wire, refusing to start" >&2
  tail -3 "$PTLOG" >&2
  exit 1
fi
echo "[$(date +%T)] confirmed: effort reaches the wire (output_config.effort)"

run_one() {
  read -r task cond model rid turns <<< "$1"
  # run_id looks like eff-low / eff-max; the level is the arm
  # run_id looks like eff-low or eff2-low: strip the eff / eff2 prefix and keep the level.
  # A hardcoded ${rid#eff-} turns eff2-low into "2-low", which the validity check then rejects --
  # the same "guard blocks a healthy batch" problem, so get it right here.
  lvl=${rid##*-}
  case "$lvl" in
    low|medium|high|xhigh|max) : ;;
    *) echo "FATAL: run_id '$rid' contains no valid effort level (the CLI silently falls back on an invalid value)" >&2; return 1 ;;
  esac
  export REVIVE_EFFORT="$lvl"
  slug=$(echo "$model" | sed 's|[^A-Za-z0-9._-]|-|g')
  echo "[$(date +%T)] START $task $cond $model $rid effort=$lvl"
  python3 harness/run_task.py --task "$task" --condition "$cond" --model "$model" \
      --run-id "$rid" --max-turns "${turns:-180}" --agent-timeout 10800 \
      > "logs/inner_${task}_${cond}_${slug}_${rid}.log" 2>&1
  echo "[$(date +%T)] END   $task $cond $model $rid rc=$?"
}
export -f run_one

grep -vE '^\s*(#|$)' "$SPEC" | while IFS= read -r line; do echo "$line"; done \
  | xargs -I{} -P "$PAR" bash -c 'run_one "$@"' _ {}

echo "[$(date +%T)] batch complete"
echo "=== effort levels actually sent, per run (post-hoc check against a silent fallback) ==="
grep '^REQ' "$PTLOG" | grep -o '"effort": "[a-z]*"' | sort | uniq -c
python3 harness/aggregate.py > /dev/null
python3 harness/usage_report.py
