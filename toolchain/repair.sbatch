#!/bin/bash
#SBATCH --job-name=tc_repair
#SBATCH --partition=day
#SBATCH --cpus-per-task=12
#SBATCH --mem=48G
#SBATCH --time=10:00:00
#SBATCH --output=logs/%x_%j.out
set -u
ROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}; TS=${REVIVE_TAILSCALE_DIR:?set REVIVE_TAILSCALE_DIR to your tailscale install}
cd "$ROOT"
SOCK=$TMPDIR/tsd.sock; cp -a "$HOME/.tailscale/tailscaled.state.compute" "$TMPDIR/tsd.state"
$TS/tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
  --outbound-http-proxy-listen=localhost:8055 --state="$TMPDIR/tsd.state" --socket="$SOCK" > "$TMPDIR/tsd.log" 2>&1 &
TSD=$!; trap 'kill $TSD 2>/dev/null' EXIT
for i in $(seq 1 30); do sleep 4; $TS/tailscale --socket="$SOCK" status 2>/dev/null | grep -q ${REVIVE_TAILNET_PEER:?set REVIVE_TAILNET_PEER to your tailnet peer name} && break; done
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 -x http://localhost:8055 http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765/ || echo 000)
echo "[$(date +%T)] proxy $code"; [ "$code" = "000" ] && exit 1
export HTTP_PROXY=http://localhost:8055 HTTPS_PROXY=http://localhost:8055 NO_PROXY=localhost,127.0.0.1
export REVIVE_BEDROCK_URL=http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765
python3 toolchain/run_repair.py --run "$1" --model "${2:-us.anthropic.claude-fable-5-1[1m]}" --max-turns "${3:-80}"
