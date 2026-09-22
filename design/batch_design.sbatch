#!/bin/bash
#SBATCH --job-name=design_batch
#SBATCH --partition=day
#SBATCH --cpus-per-task=12
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x_%j.out
#
# Design-on-demand batch: each line of the spec is "<jobname> <model> <max_turns>".
# Starts its own userspace tailscaled so agent calls go through the tailnet Bedrock proxy.
set -u
ROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
TS=${REVIVE_TAILSCALE_DIR:?set REVIVE_TAILSCALE_DIR to your tailscale install}
SPEC=$1
PAR=${2:-3}
cd "$ROOT"

SOCK=$TMPDIR/tsd.sock
STATE=$TMPDIR/tsd.state
cp -a "$HOME/.tailscale/tailscaled.state.compute" "$STATE"
$TS/tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
  --outbound-http-proxy-listen=localhost:8055 \
  --state="$STATE" --socket="$SOCK" > "$TMPDIR/tailscaled.log" 2>&1 &
TSD_PID=$!
trap 'kill $TSD_PID 2>/dev/null' EXIT
for i in $(seq 1 30); do
  sleep 4
  $TS/tailscale --socket="$SOCK" status 2>/dev/null | grep -q ${REVIVE_TAILNET_PEER:?set REVIVE_TAILNET_PEER to your tailnet peer name} && break
done
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 -x http://localhost:8055 http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765/ || echo 000)
echo "[$(date +%T)] proxy: $code on $(hostname)"
[ "$code" = "000" ] && { echo FATAL; exit 1; }

export HTTP_PROXY=http://localhost:8055 HTTPS_PROXY=http://localhost:8055 NO_PROXY=localhost,127.0.0.1
export REVIVE_BEDROCK_URL=http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765

run_job() {
  read -r job model turns <<< "$1"
  echo "[$(date +%T)] START $job $model"
  python3 design/run_design.py --job "design/jobs/$job" --model "$model" --max-turns "${turns:-60}" \
      > "logs/design_${job}.log" 2>&1
  echo "[$(date +%T)] END   $job rc=$?"
  grep -h "RESULT" "logs/design_${job}.log" 2>/dev/null | tail -1
}
export -f run_job

grep -vE '^\s*(#|$)' "$SPEC" | xargs -I{} -P "$PAR" bash -c 'run_job "$@"' _ {}
echo "[$(date +%T)] design batch complete"
