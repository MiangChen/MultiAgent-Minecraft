#!/bin/bash
# Batch conflict-reproduction trials.
# Usage: bash experiments/scripts/run_trials.sh [N]
# Each trial: clear site -> god cam + 2-agent scarce task (720s timeout) -> archive + detect drops.
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
N=${1:-5}
TASK=experiments/tasks/pyramid_two_agents_scarce2_t720.json
TID=pyramid_two_agents_scarce2_t720
SUMMARY=experiments/out/trials_summary.txt
mkdir -p experiments/out
BLOCKED='["!activate","!attackPlayer","!clearChat","!clearFurnace","!collectBlocks","!consume","!craftable","!discard","!endConversation","!endGoal","!equip","!followPlayer","!getBlueprint","!getBlueprintLevel","!goToBed","!help","!modes","!moveAway","!putInChest","!restart","!searchForBlock","!searchForEntity","!setMode","!stay","!stfu","!stop","!takeFromChest","!viewChest","!craftRecipe","!smeltItem"]'

for i in $(seq 1 "$N"); do
  TRIAL=experiments/out/trial_$i
  mkdir -p "$TRIAL"
  echo "[trials] ===== trial $i/$N start $(date +%H:%M:%S) ====="

  node experiments/scripts/clear_site.mjs >/dev/null 2>&1
  sleep 2
  rm -rf bots/andy/videos bots/bob/videos experiments/out/god

  node experiments/scripts/god_camera.mjs --out experiments/out >"$TRIAL/god.log" 2>&1 &
  GODPID=$!
  sleep 6

  SETTINGS_JSON="{\"port\":55916,\"auto_open_ui\":false,\"profiles\":[\"./task_andy.json\",\"./task_bob.json\"],\"load_memory\":false,\"record_bot_video\":true,\"video_fps\":12,\"video_resolution\":[854,480],\"blocked_actions\":$BLOCKED}" \
    timeout 1100 node main.js --task_path "$TASK" --task_id "$TID" >"$TRIAL/run.log" 2>&1 &
  RUNPID=$!
  python3 experiments/scripts/score_watcher.py "$TRIAL/run.log" "$TRIAL/scores.tsv" >/dev/null 2>&1 &
  WPID=$!

  wait "$RUNPID"
  kill "$GODPID" "$WPID" 2>/dev/null
  sleep 3

  for a in andy bob; do
    mkdir -p "$TRIAL/$a"
    mv "bots/$a/videos" "$TRIAL/$a/videos" 2>/dev/null
  done
  mv experiments/out/god "$TRIAL/god" 2>/dev/null

  RESULT=$(python3 experiments/scripts/detect_drops.py --tsv "$TRIAL/scores.tsv" 2>/dev/null | head -1)
  REAL=$(python3 experiments/scripts/detect_drops.py --tsv "$TRIAL/scores.tsv" 2>/dev/null | grep -c "DROP.*from" || true)
  REALDROPS=$(python3 - "$TRIAL/scores.tsv" <<'EOF'
import sys, os
sys.path.insert(0, 'experiments/scripts')
from detect_drops import parse_tsv, find_drops
drops = [d for d in find_drops(parse_tsv(sys.argv[1])) if d['from'] > 10]
print(len(drops))
EOF
)
  echo "trial_$i $RESULT real_drops=$REALDROPS" >>"$SUMMARY"
  echo "[trials] trial $i done: $RESULT real_drops=$REALDROPS"
done
echo "[trials] ALL DONE"
cat "$SUMMARY"
