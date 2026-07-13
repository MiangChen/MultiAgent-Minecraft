#!/bin/bash
# Point all agent profiles at your OpenAI-compatible gateway.
# Usage: bash experiments/scripts/set_gateway.sh http://your-gateway:8080/v1
set -eu
URL=$1
cd "$(dirname "$0")/../.."
for f in andy.json bob.json candy.json commander.json feedback.json task_andy.json task_bob.json task_candy.json; do
  python3 - "$f" "$URL" <<'PY'
import json, sys
p, url = sys.argv[1], sys.argv[2]
d = json.load(open(p))
if isinstance(d.get('model'), dict) and 'url' in d['model']:
    d['model']['url'] = url
json.dump(d, open(p, 'w'), indent=4, ensure_ascii=False)
PY
done
echo "gateway set to $URL"
