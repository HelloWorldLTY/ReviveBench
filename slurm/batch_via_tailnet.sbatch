#!/bin/bash
#SBATCH --job-name=tailnet_batch
# day is usually full while week sits mostly idle (9 nodes with 437 free cores, plus one entirely idle node):
# list several partitions and let Slurm take the first available. Resubmitted to week, the job went PENDING -> RUNNING in 5 seconds.
# Nothing in this project needs a GPU (the agent calls an API; the verifiers run yosys / OCP / plain Python),
# so the queueing was never GPU scarcity, only congestion on a single CPU partition.
# Do not add bigmem: those are 2TB / 64-core machines whose QOS has a minimum memory floor, and this job
# asks for 64G, which is below it, so the whole sbatch fails with QOSMinMemory instead of
# skipping that partition. Measured.
#SBATCH --partition=week,day
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x_%j.out

# Guard: sbatch does not validate the script's own arguments, so with a missing spec file the job is still accepted
# and ends "successfully", leaving one grep error in the log and zero runs. That silent failure has already wasted one submission.
SPECFILE="$1"
if [ ! -f "$SPECFILE" ]; then
  echo "FATAL: spec file $SPECFILE does not exist, refusing to run empty" >&2
  exit 1
fi
#
# Runs a list of experiments on ONE compute node, with a single userspace tailscaled
# started inside the job, so every agent call goes through the Bedrock proxy on the
# tailnet box. Login-node daemons get reaped by cluster policy, hence this design.
#
# usage: sbatch slurm/batch_via_tailnet.sbatch <specfile> [parallel]
#   specfile: one "task cond model run_id max_turns" per line, '#' comments allowed
set -u
ROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
TS=${REVIVE_TAILSCALE_DIR:?set REVIVE_TAILSCALE_DIR to your tailscale install}
SPEC=$1
PAR=${2:-3}
cd "$ROOT"

SOCK=$TMPDIR/tsd.sock
STATE=$TMPDIR/tsd.state
cp -a "$HOME/.tailscale/tailscaled.state.compute" "$STATE"

echo "[$(date +%T)] starting tailscaled on $(hostname)"
$TS/tailscaled --tun=userspace-networking \
  --socks5-server=localhost:1055 \
  --outbound-http-proxy-listen=localhost:8055 \
  --state="$STATE" --socket="$SOCK" > "$TMPDIR/tailscaled.log" 2>&1 &
TSD_PID=$!
trap 'kill $TSD_PID 2>/dev/null' EXIT

for i in $(seq 1 30); do
  sleep 4
  if $TS/tailscale --socket="$SOCK" status 2>/dev/null | grep -q ${REVIVE_TAILNET_PEER:?set REVIVE_TAILNET_PEER to your tailnet peer name}; then break; fi
done
$TS/tailscale --socket="$SOCK" status 2>&1 | head -3

code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 -x http://localhost:8055 http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765/ || echo 000)
echo "[$(date +%T)] bedrock proxy reachable: $code"
if [ "$code" = "000" ]; then echo "FATAL: proxy unreachable from compute node"; exit 1; fi

export HTTP_PROXY=http://localhost:8055
export HTTPS_PROXY=http://localhost:8055
export NO_PROXY=localhost,127.0.0.1
export REVIVE_BEDROCK_URL=http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765   # direct over the in-job tunnel
export OMP_NUM_THREADS=4

run_one() {
  read -r task cond model rid turns <<< "$1"
  slug=$(echo "$model" | sed 's|us.anthropic.claude-||; s|\[1m\]||; s|-20251001-v1:0||; s|[^A-Za-z0-9._-]|-|g')
  echo "[$(date +%T)] START $task $cond $model $rid"
  python3 harness/run_task.py --task "$task" --condition "$cond" --model "$model" \
      --run-id "$rid" --max-turns "${turns:-80}" --agent-timeout 10800 \
      > "logs/inner_${task}_${cond}_${slug}_${rid}.log" 2>&1
  echo "[$(date +%T)] END   $task $cond $model $rid rc=$?"
}
export -f run_one

grep -vE '^\s*(#|$)' "$SPEC" | while IFS= read -r line; do echo "$line"; done \
  | xargs -I{} -P "$PAR" bash -c 'run_one "$@"' _ {}

echo "[$(date +%T)] batch complete"
python3 harness/aggregate.py > /dev/null
python3 harness/usage_report.py
