#!/usr/bin/env bash
# Verify each adapter port: it must be alive, and it must forward to the model we think it does.
# In force-model mode every port answers to any model name, so a wrong port mapping silently runs the
# wrong variant and the results do not show it. The most expensive lesson of this project is a failure
# disguised as a capability difference; this check closes that path.
# usage: bash slurm/check_adapters.sh "8801=gpt-5.6-sol" "8802=gpt-5.6-luna" ...
set -uo pipefail
allok=1
for pair in "$@"; do
  port=${pair%%=*}; want=${pair#*=}
  h=$(curl -s --max-time 5 "http://127.0.0.1:$port/healthz")
  got=$(echo "$h" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("force_model"))' 2>/dev/null)
  if [ "$got" != "$want" ]; then
    echo "  ✗ port $port should be $want, got ${got:-no response}"; allok=0; continue
  fi
  # Timeout and max_tokens are overridable (defaults 90s / 300, as before). One simple kimi-k3 request takes
  # about two minutes and its reasoning tokens count against max_tokens: at 90s / 300 the probe was truncated,
  # came back empty, and a ready model was judged not ready.
  r=$(curl -s --max-time "${CHECK_TIMEOUT:-90}" -X POST "http://127.0.0.1:$port/v1/messages?beta=true" \
      -H 'content-type: application/json' -H 'anthropic-version: 2023-06-01' \
      -d '{"model":"claude-opus-4-8","max_tokens":'"${CHECK_MAX_TOKENS:-300}"',
        "tools":[{"name":"write_file","description":"w","input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}],
        "messages":[{"role":"user","content":"Call write_file with path=a.txt"}]}')
  if echo "$r" | python3 -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if any(b.get("type")=="tool_use" for b in d.get("content",[])) else 1)' 2>/dev/null; then
    echo "  ✓ port $port -> $want  (tool_use works)"
  else
    echo "  ✗ port $port -> $want  no tool_use: $(echo "$r"|head -c 140)"; allok=0
  fi
done
[ "$allok" = 1 ] || { echo "adapters not ready, refusing to start"; exit 1; }
echo "all adapters ready."
