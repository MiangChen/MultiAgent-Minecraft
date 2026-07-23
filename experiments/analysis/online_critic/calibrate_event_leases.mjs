#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

import { loadCriticReplayStream } from './replay_stream.mjs';


const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../../..');

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : fallback;
}

function quantile(values, probability) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const index = (sorted.length - 1) * probability;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

function rounded(value) {
  return value === null ? null : Number(value.toFixed(3));
}

const manifestPath = path.resolve(arg(
  'manifest',
  path.join(here, 'batch_24_manifest.json'),
));
const excluded = new Set(
  arg('exclude', 'trial_106,trial_162').split(',').map(value => value.trim()).filter(Boolean),
);
const outputPath = arg('output', null);
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const selected = manifest.trials.filter(trial => !excluded.has(trial.trial_id));
const domains = {};

for (const domain of [...new Set(selected.map(trial => trial.domain))].sort()) {
  const trials = selected.filter(trial => trial.domain === domain);
  const actionDurations = [];
  const positiveScoreGaps = [];
  for (const trial of trials) {
    const tracePath = path.join(repoRoot, 'experiments', 'out', trial.trial_id, 'trace');
    const stream = loadCriticReplayStream(tracePath);
    let previousScore = null;
    let previousIncreaseS = null;
    for (const event of stream.events) {
      if (
        event.event_type === 'cmd_end'
        && event.command === '!newAction'
        && event.duration_ms > 0
      ) {
        actionDurations.push(event.duration_ms / 1000);
      }
      if (event.event_type !== 'score') continue;
      if (previousScore !== null && event.score > previousScore + 1e-9) {
        if (previousIncreaseS !== null) {
          positiveScoreGaps.push(event.relative_time_s - previousIncreaseS);
        }
        previousIncreaseS = event.relative_time_s;
      }
      previousScore = event.score;
    }
  }
  domains[domain] = {
    trial_count: trials.length,
    trial_ids: trials.map(trial => trial.trial_id),
    completed_new_action_count: actionDurations.length,
    new_action_duration_s: {
      p50: rounded(quantile(actionDurations, 0.5)),
      p80: rounded(quantile(actionDurations, 0.8)),
      p90: rounded(quantile(actionDurations, 0.9)),
      max: actionDurations.length ? rounded(Math.max(...actionDurations)) : null,
    },
    positive_score_gap_s: {
      count: positiveScoreGaps.length,
      p90: rounded(quantile(positiveScoreGaps, 0.9)),
      p95: rounded(quantile(positiveScoreGaps, 0.95)),
    },
  };
}

const constructionP80 = domains.construction?.new_action_duration_s?.p80;
const result = {
  schema_version: 'event_lease_calibration.v1',
  source_manifest: path.relative(repoRoot, manifestPath),
  excluded_evaluation_trials: [...excluded].sort(),
  calibration_trials: selected.length,
  domains,
  frozen_pilot_policy: {
    action_lease_s: constructionP80 === null ? 135 : Math.ceil(constructionP80),
    action_lease_basis: 'Rounded-up held-out construction !newAction duration p80.',
    request_ack_lease_s: 20,
    request_attempt_lease_s: 30,
    request_result_lease_s: 60,
    watchdog_interval_s: 120,
    min_trigger_gap_s: 20,
    prespecified_parameter_note: (
      'Request, watchdog, and cooldown values are pilot parameters, not fitted accuracy optima.'
    ),
  },
  evidence_boundary: (
    'The evaluated trial durations are excluded. A live action never uses its own eventual duration.'
  ),
};

const rendered = `${JSON.stringify(result, null, 2)}\n`;
if (outputPath) {
  fs.mkdirSync(path.dirname(path.resolve(outputPath)), { recursive: true });
  fs.writeFileSync(path.resolve(outputPath), rendered);
} else {
  process.stdout.write(rendered);
}
