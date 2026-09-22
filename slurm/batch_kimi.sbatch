#!/bin/bash
#SBATCH --job-name=kimi_batch
#SBATCH --partition=week,day
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=20:00:00
#SBATCH --output=logs/%x_%j.out
#
# kimi-k3 batch. Same shape as batch_via_gateway.sbatch; only the gateway and the path differ:
#   * the gateway is a FastAPI catch-all proxy (`/{full_path}`, Server: uvicorn),
#     whose OpenAI-compatible path is /chat/completions, with no /v1 prefix.
#     /v1/chat/completions returns 404: a GET with a token shows it rewriting the path, and the upstream
#     answering 405, which is easily mistaken for the path existing. Measured.
#   * this gateway accepts both max_tokens and max_completion_tokens and passes tool_calls through correctly
#     (OpenAI form, with call_ ids), so anthropic_openai_adapter.py needs no change.
#   * /healthz reports routed_models and the upstream; look there first when debugging.
#
# WARNING cost accounting: as in the gpt-5.6 batch, cost_usd comes from the launch model's rate (claude-opus-4-8)
#   and is fictional for kimi-k3; it must not be added to real Claude spend.
#
# usage: sbatch slurm/batch_kimi.sbatch slurm/spec_kimi_full.txt [parallel]
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

KEYFILE=${REVIVE_KIMI_KEYFILE:-$ROOT/.secrets/pinggy_gw.key}
if [ ! -r "$KEYFILE" ]; then
  echo "FATAL: key file not readable: $KEYFILE" >&2
  exit 1
fi

GWBASE=${REVIVE_KIMI_BASE:-${REVIVE_KIMI_HOST:?set REVIVE_KIMI_HOST to your OpenAI-compatible gateway}}
UPSTREAM="$GWBASE/chat/completions"
MODEL=${REVIVE_KIMI_MODEL:-kimi-k3}
# Output-cap field: kimi-k3 honours both max_tokens and max_completion_tokens (measured: a cap of 16 gave 16
# tokens and finish=length);
# use max_tokens, matching the documented client usage. Guard 1.5 still measures it before starting.
TOKEN_FIELD=${REVIVE_TOKEN_FIELD:-max_tokens}
# One kimi request can be very slow (the SDK default of 600s is not enough; 3600s is), so the adapter's
# upstream read timeout is raised to match.
export REVIVE_UPSTREAM_TIMEOUT=${REVIVE_UPSTREAM_TIMEOUT:-3600}

# ---- guard 1: ask the gateway for one real kimi-k3 completion before starting.
# When this batch was first submitted (2026-09-12) the model was routed to a separate backend that was
# unreachable by TCP from the proxy side, and the gateway returned 502 "Backend host forward failed".
# Without this guard all 13 tasks would burn their full turn budget and be recorded as infra_error,
# producing empty results that look like runs -- the same family as defects #18/#28: it looks like a
# measurement and is not.
PF=$(mktemp)
# The preflight waits up to 900s: one simple kimi-k3 request takes about 37s even on a login node, and batch
# 2471810 failed with http=000 after 120s on a compute node, running none of the 13 tasks. The documented SDK
# timeout is 3600s. Same order of magnitude as the cap guard below (600s).
CODE=$(curl -s -o "$PF" -w "%{http_code}" --max-time 900 --compressed -X POST "$UPSTREAM" \
        -H "Authorization: Bearer $(cat "$KEYFILE")" -H "Content-Type: application/json" \
        -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":256}")
CONTENT=$(python3 -c "import json,sys;d=json.load(open('$PF'));print((d.get('choices') or [{}])[0].get('message',{}).get('content') or '')" 2>/dev/null)
# Checking for 200/choices is not enough: a reasoning model can spend the whole budget on reasoning_content
# and return empty content, and such a pass measures nothing. Require the preflight to retrieve real text.
if [ "$CODE" != "200" ] || [ -z "$CONTENT" ]; then
  echo "FATAL: $MODEL preflight failed http=$CODE, refusing to start. The endpoint returned:" >&2
  head -c 400 "$PF" >&2; echo >&2
  echo "  debug: curl -H \"Authorization: Bearer \$(cat $KEYFILE)\" $GWBASE/healthz" >&2
  echo "  if the response says 'Backend host forward failed', the backend for $MODEL is unreachable; resubmit once it recovers." >&2
  rm -f "$PF"; exit 1
fi
echo "[$(date +%T)] preflight ok: $MODEL is live ($(python3 -c "import json,sys;d=json.load(open('$PF'));print(repr(d['choices'][0]['message'].get('content'))[:60])")"
rm -f "$PF"

# ---- guard 1.5: the output cap must be honoured, not merely accepted (GLM silently ignored the field).
CAPF=$(mktemp)
# --compressed is required: the gateway returns a gzip body; without it the JSON parse fails and the guard
# rejects a healthy upstream as not honouring the cap (batch 2471905 was refused this way after preflight passed).
curl -s --compressed -o "$CAPF" --max-time 600 -X POST "$UPSTREAM" \
     -H "Authorization: Bearer $(cat "$KEYFILE")" -H "Content-Type: application/json" \
     -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a 600-word essay about rivers.\"}],\"$TOKEN_FIELD\":16}"
CAPOUT=$(python3 -c "import json;d=json.load(open('$CAPF'));print((d.get('usage') or {}).get('completion_tokens',''))" 2>/dev/null)
if [ -z "$CAPOUT" ] || [ "$CAPOUT" -gt 32 ]; then
  echo "FATAL: upstream did not honour $TOKEN_FIELD=16 (completion_tokens=${CAPOUT:-none}), refusing to start. Response:" >&2
  head -c 300 "$CAPF" >&2; echo >&2
  rm -f "$CAPF"; exit 1
