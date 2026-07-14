#!/bin/bash
# Probe the LLM gateway every 20 min; when quota is back, auto-resume batch C.
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
KEY=$(python3 -c "import json;print(json.load(open('keys.json'))['OPENAI_API_KEY'])")
URL=$(python3 -c "import json;print(json.load(open('task_andy.json'))['model']['url'])")

while true; do
  CODE=$(curl -s -o /tmp/quota_probe.json -w "%{http_code}" -m 30 "$URL/chat/completions" \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"hi"}],"max_completion_tokens":16}')
  if [ "$CODE" = "200" ]; then
    echo "[quota] gateway OK at $(date +%H:%M) — resuming batch C"
    setsid bash experiments/scripts/run_matrix.sh > experiments/out/matrix_runner3.log 2>&1 &
    echo "[quota] batch C resumed (matrix_runner3.log)"
    exit 0
  fi
  echo "[quota] $(date +%H:%M) gateway status $CODE — waiting"
  sleep 1200
done
