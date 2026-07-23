# Online replay critic

中文报告：

- 24 轮扩样阶段报告：[`BATCH_24_STAGE_REPORT_ZH.md`](BATCH_24_STAGE_REPORT_ZH.md)
- 106/162 初始案例故事：[`TRIAL_106_162_ONLINE_REPLAY_STORY.md`](TRIAL_106_162_ONLINE_REPLAY_STORY.md)

交互式案例页：[`timeline_viewer/index.html`](timeline_viewer/index.html)。页面包含
`trial_106` / `trial_162` tabs、气泡故事模式和多泳道审计模式，可直接用浏览器打开。

This directory adds a read-only coordination critic to the existing trajectory replay. It is an online simulation over historical data: events are revealed in replay-clock order, and the critic never receives an event or command result later than its snapshot cutoff.

## What changes relative to the offline critic

Agent trace commands are recorded only when they finish. `replay_stream.mjs` reconstructs two causal events from each command row:

- `cmd_start = recorded_end_time - duration_ms`, containing the command and arguments but no result.
- `cmd_end = recorded_end_time`, containing duration and the recorded result.

The replay sidecar therefore reports `current_execution.status=acting` between those two events. Silence during that interval is not treated as idleness. A stable `command_id` pairs each start with its own end. Packet v2 tracks overlapping commands independently, so a transient command cannot overwrite a still-running outer action. A repeated common `!goal` also no longer replaces a more specific `!newAction` claim.

This reconstruction is appropriate for historical replay, but it uses duration metadata that becomes available only after a command finishes. A truly live rollout should emit authoritative start/end state from `src/agent/action_manager.js` or consume `state-update` from `src/mindcraft/mindserver.js` instead.

## Trigger policy

The default policy is hybrid: evaluate after 90 replay seconds or 8 outgoing Agent messages, whichever arrives first. This avoids treating a fixed number of dialogue turns as elapsed work. Both thresholds are configurable.

The experimental `event_leases` policy keeps commitment watches across snapshots and treats time as a deadline relative to an observed event. It evaluates candidates when a task action closes without verified progress, an action lease expires, a directed request is not acknowledged/attempted/verified, the score regresses, or a 120-second no-progress watchdog expires. Productive actions close silently. Candidate signals select a review moment; they are not model verdicts and do not require an advisory.

The 106/162 pilot freezes a 135-second action lease from the held-out construction `!newAction` duration p80 in 22 other manifest trials. Request and watchdog values are prespecified pilot parameters. Reproduce the calibration with:

```bash
node experiments/analysis/online_critic/calibrate_event_leases.mjs \
  --exclude trial_106,trial_162 \
  --output /tmp/event_lease_calibration.json
```

Model evaluation is asynchronous and shadow-only. It does not pause, redirect, or message the executor Agents. Accelerated replay can therefore finish before the model response, but each submitted packet retains its exact replay cutoff.

## Run without Minecraft

Dry-run one controlled snapshot at 180 seconds:

```bash
node experiments/scripts/replay.mjs \
  --trace experiments/out/trial_162/trace \
  --from 150 --to 195 --speed 1000 \
  --critic-only --critic-dry-run \
  --critic-time-interval 90 --critic-message-count 999 \
  --critic-output /tmp/trial_162_online_dry.jsonl
```

Remove `--critic-dry-run` for the configured `gpt-5.6-sol` critic with `high` reasoning. The large message threshold above is only a controlled test setting that guarantees the 180-second time trigger; normal runs should use the default hybrid policy.

Run the event-lease shadow policy over a complete historical trial with:

```bash
node experiments/scripts/replay.mjs \
  --trace experiments/out/trial_162/trace \
  --speed 100000 --critic-only \
  --critic-trigger-policy event_leases \
  --critic-output /tmp/trial_162_event_lease.jsonl
```

The trigger-policy pilot and its fixed-cutoff comparison are under `derived/event_lease_v1/`. Rebuild the validated summary with:

```bash
python3 experiments/analysis/online_critic/summarize_event_lease_experiment.py
```

## Run with visual replay

