#!/bin/bash
# Batch conflict-reproduction trials — TRACE-ONLY (no video during data runs).
# Hardened for long unattended batches: server health check + auto-restart,
# terrain reset between trials, run.log gzip, cheat-contamination flag.
# Usage: bash experiments/scripts/run_trials.sh [N] [task_json] [task_id] [start_index]
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
N=${1:-5}
TASK=${2:-experiments/tasks/pyramid_two_agents_scarce2_t720.json}
TID=${3:-pyramid_two_agents_scarce2_t720}
START=${4:-1}
SUMMARY=experiments/out/trials_summary.txt
SERVER_DIR=/home/ubuntu/mc/mindcraft-server
SERVER_JAR=/home/ubuntu/mc/server/paper-1.20.4-499.jar
mkdir -p experiments/out
BLOCKED='["!activate","!attackPlayer","!clearChat","!clearFurnace","!collectBlocks","!consume","!craftable","!discard","!endConversation","!endGoal","!equip","!followPlayer","!getBlueprint","!getBlueprintLevel","!goToBed","!help","!modes","!moveAway","!putInChest","!restart","!searchForBlock","!searchForEntity","!setMode","!stay","!stfu","!stop","!takeFromChest","!viewChest","!craftRecipe","!smeltItem"]'

ensure_server() {
  if ! ss -tln 2>/dev/null | grep -q ':55916'; then
    echo "[trials] server down — restarting"
    (cd "$SERVER_DIR" && . /home/ubuntu/opt/javaenv.sh && nohup java -Xmx4G -Xms1G -jar "$SERVER_JAR" --nogui > "$SERVER_DIR/console.log" 2>&1 &)
    for _ in $(seq 1 30); do ss -tln 2>/dev/null | grep -q ':55916' && break; sleep 4; done
    sleep 5
  fi
}

for i in $(seq "$START" $((START + N - 1))); do
  TRIAL=experiments/out/trial_$(printf '%03d' "$i")
  TRACE=$TRIAL/trace
  mkdir -p "$TRACE"
  echo "[trials] ===== trial $i start $(date +%H:%M:%S) ====="
  ensure_server

  timeout 120 node experiments/scripts/clear_site.mjs >/dev/null 2>&1
  sleep 2
  rm -rf bots/andy/trace.jsonl bots/bob/trace.jsonl bots/andy/logs bots/bob/logs

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

  for a in andy bob; do
    mv "bots/$a/trace.jsonl" "$TRACE/$a.trace.jsonl" 2>/dev/null
    mkdir -p "$TRACE/prompts/$a" && mv bots/$a/logs/* "$TRACE/prompts/$a/" 2>/dev/null
  done
  python3 - "$TRACE" "$TID" "$START_EPOCH" <<'EOF'
import json, sys, os
trace, tid, start = sys.argv[1], sys.argv[2], int(sys.argv[3])
json.dump({
  "task_id": tid, "start_epoch_ms": start, "agents": ["andy", "bob"],
  "world": "superflat y=-60 surface, arena terrain reset at start",
  "clear_region": [-62, -60, 4, -49, -54, 17],
  "blueprint_region": [-60, -60, 6, -51, -56, 15],
}, open(os.path.join(trace, "meta.json"), "w"), indent=2)
EOF

  REALDROPS=$(python3 - "$TRACE/scores.tsv" <<'EOF'
import sys
sys.path.insert(0, 'experiments/scripts')
from detect_drops import parse_tsv, find_drops
try:
    print(len([d for d in find_drops(parse_tsv(sys.argv[1])) if d['from'] > 10]))
except Exception:
    print(-1)
EOF
)
  # ground-truth conflict metric: structure blocks physically removed (observer stream)
  TRUTH=$(python3 - "$TRACE/world_events.jsonl" <<'EOF'
import json, sys
STRUCT = {'stone_bricks','stone','gold_block','quartz_block','quartz_pillar','polished_andesite','polished_diorite','polished_granite','glowstone'}
n = 0
try:
    for l in open(sys.argv[1]):
        e = json.loads(l)
        if e.get('type') == 'block' and e.get('to') == 'air' and e.get('from', '').split('[')[0] in STRUCT:
            n += 1
except Exception:
    n = -1
print(n)
EOF
)
  CHEAT=$(grep -ac "/give" "$TRIAL/run.log" 2>/dev/null | head -1)
  BOTHSPAWNED=$( (grep -q "andy spawned" "$TRIAL/run.log" && grep -q "bob spawned" "$TRIAL/run.log") && echo 1 || echo 0)
  RESULT=$(python3 experiments/scripts/detect_drops.py --tsv "$TRACE/scores.tsv" 2>/dev/null | head -1)
  SIZE=$(du -sh "$TRACE" | cut -f1)
  gzip -f "$TRIAL/run.log" 2>/dev/null
  echo "trial_$(printf '%03d' "$i") $RESULT real_drops=$REALDROPS truth_removals=$TRUTH cheat_give=$CHEAT both_spawned=$BOTHSPAWNED trace_size=$SIZE" >>"$SUMMARY"
  echo "[trials] trial $i done: $RESULT real_drops=$REALDROPS truth_removals=$TRUTH cheat_give=$CHEAT both_spawned=$BOTHSPAWNED"
done
echo "[trials] ALL DONE"
