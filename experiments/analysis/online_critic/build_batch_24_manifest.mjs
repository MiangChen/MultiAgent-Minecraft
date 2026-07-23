#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

import { loadCriticReplayStream } from './replay_stream.mjs';


const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const METRICS_PATH = path.join(
  ROOT,
  'experiments/analysis/open_world_coordination/derived/trial_process_metrics.jsonl',
);
const DEFAULT_OUTPUT = path.join(HERE, 'batch_24_manifest.json');
const CUTOFF_FRACTIONS = [0.25, 0.5, 0.75];

const SELECTION = [
  // Construction: six successful and six unsuccessful trials across every resource/team group.
  ['trial_104', 'construction', 'successful_quiet_complementarity'],
  ['trial_106', 'construction', 'successful_balanced_parallel_anchor'],
  ['trial_107', 'construction', 'near_complete_plateau_failure'],
  ['trial_126', 'construction', 'low_progress_resource_plateau'],
  ['trial_132', 'construction', 'resource_gap_success'],
  ['trial_149', 'construction', 'larger_resource_gap_success'],
  ['trial_158', 'construction', 'high_communication_without_completion'],
  ['trial_162', 'construction', 'scarce_resource_success_anchor'],
  ['trial_179', 'construction', 'very_low_progress_unknown_process'],
  ['trial_181', 'construction', 'three_agent_balanced_failure'],
  ['trial_186', 'construction', 'three_agent_success'],
  ['trial_190', 'construction', 'three_agent_communication_plateau'],

  // Crafting: three trials from each resource-role condition.
  ['trial_202', 'crafting', 'handoff_failure_then_repair'],
  ['trial_208', 'crafting', 'self_contained_terminal_mismatch'],
  ['trial_212', 'crafting', 'unanswered_request_and_resource_displacement'],
  ['trial_229', 'crafting', 'verified_role_handoff'],
  ['trial_230', 'crafting', 'unanswered_request_and_resource_displacement'],
  ['trial_243', 'crafting', 'handoff_failure_then_repair'],
  ['trial_255', 'crafting', 'parallel_overproduction_terminal_mismatch'],
  ['trial_257', 'crafting', 'self_contained_success'],
  ['trial_258', 'crafting', 'parallel_target_overproduction'],
  ['trial_279', 'crafting', 'repair_and_role_reassignment'],
  ['trial_286', 'crafting', 'verified_handoff'],
  ['trial_297', 'crafting', 'high_communication_terminal_mismatch'],
];

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : fallback;
}

function readJsonl(filePath) {
  return fs.readFileSync(filePath, 'utf8')
    .split('\n')
    .filter(line => line.trim())
    .map(line => JSON.parse(line));
}

function main() {
  const output = path.resolve(arg('output', DEFAULT_OUTPUT));
  const metrics = new Map(readJsonl(METRICS_PATH).map(row => [row.trial_id, row]));
  const domainCounts = Object.groupBy(SELECTION, row => row[1]);
  if (SELECTION.length !== 24) throw new Error(`Expected 24 trials, got ${SELECTION.length}`);
  if (domainCounts.construction.length !== 12 || domainCounts.crafting.length !== 12) {
    throw new Error('Selection must contain 12 construction and 12 crafting trials');
  }

  const trials = SELECTION.map(([trialId, domain, stratum]) => {
    const metric = metrics.get(trialId);
    if (!metric) throw new Error(`Missing process metrics for ${trialId}`);
    const tracePath = path.join(ROOT, 'experiments/out', trialId, 'trace');
    const replay = loadCriticReplayStream(tracePath);
    const meta = JSON.parse(fs.readFileSync(path.join(tracePath, 'meta.json'), 'utf8'));
    return {
      trial_id: trialId,
      domain,
      group: metric.group,
      task_id: meta.task_id,
      selection_stratum: stratum,
      known_process_labels_for_post_selection_audit: metric.phenomena,
      run_success: metric.run_success,
      final_score: metric.final_score,
      replay_end_s: replay.trial_end_s,
      agents: replay.agents,
      snapshots: CUTOFF_FRACTIONS.map(fraction => ({
        fraction,
        cutoff_s: Number((replay.trial_end_s * fraction).toFixed(3)),
      })),
    };
  });

  const manifest = {
    schema_version: 'online_critic_batch_manifest.v1',
    batch_id: 'batch_24_v1',
    created_date: '2026-07-23',
    selection_policy: {
      sample_size_trials: 24,
      domains: { construction: 12, crafting: 12 },
      construction_outcomes: { successful: 6, unsuccessful: 6 },
      cutoff_policy: 'Fixed 25%, 50%, and 75% replay-time quantiles.',
      cutoff_fractions: CUTOFF_FRACTIONS,
      selection_note: (
        'Trials were fixed from pre-existing process strata before critic inference. '
        + 'Known labels are retained only for post-selection auditing, not prompt input.'
      ),
    },
    model: 'gpt-5.6-sol',
    reasoning_effort: 'high',
    trials,
  };
  fs.writeFileSync(output, `${JSON.stringify(manifest, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ output, trials: trials.length, snapshots: 72 })}\n`);
}

main();
