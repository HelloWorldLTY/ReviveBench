#!/bin/bash
#SBATCH --job-name=glm_batch
#SBATCH --partition=week,day
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x_%j.out
#
# glm-5.3-flash batch, straight to the provider's open platform with no tunnel. Measured facts:
#   * the OpenAI-compatible path is /api/paas/v4/chat/completions, authenticated with Authorization: Bearer;
#     the adapter sends both api-key and Bearer headers, so it needs no change.
#   * verified end to end: claude -p driving glm-5.3-flash through the adapter made real tool calls and wrote
#     the right file.
#   * WARNING it is a reasoning model and reasoning tokens count against the completion budget: at max_tokens=64
#     all 63 tokens went to reasoning_content and content came back empty. The max_tokens Claude Code sends
#     is large enough, but anyone lowering it should watch for this empty-turn failure mode.
#   * WARNING the platform returns no rate-limit headers and throttling appears only as 429. The adapter now
#     retries with exponential backoff (REVIVE_ADAPTER_RETRIES, default 5); without it one 429 files the run
#     as infra_error.
#   * the /api/coding/paas/v4 path belongs to a separate coding plan whose subscription had expired (1309);
#     unrelated to this batch.
#
# WARNING cost accounting: cost_usd is computed from the launch model's rate (claude-opus-4-8) and is
#   fictional for glm-5.3-flash. It must not be added to real Claude spend; the real cost sits with the provider.
#
# usage: sbatch slurm/batch_glm.sbatch slurm/spec_glm_full.txt [parallel]
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

KEYFILE=${REVIVE_GLM_KEYFILE:-$ROOT/.secrets/glm.key}
if [ ! -r "$KEYFILE" ]; then
  echo "FATAL: key file not readable: $KEYFILE" >&2
  exit 1
fi

GWBASE=${REVIVE_GLM_BASE:-https://open.bigmodel.cn/api/paas/v4}
UPSTREAM="$GWBASE/chat/completions"
MODEL=${REVIVE_GLM_MODEL:-glm-5.3-flash}
# Output-cap field: this provider honours max_tokens only. max_completion_tokens returns 200 and is silently
# ignored (measured: a cap of 2000 produced 59,942 tokens).
TOKEN_FIELD=${REVIVE_TOKEN_FIELD:-max_tokens}

# ---- guard 1: ask the endpoint for one real completion from $MODEL before starting.
# When this batch was first submitted (2026-09-12) the model was routed to a separate backend that was
# unreachable by TCP from the proxy side, and the gateway returned 502 "Backend host forward failed".
# Without this guard all 13 tasks would burn their full turn budget and be recorded as infra_error,
# producing empty results that look like runs -- the same family as defects #18/#28: it looks like a
# measurement and is not.
PF=$(mktemp)
CODE=$(curl -s -o "$PF" -w "%{http_code}" --max-time 120 --compressed -X POST "$UPSTREAM" \
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

# ---- guard 1.5: the output cap must be honoured, not merely accepted.
# Writing the cap into max_completion_tokens the gpt-5.6 way returned 200 while the field was ignored entirely,
# so every GLM run went uncapped, under different conditions from the Claude models: accepted is not honoured.
CAPF=$(mktemp)
# --compressed is required: the gateway returns a gzip body; without it the JSON parse fails and the guard
# rejects a healthy upstream as not honouring the cap (batch 2471905 was refused this way after preflight passed).
curl -s --compressed -o "$CAPF" --max-time 180 -X POST "$UPSTREAM" \
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

ADPORT=${REVIVE_GLM_PORT:-8831}
python3 "$ROOT/harness/anthropic_openai_adapter.py" --port "$ADPORT" \
    --upstream "$UPSTREAM" --key-file "$KEYFILE" --force-model "$MODEL" --token-field "$TOKEN_FIELD" --debug \
    > "logs/adapter_${MODEL}_${SLURM_JOB_ID:-local}.log" 2>&1 &
ADPID=$!
trap 'kill $ADPID 2>/dev/null' EXIT
sleep 5

# ---- guard 2: confirm the process on the port really is this model's adapter, not one left from another batch.
# --force-model is process-wide, so a crossed port files a whole batch under the wrong model name, undetectably.
if ! bash "$ROOT/slurm/check_adapters.sh" "$ADPORT=$MODEL"; then
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
# Claude Code's per-request timeout raised to one hour. Note: this is not the fix -- the failures took almost
# exactly as long before and after, and "Request timed out" still happened in the main batch and the m2 re-runs.
# The cause is that glm-5.3-flash reasons for a very long time on some contexts (a streaming trace shows 75,085
# reasoning tokens streaming for 803s) while the old adapter sent no bytes until the upstream answered.
# Fixed in the adapter (H._stream sends message_start first, then a ping every 15s while waiting); live from m3.
# The variable is kept: it changes nothing the model can see, and is harmless.
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

run_one() {
  read -r task cond model rid turns <<< "$1"
  slug=$(echo "$model" | sed 's|[^A-Za-z0-9._-]|-|g')
  echo "[$(date +%T)] START $task $cond $model $rid"
  python3 harness/run_task.py --task "$task" --condition "$cond" --model "$model" \
      --run-id "$rid" --max-turns "${turns:-150}" --agent-timeout 10800 \
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
