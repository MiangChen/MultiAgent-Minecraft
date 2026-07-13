#!/bin/bash
# Batch conflict-reproduction trials — TRACE-ONLY (no video during data runs).
# Rendering happens later via replay.mjs + cameras (fully decoupled).
# Usage: bash experiments/scripts/run_trials.sh [N] [task_json] [task_id]
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
N=${1:-5}
TASK=${2:-experiments/tasks/pyramid_two_agents_scarce2_t720.json}
TID=${3:-pyramid_two_agents_scarce2_t720}
SUMMARY=experiments/out/trials_summary.txt
mkdir -p experiments/out
BLOCKED='["!activate","!attackPlayer","!clearChat","!clearFurnace","!collectBlocks","!consume","!craftable","!discard","!endConversation","!endGoal","!equip","!followPlayer","!getBlueprint","!getBlueprintLevel","!goToBed","!help","!modes","!moveAway","!putInChest","!restart","!searchForBlock","!searchForEntity","!setMode","!stay","!stfu","!stop","!takeFromChest","!viewChest","!craftRecipe","!smeltItem"]'

for i in $(seq 1 "$N"); do
  TRIAL=experiments/out/trial_$i
  TRACE=$TRIAL/trace
  mkdir -p "$TRACE"
  echo "[trials] ===== trial $i/$N start $(date +%H:%M:%S) ====="

  node experiments/scripts/clear_site.mjs >/dev/null 2>&1
  sleep 2
  rm -rf bots/andy/trace.jsonl bots/bob/trace.jsonl bots/andy/logs bots/bob/logs

  # world-truth observer (no rendering)
  node experiments/scripts/observer.mjs --out "$TRACE" >"$TRIAL/observer.log" 2>&1 &
  OBSPID=$!
  sleep 4

  START_EPOCH=$(date +%s%3N)
  SETTINGS_JSON="{\"port\":55916,\"auto_open_ui\":false,\"profiles\":[\"./task_andy.json\",\"./task_bob.json\"],\"load_memory\":false,\"trace\":true,\"log_all_prompts\":true,\"blocked_actions\":$BLOCKED}" \
    timeout 1100 node main.js --task_path "$TASK" --task_id "$TID" >"$TRIAL/run.log" 2>&1 &
  RUNPID=$!
  python3 experiments/scripts/score_watcher.py "$TRIAL/run.log" "$TRACE/scores.tsv" >/dev/null 2>&1 &
  WPID=$!

  wait "$RUNPID"
  kill "$OBSPID" "$WPID" 2>/dev/null
  sleep 3

  # archive agent-side traces + LLM prompt logs
  for a in andy bob; do
    mv "bots/$a/trace.jsonl" "$TRACE/$a.trace.jsonl" 2>/dev/null
    mkdir -p "$TRACE/prompts/$a" && mv bots/$a/logs/* "$TRACE/prompts/$a/" 2>/dev/null
  done
  python3 - "$TRACE" "$TID" "$START_EPOCH" <<'EOF'
import json, sys, os
trace, tid, start = sys.argv[1], sys.argv[2], int(sys.argv[3])
json.dump({
  "task_id": tid, "start_epoch_ms": start, "agents": ["andy", "bob"],
  "world": "superflat y=-60 surface, site cleared at start",
  "clear_region": [-62, -60, 4, -49, -54, 17],
  "blueprint_region": [-60, -60, 6, -51, -56, 15],
}, open(os.path.join(trace, "meta.json"), "w"), indent=2)
EOF

  REALDROPS=$(python3 - "$TRACE/scores.tsv" <<'EOF'
import sys
sys.path.insert(0, 'experiments/scripts')
from detect_drops import parse_tsv, find_drops
try:
    drops = [d for d in find_drops(parse_tsv(sys.argv[1])) if d['from'] > 10]
    print(len(drops))
except Exception:
    print(-1)
EOF
)
  SIZE=$(du -sh "$TRACE" | cut -f1)
  RESULT=$(python3 experiments/scripts/detect_drops.py --tsv "$TRACE/scores.tsv" 2>/dev/null | head -1)
  echo "trial_$i $RESULT real_drops=$REALDROPS trace_size=$SIZE" >>"$SUMMARY"
  echo "[trials] trial $i done: $RESULT real_drops=$REALDROPS trace_size=$SIZE"
done
echo "[trials] ALL DONE"
