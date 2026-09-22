#!/bin/bash
#SBATCH --job-name=toolchain
#SBATCH --partition=day
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=23:00:00
#SBATCH --output=logs/%x_%j.out
#
# Builds the plcforge toolchain inside one compute-node job, with its own userspace tailscaled
# so the agent's model calls go through the tailnet Bedrock proxy.
#
# usage: sbatch toolchain/batch_toolchain.sbatch <specfile>
#   specfile lines: "<run_name> <model> <phase> <max_turns> [from_arch_run]"
set -u
ROOT=${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
TS=${REVIVE_TAILSCALE_DIR:?set REVIVE_TAILSCALE_DIR to your tailscale install}
SPEC=$1
cd "$ROOT"

SOCK=$TMPDIR/tsd.sock
cp -a "$HOME/.tailscale/tailscaled.state.compute" "$TMPDIR/tsd.state"
$TS/tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
  --outbound-http-proxy-listen=localhost:8055 \
  --state="$TMPDIR/tsd.state" --socket="$SOCK" > "$TMPDIR/tailscaled.log" 2>&1 &
TSD=$!
trap 'kill $TSD 2>/dev/null' EXIT
for i in $(seq 1 30); do sleep 4; $TS/tailscale --socket="$SOCK" status 2>/dev/null | grep -q ${REVIVE_TAILNET_PEER:?set REVIVE_TAILNET_PEER to your tailnet peer name} && break; done
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 -x http://localhost:8055 http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765/ || echo 000)
echo "[$(date +%T)] proxy $code on $(hostname)"
[ "$code" = "000" ] && { echo FATAL; exit 1; }

export HTTP_PROXY=http://localhost:8055 HTTPS_PROXY=http://localhost:8055 NO_PROXY=localhost,127.0.0.1
export REVIVE_BEDROCK_URL=http://${REVIVE_BEDROCK_HOST:?set REVIVE_BEDROCK_HOST to your Bedrock proxy host}:8765
export OMP_NUM_THREADS=4

grep -vE '^\s*(#|$)' "$SPEC" | while read -r name model phase turns from; do
  echo "[$(date +%T)] START $name $phase $model"
  extra=""
  [ -n "${from:-}" ] && extra="--from-arch $from"
  python3 toolchain/run_toolchain.py --run "$name" --model "$model" --phase "$phase" \
      --max-turns "$turns" $extra > "logs/toolchain_${name}_${phase}.log" 2>&1
  echo "[$(date +%T)] END   $name $phase rc=$?"
  tail -2 "logs/toolchain_${name}_${phase}.log"
done
echo "[$(date +%T)] toolchain batch complete"
