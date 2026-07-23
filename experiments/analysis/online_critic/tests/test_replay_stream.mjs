import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { loadCriticReplayStream } from '../replay_stream.mjs';


const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const tracePath = path.join(repoRoot, 'experiments/out/trial_162/trace');

test('trial_162 exposes Bob acting at 180s without revealing the result', () => {
  const stream = loadCriticReplayStream(tracePath);
  const start = stream.events.find(event =>
    event.agent === 'bob'
    && event.event_type === 'cmd_start'
    && event.command === '!newAction'
    && Math.abs(event.relative_time_s - 97.86) < 0.01);

  assert.ok(start, 'expected reconstructed Bob command start near 97.86s');
  assert.equal(start.result, undefined);
  const end = stream.events.find(event =>
    event.event_type === 'cmd_end' && event.command_id === start.command_id);
  assert.ok(end, 'expected the matching command end');
  assert.ok(Math.abs(end.relative_time_s - 236.759) < 0.01);
  assert.ok(end.result);

  const active = new Map();
  for (const event of stream.events) {
    if (event.relative_time_s > 180) break;
    if (event.event_type === 'cmd_start') active.set(event.agent, event);
    if (
      event.event_type === 'cmd_end'
      && active.get(event.agent)?.command_id === event.command_id
    ) {
      active.delete(event.agent);
    }
  }
  assert.equal(active.get('bob')?.command_id, start.command_id);
});
