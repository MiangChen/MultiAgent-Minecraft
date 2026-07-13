#!/bin/bash
# Trace-only trial batch, matrix-aware. Natural-terrain edition:
# per-trial WORLD RESET from pristine template (server restart), watcher does
# staff duties, agents forced back to survival every trial.
# Usage:
#   run_trials.sh N TASK_JSON TASK_ID START_INDEX GROUP 'PROFILES_JSON' 'CENTER'
# Example:
#   run_trials.sh 20 experiments/tasks/matrix/pyr_2a_d22.json pyr_2a_d22 41 \
#     2a_d22 '["./task_andy.json","./task_bob.json"]' '-343.5,64,250.5'
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
N=${1:?}; TASK=${2:?}; TID=${3:?}; START=${4:?}; GROUP=${5:?}; PROFILES=${6:?}; CENTER=${7:?}
SUMMARY=experiments/out/trials_summary.txt
SERVER_DIR=/home/ubuntu/mc/mindcraft-server
SERVER_JAR=/home/ubuntu/mc/server/paper-1.20.4-499.jar
WORLD=arena_natural
mkdir -p experiments/out
BLOCKED='["!activate","!attackPlayer","!clearChat","!clearFurnace","!collectBlocks","!consume","!craftable","!discard","!endConversation","!endGoal","!equip","!followPlayer","!getBlueprint","!getBlueprintLevel","!goToBed","!help","!modes","!moveAway","!putInChest","!restart","!searchForBlock","!searchForEntity","!setMode","!stay","!stfu","!stop","!takeFromChest","!viewChest","!craftRecipe","!smeltItem"]'

server_pid() { pgrep -u "$(id -u)" -f "paper-1.20.4-499.jar --nogui" | head -1; }

stop_server() {
  local pid; pid=$(server_pid)
  [ -n "$pid" ] && { kill "$pid"; for _ in $(seq 1 20); do ps -p "$pid" >/dev/null || return 0; sleep 2; done; kill -9 "$pid"; sleep 2; }
  return 0
}

start_server() {
  ( cd "$SERVER_DIR" && . /home/ubuntu/opt/javaenv.sh && nohup java -Xmx4G -Xms1G -jar "$SERVER_JAR" --nogui > "$SERVER_DIR/console.log" 2>&1 & )
  for _ in $(seq 1 40); do grep -q "Done (" "$SERVER_DIR/console.log" 2>/dev/null && { sleep 2; return 0; }; sleep 3; done
  echo "[trials] SERVER START FAILED"; return 1
}

reset_world() {
  stop_server
  rm -rf "$SERVER_DIR/$WORLD"
  cp -r "$SERVER_DIR/${WORLD}_template" "$SERVER_DIR/$WORLD"
  start_server
}

for i in $(seq "$START" $((START + N - 1))); do
  TRIAL=experiments/out/trial_$(printf '%03d' "$i")
  TRACE=$TRIAL/trace
  mkdir -p "$TRACE"
  echo "[trials] ===== trial $i ($GROUP) start $(date +%H:%M:%S) ====="

  reset_world || { echo "[trials] trial $i aborted: server" ; continue; }
  # staff pass: force agent gamemodes + daytime (fresh template world already pristine)
  timeout 60 node experiments/scripts/staff_prep.mjs --center "$CENTER" >/dev/null 2>&1
  rm -rf bots/andy/trace.jsonl bots/bob/trace.jsonl bots/candy/trace.jsonl bots/andy/logs bots/bob/logs bots/candy/logs

  node experiments/scripts/observer.mjs --out "$TRACE" --center "$CENTER" >"$TRIAL/observer.log" 2>&1 &
  OBSPID=$!
  sleep 4

  START_EPOCH=$(date +%s%3N)
  SETTINGS_JSON="{\"port\":55916,\"auto_open_ui\":false,\"profiles\":$PROFILES,\"load_memory\":false,\"trace\":true,\"log_all_prompts\":true,\"blocked_actions\":$BLOCKED}" \
    timeout 1100 node main.js --task_path "$TASK" --task_id "$TID" >"$TRIAL/run.log" 2>&1 &
  RUNPID=$!
  python3 experiments/scripts/score_watcher.py "$TRIAL/run.log" "$TRACE/scores.tsv" >/dev/null 2>&1 &
  WPID=$!

  wait "$RUNPID"
  kill "$OBSPID" "$WPID" 2>/dev/null
  sleep 3

  for a in andy bob candy; do
    mv "bots/$a/trace.jsonl" "$TRACE/$a.trace.jsonl" 2>/dev/null
    [ -d "bots/$a/logs" ] && mkdir -p "$TRACE/prompts/$a" && mv bots/$a/logs/* "$TRACE/prompts/$a/" 2>/dev/null
  done
  python3 - "$TRACE" "$TID" "$START_EPOCH" "$GROUP" <<'EOF'
import json, sys, os
trace, tid, start, group = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
json.dump({
  "task_id": tid, "group": group, "start_epoch_ms": start,
  "world": "arena_natural (seed 20260713), plains site, reset from template each trial",
  "blueprint_origin": [-348, 64, 246],
}, open(os.path.join(trace, "meta.json"), "w"), indent=2)
EOF

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
  CHEAT=$(grep -ac "/give\|/setblock" "$TRIAL/run.log" 2>/dev/null | head -1)
  SPAWNED=$(grep -acE "^(andy|bob|candy) spawned" "$TRIAL/run.log" 2>/dev/null | head -1)
  RESULT=$(python3 experiments/scripts/detect_drops.py --tsv "$TRACE/scores.tsv" 2>/dev/null | head -1)
  SIZE=$(du -sh "$TRACE" | cut -f1)
  gzip -f "$TRIAL/run.log" 2>/dev/null
  echo "trial_$(printf '%03d' "$i") group=$GROUP $RESULT truth_removals=$TRUTH cheat_cmds=$CHEAT spawned=$SPAWNED trace_size=$SIZE" >>"$SUMMARY"
  echo "[trials] trial $i done: group=$GROUP $RESULT truth_removals=$TRUTH cheat_cmds=$CHEAT spawned=$SPAWNED"
done
echo "[trials] GROUP $GROUP DONE"