When the Minecraft server is available and real MindCraft Agents are stopped, add `--critic` to the normal replay command:

```bash
node experiments/scripts/replay.mjs \
  --trace experiments/out/trial_162/trace \
  --speed 1 --critic \
  --critic-output experiments/analysis/online_critic/derived/trial_162_visual_results.jsonl
```

Visual events and critic events share the same replay clock. Pre-window critic events are fast-fed as causal history, while events inside `--from/--to` are delivered at replay speed. Critic events are never dropped when visual replay falls behind.

## Reproduce the fixed 24-trial batch

The frozen manifest contains 12 construction and 12 crafting trials. Every trial is
evaluated at fixed 25%, 50%, and 75% replay-time cutoffs, producing 72 causal
snapshots. Pre-existing process labels were used to freeze diverse selection strata
but are never included in critic packets.

```bash
node experiments/analysis/online_critic/build_batch_24_manifest.mjs

python3 experiments/analysis/online_critic/run_batch.py \
  --dry-run --workers 4 \
  --output-root /tmp/online_critic_batch_24_dry

python3 experiments/analysis/online_critic/run_batch.py \
  --workers 3 \
  --output-root /tmp/online_critic_batch_24_results

python3 experiments/analysis/online_critic/summarize_batch.py \
  --results-root /tmp/online_critic_batch_24_results \
  --output-root /tmp/online_critic_batch_24_summary
```

The original completed run is under [`derived/batch_24_v1/`](derived/batch_24_v1/). It is retained for reproducibility, but its model-level aggregate is provisional: a later v2 audit found 2/72 snapshots with overwritten active execution and 38/72 with a specific claim replaced by a common goal. See [`KNOWN_LIMITATION.md`](derived/batch_24_v1/KNOWN_LIMITATION.md).

The corrected dry-run packets are under `derived/batch_24_v2/dry_run/`. Corrected real-model results for the 106/162 visual case study are under `derived/timeline_106_162_v2/results/`.

The v1 directory contains:

- `results/*.jsonl`: submitted packet and model output for each trial.
- `batch_summary.json`: schema-validated aggregate model behavior.
- `model_results.tsv`: model verdicts and advisories for post-audit comparison.
- `blind_packets.jsonl`: evidence packets with model verdicts and selection labels removed.
- `human_audit_blind.tsv`: empty human labels keyed to the blind packets.

Do not treat the model's alert rate or self-reported confidence as accuracy. Join the
blind human labels to `model_results.tsv` only after annotation is complete.

## Files

- `replay_stream.mjs`: structured world/Agent/score stream and command start reconstruction.
- `replay_critic.py`: replay state machine, hybrid trigger, evidence packet, and asynchronous model evaluator.
- `calibrate_event_leases.mjs`: held-out action-duration calibration for the event policy.
- `summarize_event_lease_experiment.py`: causal validation and fixed/event pilot comparison.
- `critic_prompt.md`: execution-state and evidence rules.
- `batch_24_manifest.json`: frozen 24-trial sample and three cutoffs per trial.
- `build_batch_24_manifest.mjs`: reproducible manifest builder.
- `run_batch.py`: bounded parallel dry-run/model batch runner with resume support.
- `summarize_batch.py`: schema validation, aggregate behavior, and blind audit export.
- `timeline_viewer/`: generated case data and the static story/audit HTML interface.
- `derived/*.jsonl`: append-only audit records containing both the submitted packet and model result.
- `tests/`: command causality, execution state, and message ownership checks.

Run focused tests with:

```bash
python3 -m unittest discover -s experiments/analysis/online_critic/tests -p 'test_*.py' -v
node --test experiments/analysis/online_critic/tests/test_replay_stream.mjs
node --test experiments/analysis/online_critic/tests/test_timeline_viewer.mjs
```

## Evidence boundaries

- `acting` proves a command is in progress, not that it is productive or will succeed.
- No active command observed is not by itself proof of idleness.
- Message recipient and local command executor remain separate.
- Replay block changes are not assigned to an executor without independent attribution.
- The replay critic is currently advisory and does not test intervention effects.
