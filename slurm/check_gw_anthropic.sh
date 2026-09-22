#!/usr/bin/env bash
# Check whether the gateway's Anthropic side can serve gpt-5.6-sol / luna / terra.
#
# Why not a simple ping: the harness agent is Claude Code, which speaks only the Anthropic Messages
# protocol and, in -p mode, only streams. Returning one sentence is nowhere near enough; all three must hold:
#   1) /anthropic/v1/messages knows this model id
#   2) tools are supported and tool_use blocks are emitted (otherwise the agent cannot write a file and all
#      13 tasks come back empty)
#   3) stream:true works, emitting message_start / content_block_* / message_delta / message_stop in order
# Miss any one and the results look like a capability failure of the model -- the trap this project keeps hitting.
#
# usage: bash slurm/check_gw_anthropic.sh
set -uo pipefail
B=${REVIVE_GW_URL:-${REVIVE_GW_HOST:?set REVIVE_GW_HOST to your Anthropic-compatible gateway}/anthropic}
KF=${REVIVE_GW_KEYFILE:-${REVIVE_ROOT:-.}/.secrets/ngrok_gw.key}
K=$(cat "$KF")
MODELS=${*:-"gpt-5.6-sol gpt-5.6-luna gpt-5.6-terra"}

hdr=(-H "x-api-key: $K" -H "anthropic-version: 2023-06-01" -H "content-type: application/json")
allok=1

for m in $MODELS; do
  echo "===== $m ====="

  # 1) basic reachability
  r=$(curl -s --max-time 60 -X POST "$B/v1/messages" "${hdr[@]}" \
      -d "{\"model\":\"$m\",\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"say OK\"}]}")
  # Parse JSON instead of grepping: the adapter emits '"type": "message"' (json.dumps default separators,
  # with a space) while the gateway emits the compact '"type":"message"'. The old pattern matched only the
  # latter and failed a perfectly healthy adapter. A false negative in the check is as fatal as a real failure
  # in what it checks, so this must not depend on whitespace.
  if echo "$r" | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get("type")=="message" else 1)' 2>/dev/null; then
    echo "  [1/3] basic call   ✓  backend model=$(echo "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("model"))' 2>/dev/null)"
  else
    echo "  [1/3] basic call   ✗  $(echo "$r" | head -c 160)"
    allok=0; echo; continue
  fi

  # 2) tool calls: a tool_use block must actually be emitted
  r=$(curl -s --max-time 90 -X POST "$B/v1/messages" "${hdr[@]}" -d "{
        \"model\":\"$m\",\"max_tokens\":300,
        \"tools\":[{\"name\":\"write_file\",\"description\":\"Write text to a file\",
          \"input_schema\":{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"},\"content\":{\"type\":\"string\"}},\"required\":[\"path\",\"content\"]}}],
        \"messages\":[{\"role\":\"user\",\"content\":\"Use the write_file tool to create hello.txt containing OK. Call the tool.\"}]}")
  if echo "$r" | python3 -c "
import sys,json
d=json.load(sys.stdin)
blocks=[b.get('type') for b in d.get('content',[])]
sys.exit(0 if 'tool_use' in blocks else 1)" 2>/dev/null; then
    echo "  [2/3] tool_use   ✓  stop_reason=$(echo "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("stop_reason"))' 2>/dev/null)"
  else
    echo "  [2/3] tool_use   ✗  no tool_use block -> $(echo "$r" | head -c 160)"
    allok=0
  fi

  # 3) the full set of streaming events
  ev=$(curl -s --max-time 60 -N -X POST "$B/v1/messages" "${hdr[@]}" \
       -d "{\"model\":\"$m\",\"max_tokens\":32,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"count to three\"}]}" \
       | grep -o '^event: .*' | sed 's/event: //' | sort -u | tr '\n' ' ')
  miss=""
  for need in message_start content_block_start content_block_delta content_block_stop message_delta message_stop; do
    echo "$ev" | grep -qw "$need" || miss="$miss $need"
  done
  if [ -z "$miss" ]; then
    echo "  [3/3] stream events ✓  $ev"
  else
    echo "  [3/3] stream events ✗  missing:$miss   got: $ev"
    allok=0
  fi
  echo
done

if [ "$allok" = 1 ]; then
  echo "all checks passed: Claude Code can be driven over the Anthropic protocol; run the pilot."
else
  echo "not ready: fix everything marked ✗ before submitting experiments, or failures will masquerade as model capability."
  exit 1
fi
