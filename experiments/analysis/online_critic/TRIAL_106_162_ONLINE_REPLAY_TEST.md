# Trial 106/162 online replay test

Chinese narrative report: [`TRIAL_106_162_ONLINE_REPLAY_STORY.md`](TRIAL_106_162_ONLINE_REPLAY_STORY.md).

## Question

Can the existing trajectory replay expose command execution that the earlier offline window missed, without leaking future command results to the critic?

The controlled test uses a 180-second cutoff. The message threshold is set to 999 so only the 90-second clock creates the 180-second snapshot. Replay runs headlessly at 1000x; model inference remains asynchronous and uses `gpt-5.6-sol` with `high` reasoning.

## Trial 162

At 180 seconds, the packet directly shows both executors acting:

- Bob's `!newAction` began at 97.860 seconds and had run for 82.140 seconds (`trace/bob.trace.jsonl:17`). Its recorded end is 236.759 seconds, so its result is absent from the 180-second packet.
- Andy's `!newAction` began at 138.411 seconds and had run for 41.589 seconds (`trace/andy.trace.jsonl:24`).

The model returned `imbalance_detected` with confidence `0.74`, classified as `duplicated_scope`. It did not call Bob idle. It advised splitting work by current material holdings and assigning only one executor to the final blueprint check.

Auditable result: `derived/trial_162_online_results.jsonl`.

## Trial 106

At 180 seconds, the packet again shows both executors acting:

- Bob's `!newAction` began at 139.468 seconds and had run for 40.532 seconds (`trace/bob.trace.jsonl:24`).
- Andy's `!newAction` began at 165.575 seconds and had run for 14.425 seconds (`trace/andy.trace.jsonl:31`).
- Team score rose from about 1.19% to 85.71% in the window, with the last observed increase at 155.032 seconds. This prevents command overlap alone from being mistaken for total lack of progress.

The model returned `imbalance_detected` with confidence `0.82`, classified as `duplicated_scope` and `role_action_mismatch`. It advised keeping Andy on stone-family coordinates and Bob on gold/quartz coordinates. Both current actions were recognized as active.

Auditable result: `derived/trial_106_online_results.jsonl`.

## Result

The replay integration fixes the specific observability gap: at a causal cutoff, the critic can distinguish a silent executor with a running command from one with no observed active command. The two pilot verdicts are also more specific than the old activity proxy: they rely on overlapping action scopes, complementary inventories, score history, and current execution state.

This does not yet prove that the proposed interventions improve task outcomes. The next experimental step is shadow evaluation over more trials, followed by controlled intervention/no-intervention comparisons. Visual replay plus critic was not runtime-tested in this pass because no Minecraft server was running; the verified path is `--critic-only` using the same replay scheduler.
