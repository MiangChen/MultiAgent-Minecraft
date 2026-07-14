#!/bin/bash
# Drive the full experiment matrix from matrix.json, with resume support:
# trials already present in trials_summary.txt are skipped group-wise.
# Usage: run_matrix.sh [matrix.json] [global_start_index]
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
MATRIX=${1:-experiments/tasks/matrix/matrix.json}
GSTART=${2:-101}
SUMMARY=experiments/out/trials_summary.txt
touch "$SUMMARY"

CENTER=$(python3 -c "import json;print(','.join(str(v) for v in json.load(open('$MATRIX'))['center']))")
PRESET=$(python3 -c "import json;print(json.load(open('$MATRIX')).get('blocked_preset','construction'))")
NGROUPS=$(python3 -c "import json;print(len(json.load(open('$MATRIX'))['groups']))")

idx=$GSTART
for g in $(seq 0 $((NGROUPS - 1))); do
  read -r GROUP TASKP TID ROUNDS PROFILES <<EOF
$(python3 -c "
import json
grp = json.load(open('$MATRIX'))['groups'][$g]
print(grp['group'], grp['task_path'], grp['task_id'], grp['rounds'], json.dumps(grp['profiles']))")
EOF
  # resume: count already-done trials of this group
  DONE=$(grep -c "group=$GROUP " "$SUMMARY" || true)
  REMAIN=$((ROUNDS - DONE))
  if [ "$REMAIN" -le 0 ]; then
    echo "[matrix] group $GROUP complete ($DONE/$ROUNDS), skipping"
    idx=$((idx + ROUNDS))
    continue
  fi
  START=$((idx + DONE))
  echo "[matrix] group $GROUP: running $REMAIN trials (index $START..$((START + REMAIN - 1)))"
  bash experiments/scripts/run_trials.sh "$REMAIN" "$TASKP" "$TID" "$START" "$GROUP" "$PROFILES" "$CENTER" "$PRESET"
  idx=$((idx + ROUNDS))
done
echo "[matrix] MATRIX DONE"