fi
echo "[$(date +%T)] cap guard passed: $TOKEN_FIELD=16 -> completion_tokens=$CAPOUT"
rm -f "$CAPF"

export REVIVE_USE_BEDROCK=0
unset CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_SKIP_BEDROCK_AUTH ANTHROPIC_BEDROCK_BASE_URL \
      ANTHROPIC_CUSTOM_HEADERS ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL \
      ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL 2>/dev/null

ADPORT=${REVIVE_KIMI_PORT:-8821}
python3 "$ROOT/harness/anthropic_openai_adapter.py" --port "$ADPORT" \
    --upstream "$UPSTREAM" --key-file "$KEYFILE" --force-model "$MODEL" --token-field "$TOKEN_FIELD" --debug \
    > "logs/adapter_${MODEL}_${SLURM_JOB_ID:-local}.log" 2>&1 &
ADPID=$!
trap 'kill $ADPID 2>/dev/null' EXIT
sleep 5

# ---- guard 2: confirm the process on the port really is this model's adapter, not one left from another batch.
# --force-model is process-wide, so a crossed port files a whole batch under the wrong model name, undetectably.
# kimi-k3 is slow and its reasoning counts against the cap, so the adapter tool-call check is relaxed to 900s
# and max_tokens 2048 (a direct tool call succeeded in 24s).
if ! CHECK_TIMEOUT=900 CHECK_MAX_TOKENS=2048 bash "$ROOT/slurm/check_adapters.sh" "$ADPORT=$MODEL"; then
  echo "FATAL: adapter not ready, or force_model on port $ADPORT is not $MODEL, refusing to start" >&2
  exit 1
fi
TF=$(curl -s --max-time 5 "http://127.0.0.1:$ADPORT/healthz" | python3 -c "import json,sys;print(json.load(sys.stdin).get('token_field',''))" 2>/dev/null)
if [ "$TF" != "$TOKEN_FIELD" ]; then
  echo "FATAL: adapter token_field=${TF:-none} does not match the expected $TOKEN_FIELD (old adapter?), refusing to start" >&2
  exit 1
fi

# Claude Code validates --model client-side and reports unrecognized_model for anything outside its list,
# so launch it under a name it knows; the adapter forces the real model, and the accounting keeps the real name.
export REVIVE_CLAUDE_MODEL=claude-opus-4-8
export ANTHROPIC_API_KEY=dummy-local-adapter
export ANTHROPIC_BASE_URL=http://127.0.0.1:$ADPORT
export OMP_NUM_THREADS=4
# Same infrastructure conditions as batch_glm.sbatch (see its comments): a one-hour per-request timeout.
export API_TIMEOUT_MS=${API_TIMEOUT_MS:-3600000}
# Claude Code's stream-idle timeout. This is the actual fix (with the adapter keepalive). Measured against a
# local fake upstream emitting one event every 15s for 900s:
#   pings only, unset        -> gives up and resends at about 750s (matching ten "waited~765s" disconnects in the GLM m3 log);
#   pings only, 3600000      -> waits the full 900s, sends one request, completes normally;
#   content deltas, unset    -> also waits the full 900s, so only content deltas reset the timer, not pings.
# Also: CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS and API_TIMEOUT_MS do nothing when the upstream sends no bytes at
# all (resend at about 360s), but the adapter now emits message_start immediately, so that case cannot arise.
# This variable only changes how long Claude Code waits; it changes nothing the model can see.
export CLAUDE_STREAM_IDLE_TIMEOUT_MS=${CLAUDE_STREAM_IDLE_TIMEOUT_MS:-3600000}
echo "[$(date +%T)] node=$(hostname) adapter=$ADPORT -> $UPSTREAM ($MODEL)"

# Wall clock raised to 4 hours (asked on 2026-09-14 to relax the time limit for one more night). A single
# kimi-k3 request can exceed 120s on a compute node; 4 hours is the longest limit any batch script here uses
# (run_big / run_gpu use 14400s).
# The turn budget is unchanged, to stay comparable with the other models; the paper must disclose that kimi had
# a 4-hour wall clock while the GLM / GPT-5.6 batches had 3.
run_one() {
  read -r task cond model rid turns <<< "$1"
  slug=$(echo "$model" | sed 's|[^A-Za-z0-9._-]|-|g')
  echo "[$(date +%T)] START $task $cond $model $rid"
  python3 harness/run_task.py --task "$task" --condition "$cond" --model "$model" \
      --run-id "$rid" --max-turns "${turns:-150}" --agent-timeout ${REVIVE_AGENT_TIMEOUT:-14400} \
      > "logs/inner_${task}_${cond}_${slug}_${rid}.log" 2>&1
  echo "[$(date +%T)] END   $task $cond $model $rid rc=$?"
}
export -f run_one
export REVIVE_CLAUDE_MODEL ANTHROPIC_BASE_URL ANTHROPIC_API_KEY API_TIMEOUT_MS CLAUDE_STREAM_IDLE_TIMEOUT_MS

grep -vE '^\s*(#|$)' "$SPEC" | while IFS= read -r line; do echo "$line"; done \
  | xargs -I{} -P "$PAR" bash -c 'run_one "$@"' _ {}

echo "[$(date +%T)] batch complete"
python3 harness/aggregate.py > /dev/null
python3 harness/usage_report.py
