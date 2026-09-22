#!/bin/bash
#SBATCH --job-name=gateway_batch
# Partition choice follows the tailnet batch: day is usually full while week is mostly idle, so list several
# and let Slurm take the first available.
# Do not add bigmem: its QOS has a minimum memory floor and this job asks for 64G, which is below it, so the
# whole sbatch fails with QOSMinMemory instead of skipping that partition. Measured.
#SBATCH --partition=week,day
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x_%j.out
#
# How this differs from batch_via_tailnet.sbatch, and why it can be simpler:
#   * no userspace tailscaled and no HTTP_PROXY: compute nodes were measured to reach the tunnel directly
#     (job 2452556 got HTTP 200), so the in-job tunnel is unnecessary.
#   * no Bedrock: REVIVE_USE_BEDROCK=0 makes run_task.py skip ~/.tailscale/bedrock_proxy.json.
#   * ANTHROPIC_BASE_URL points at the adapter inside this job, not the gateway's Anthropic side --
#     that side knows only its claude-* deployments, where gpt-5.6-* is an unknown_model.
#   * the key is read from a 0600 file and never written into the script or the log.
#
# usage: sbatch slurm/batch_via_gateway.sbatch <specfile> [parallel]
#   specfile: one "task cond model run_id max_turns" per line; '#' comments allowed
set -u
ROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}

# Guard: sbatch does not validate the script's own arguments, so with a missing spec file the job is still
# accepted and ends "successfully", leaving one grep error in the log and zero runs. That silent failure has
# already wasted one submission.
SPECFILE="$1"
if [ ! -f "$SPECFILE" ]; then
  echo "FATAL: spec file $SPECFILE does not exist, refusing to run empty" >&2
  exit 1
fi
SPEC=$1
PAR=${2:-3}
cd "$ROOT"

KEYFILE=${REVIVE_GW_KEYFILE:-$ROOT/.secrets/ngrok_gw.key}
if [ ! -r "$KEYFILE" ]; then
  echo "FATAL: key file not readable: $KEYFILE" >&2
  exit 1
fi

export REVIVE_USE_BEDROCK=0
unset CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_SKIP_BEDROCK_AUTH ANTHROPIC_BEDROCK_BASE_URL \
      ANTHROPIC_CUSTOM_HEADERS ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL \
      ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL 2>/dev/null
# The gateway's /anthropic side knows only its claude-* deployments; gpt-5.6-* exists only in OpenAI form,
# and the tunnel is a pure forwarder (only /{path} and /healthz) with no registration endpoint,
# whose agent sits behind NAT and cannot be logged into. So the translation layer sits on our side:
# each job starts a standard-library-only adapter: Claude Code -> adapter -> gateway /openai.
UPSTREAM=${REVIVE_GW_OPENAI:-${REVIVE_GW_HOST:?set REVIVE_GW_HOST to your Anthropic-compatible gateway}/openai/v1/chat/completions}
# --force-model is process-wide, so each variant gets its own adapter on its own port.
declare -A ADPORT=( [gpt-5.6-sol]=8801 [gpt-5.6-luna]=8802 [gpt-5.6-terra]=8803 )
ADPIDS=""
for m in "${!ADPORT[@]}"; do
  python3 "$ROOT/harness/anthropic_openai_adapter.py" --port "${ADPORT[$m]}" \
      --upstream "$UPSTREAM" --key-file "$KEYFILE" --force-model "$m" --debug \
      > "logs/adapter_${m}_${SLURM_JOB_ID:-local}.log" 2>&1 &
  ADPIDS="$ADPIDS $!"
done
trap 'kill $ADPIDS 2>/dev/null' EXIT
sleep 5
PAIRS=""
for m in "${!ADPORT[@]}"; do PAIRS="$PAIRS ${ADPORT[$m]}=$m"; done
if ! bash "$ROOT/slurm/check_adapters.sh" $PAIRS; then
  echo "FATAL: adapters not ready or port mapping wrong, refusing to start" >&2
  exit 1
fi

# Claude Code validates --model client-side and rejects an unknown id outright,
# so launch it under a name it knows; the adapter forces the real model, while the accounting keeps the real name.
export REVIVE_CLAUDE_MODEL=claude-opus-4-8
export ANTHROPIC_API_KEY=dummy-local-adapter
export OMP_NUM_THREADS=4

echo "[$(date +%T)] node=$(hostname)"


run_one() {
  read -r task cond model rid turns <<< "$1"
  case "$model" in
    gpt-5.6-sol)   export ANTHROPIC_BASE_URL=http://127.0.0.1:8801 ;;
    gpt-5.6-luna)  export ANTHROPIC_BASE_URL=http://127.0.0.1:8802 ;;
    gpt-5.6-terra) export ANTHROPIC_BASE_URL=http://127.0.0.1:8803 ;;
    *) echo "FATAL: unknown model $model has no adapter port" >&2; return 1 ;;
  esac
  slug=$(echo "$model" | sed 's|us.anthropic.claude-||; s|\[1m\]||; s|-20251001-v1:0||; s|[^A-Za-z0-9._-]|-|g')
  echo "[$(date +%T)] START $task $cond $model $rid"
  python3 harness/run_task.py --task "$task" --condition "$cond" --model "$model" \
      --run-id "$rid" --max-turns "${turns:-80}" --agent-timeout 10800 \
      > "logs/inner_${task}_${cond}_${slug}_${rid}.log" 2>&1
  echo "[$(date +%T)] END   $task $cond $model $rid rc=$?"
}
export -f run_one
export REVIVE_CLAUDE_MODEL

grep -vE '^\s*(#|$)' "$SPEC" | while IFS= read -r line; do echo "$line"; done \
  | xargs -I{} -P "$PAR" bash -c 'run_one "$@"' _ {}

echo "[$(date +%T)] batch complete"
python3 harness/aggregate.py > /dev/null
python3 harness/usage_report.py
