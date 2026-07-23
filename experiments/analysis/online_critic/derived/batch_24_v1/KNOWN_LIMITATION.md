# batch_24_v1 known limitation

`batch_24_v1` is retained as an immutable, reproducible model run, but its aggregate model behavior is provisional.

While building the `trial_106` / `trial_162` timeline viewer, a causal-state audit found that the v1 replay state kept only one active command per Agent. A transient zero-duration command could overwrite a still-running outer `!newAction`, then clear the slot when it ended. Repeated common `!goal` commands could also replace the latest specific `!newAction` claim.

The v2 state machine tracks active commands independently by `command_id` and keeps a specific action claim from being replaced by a later common goal. Comparing the same 72 fixed dry-run cutoffs found:

- 2/72 snapshots with a changed `current_execution` state (`trial_106` at 25% and `trial_186` at 25%);
- 38/72 snapshots with a changed latest task claim;
- 37/72 v2 snapshots with an active execution, versus 35/72 in v1.

Because these fields are part of the model prompt, the v1 verdict counts, label counts, advisories, and mean confidence must not be treated as final accuracy or calibrated behavior. Corrected causal packets are under `../batch_24_v2/dry_run/`. Corrected real-model outputs for the two current visual cases are under `../timeline_106_162_v2/results/`.

The v1 raw results have not been overwritten, and no claim is made that only the two changed execution-state snapshots would produce different model outputs: changed task claims can also alter semantic judgments.
