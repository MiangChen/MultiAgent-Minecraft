#!/bin/bash
# Sequential god-view renders: <name>:<trace_dir>:<replay_speed> triples as args.
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
SC=${SCRATCH:-/tmp}
for spec in "$@"; do
  NAME=${spec%%:*}; rest=${spec#*:}; TRACE=${rest%%:*}; SPD=${rest##*:}
  echo "[render] === $NAME (speed $SPD) ==="
  rm -rf "experiments/out/render_$NAME"
  nohup node experiments/scripts/god_camera.mjs --username watcher --distance 30 --fov 45 \
    --out "experiments/out/render_$NAME" > "$SC/render_${NAME}_god.log" 2>&1 &
  CAMPID=$!
  ok=0
  for _ in $(seq 1 30); do grep -q "recording" "$SC/render_${NAME}_god.log" 2>/dev/null && { ok=1; break; }; sleep 2; done
  [ "$ok" = 1 ] || { echo "[render] $NAME camera failed"; kill "$CAMPID" 2>/dev/null; continue; }
  node experiments/scripts/replay.mjs --trace "$TRACE" --speed "$SPD" --mute-chat > "$SC/render_${NAME}_replay.log" 2>&1
  grep -a "playback finished" "$SC/render_${NAME}_replay.log" || tail -2 "$SC/render_${NAME}_replay.log"
  kill "$CAMPID" 2>/dev/null
  sleep 2
done
echo "[render] ALL DONE"
