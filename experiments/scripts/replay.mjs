// Trajectory replay: puppet bots re-enact a recorded run while an optional
// shadow critic consumes the same causal replay clock.
//
// Visual replay (make sure no real agents are running):
//   node experiments/scripts/replay.mjs --trace <trace-dir> [--speed 1]
//     [--from 0] [--to 99999] [--mute-chat] [--fpv andy,bob]
//
// Headless critic replay (does not require a Minecraft server):
//   node experiments/scripts/replay.mjs --trace <trace-dir> --critic-only
//     [--critic-dry-run] [--critic-output <jsonl>]
import mineflayer from 'mineflayer';
import fs from 'fs';
import path from 'path';
import process from 'process';
import { once } from 'events';
import { spawn, spawnSync } from 'child_process';
import { Vec3 } from 'vec3';

import { loadCriticReplayStream } from '../analysis/online_critic/replay_stream.mjs';


function arg(name, dflt) {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : dflt;
}

const has = name => process.argv.includes(`--${name}`);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const TRACE = arg('trace', null);
const SPEED = Number.parseFloat(arg('speed', '1'));
const FROM_S = Number.parseFloat(arg('from', '0'));
const TO_S = Number.parseFloat(arg('to', '1e9'));
const MUTE = has('mute-chat');
const FPV = (arg('fpv', '') || '').split(',').filter(Boolean);
const CLEAR = arg('clear', '-62,-60,4,-49,-54,17').split(',').map(Number);
const PORT = Number.parseInt(arg('port', '55916'), 10);
const DIRECTOR = arg('director', 'candy');
const OUT = arg('out', 'experiments/out/replay');
const CRITIC_ONLY = has('critic-only');
const CRITIC_ENABLED = has('critic') || CRITIC_ONLY || has('critic-dry-run');
const CRITIC_DRY_RUN = has('critic-dry-run');
const CRITIC_TRIGGER_POLICY = arg('critic-trigger-policy', 'hybrid');
const CRITIC_INTERVAL_S = Number.parseFloat(arg('critic-time-interval', '90'));
const CRITIC_MESSAGE_COUNT = Number.parseInt(arg('critic-message-count', '8'), 10);
const CRITIC_ACTION_LEASE_S = Number.parseFloat(arg('critic-action-lease', '135'));
const CRITIC_REQUEST_ACK_LEASE_S = Number.parseFloat(arg('critic-request-ack-lease', '20'));
const CRITIC_REQUEST_ATTEMPT_LEASE_S = Number.parseFloat(arg('critic-request-attempt-lease', '30'));
const CRITIC_REQUEST_RESULT_LEASE_S = Number.parseFloat(arg('critic-request-result-lease', '60'));
const CRITIC_WATCHDOG_INTERVAL_S = Number.parseFloat(arg('critic-watchdog-interval', '120'));
const CRITIC_MIN_TRIGGER_GAP_S = Number.parseFloat(arg('critic-min-trigger-gap', '20'));
const CRITIC_TIMEOUT_S = Number.parseFloat(arg('critic-timeout', '900'));

if (!TRACE) {
  console.error('need --trace <dir>');
  process.exit(1);
}
if (!Number.isFinite(SPEED) || SPEED <= 0) throw new Error('--speed must be positive');
if (!Number.isFinite(FROM_S) || !Number.isFinite(TO_S) || FROM_S < 0 || TO_S < FROM_S) {
  throw new Error('--from and --to must define a non-negative, increasing interval');
}
if (!Number.isFinite(CRITIC_INTERVAL_S) || CRITIC_INTERVAL_S <= 0) {
  throw new Error('--critic-time-interval must be positive');
}
if (!Number.isInteger(CRITIC_MESSAGE_COUNT) || CRITIC_MESSAGE_COUNT <= 0) {
  throw new Error('--critic-message-count must be a positive integer');
}
if (!['hybrid', 'event_leases'].includes(CRITIC_TRIGGER_POLICY)) {
  throw new Error('--critic-trigger-policy must be hybrid or event_leases');
}
for (const [name, value] of [
  ['critic-action-lease', CRITIC_ACTION_LEASE_S],
  ['critic-request-ack-lease', CRITIC_REQUEST_ACK_LEASE_S],
  ['critic-request-attempt-lease', CRITIC_REQUEST_ATTEMPT_LEASE_S],
  ['critic-request-result-lease', CRITIC_REQUEST_RESULT_LEASE_S],
  ['critic-watchdog-interval', CRITIC_WATCHDOG_INTERVAL_S],
  ['critic-min-trigger-gap', CRITIC_MIN_TRIGGER_GAP_S],
]) {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`--${name} must be positive`);
}

const tracePath = path.resolve(TRACE);
const worldPath = path.join(tracePath, 'world_events.jsonl');
const events = fs.readFileSync(worldPath, 'utf8')
  .split('\n')
  .filter(Boolean)
  .map(line => JSON.parse(line));
const visualT0 = events.find(event => event.type !== 'meta')?.t ?? events[0].t;
const criticStream = CRITIC_ENABLED ? loadCriticReplayStream(tracePath) : null;
const clockT0 = criticStream?.t0 ?? visualT0;
const playable = events.filter(event => {
  const relative = (event.t - clockT0) / 1000;
  return ['pose', 'block', 'chat'].includes(event.type) && relative >= FROM_S && relative <= TO_S;
});
const preBlocks = events.filter(
  event => event.type === 'block' && (event.t - clockT0) / 1000 < FROM_S,
);
const puppetNames = [...new Set(playable.filter(event => event.type === 'pose').map(event => event.name))];

const trialId = path.basename(path.dirname(tracePath));
const defaultCriticOutput = path.join(
  'experiments', 'analysis', 'online_critic', 'derived', `${trialId}_online_results.jsonl`,
);
const CRITIC_OUTPUT = path.resolve(arg('critic-output', defaultCriticOutput));

function ensureNoLiveAgents() {
  const result = spawnSync(
    'pgrep',
    ['-u', String(process.getuid()), '-af', 'node [m]ain.js|[i]nit_agent'],
    { encoding: 'utf8' },
  );
  const processes = result.status === 0 ? result.stdout.trim() : '';
  if (processes) {
    console.error(`[replay] refusing to start: mindcraft agents appear to be running:\n${processes}`);
    process.exit(1);
  }
}

function mkBot(username) {
  return new Promise((resolve, reject) => {
    const bot = mineflayer.createBot({
      host: '127.0.0.1', port: PORT, username, auth: 'offline',
    });
    bot.once('spawn', () => resolve(bot));
    bot.on('error', reject);
    bot.on('kicked', reason => {
      console.log(`[replay] ${username} kicked:`, JSON.stringify(reason).slice(0, 120));
    });
  });
}

async function attachFPV(bot, name) {
  const { Viewer } = await import('prismarine-viewer/viewer/lib/viewer.js');
  const { WorldView } = await import('prismarine-viewer/viewer/lib/worldView.js');
  const THREE = (await import('three')).default;
  const { createCanvas } = await import('node-canvas-webgl/lib/index.js');
  const workerThreads = await import('worker_threads');
  globalThis.Worker = workerThreads.Worker;

  const dir = `${OUT}/${name}/videos`;
  fs.mkdirSync(dir, { recursive: true });
  const base = `${dir}/${Date.now()}`;
  const width = 854;
  const height = 480;
  const fps = 12;
  const canvas = createCanvas(width, height);
  const renderer = new THREE.WebGLRenderer({ canvas });
  const viewer = new Viewer(renderer);
  viewer.setVersion(bot.version);
  const center = () => new Vec3(
    bot.entity.position.x,
    bot.entity.position.y + 1.6,
    bot.entity.position.z,
  );
  const worldView = new WorldView(bot.world, 12, center());
  viewer.listen(worldView);
  worldView.listenToBot(bot);
  await worldView.init(center());
  const ffmpeg = spawn(
    'ffmpeg',
    [
      '-y', '-f', 'image2pipe', '-framerate', String(fps), '-i', 'pipe:0',
      '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
      '-movflags', '+frag_keyframe+empty_moov', '-r', String(fps), `${base}.mp4`,
    ],
    { stdio: ['pipe', 'ignore', fs.openSync(`${base}.ffmpeg.log`, 'w')] },
  );
  ffmpeg.stdin.on('error', () => {});
  let busy = false;
  let lastFrame = null;
  const timer = setInterval(async () => {
    if (!busy) {
      busy = true;
      try {
        await worldView.updatePosition(center());
        viewer.setFirstPersonCamera(bot.entity.position, bot.entity.yaw, bot.entity.pitch);
        viewer.update();
        renderer.render(viewer.scene, viewer.camera);
        lastFrame = canvas.toBuffer('image/jpeg');
      } catch {
        // Keep the last good frame if the renderer briefly falls behind.
      }
      busy = false;
    }
    if (lastFrame && ffmpeg.stdin.writable) ffmpeg.stdin.write(lastFrame);
  }, 1000 / fps);
  console.log(`[replay] FPV recorder on ${name} -> ${base}.mp4`);
  return () => {
    clearInterval(timer);
    try { ffmpeg.stdin.end(); } catch {
      // The recorder may already have closed its input.
    }
  };
}

async function setupVisualReplay() {
  ensureNoLiveAgents();
  console.log(
    `[replay] ${playable.length} visual events, puppets: ${puppetNames.join(', ')}, speed x${SPEED}`,
  );
  const director = await mkBot(DIRECTOR);
  console.log('[replay] director online');
  await sleep(500);
  director.chat('/gamemode spectator');
  director.chat(`/tp ${DIRECTOR} ${CLEAR[0]} ${CLEAR[4] + 20} ${CLEAR[2]}`);
  await sleep(500);
  director.chat(`/fill ${CLEAR[0]} ${CLEAR[1]} ${CLEAR[2]} ${CLEAR[3]} ${CLEAR[4]} ${CLEAR[5]} air`);
  director.chat('/kill @e[type=item]');
  director.chat('/time set day');
  director.chat('/weather clear');
  await sleep(1000);

  if (preBlocks.length) {
    console.log(
      `[replay] fast-applying ${preBlocks.length} pre-window block events at t=${FROM_S}s`,
    );
    for (let index = 0; index < preBlocks.length; index++) {
      const event = preBlocks[index];
      director.chat(`/setblock ${event.x} ${event.y} ${event.z} ${event.to}`);
      if (index % 25 === 24) await sleep(600);
    }
    await sleep(1500);
  }

  const puppets = {};
  const stoppers = [];
  for (const name of puppetNames) {
    puppets[name] = await mkBot(name);
    puppets[name].physicsEnabled = false;
    await sleep(300);
    director.chat(`/gamemode adventure ${name}`);
    if (FPV.includes(name)) stoppers.push(await attachFPV(puppets[name], name));
  }
  console.log('[replay] puppets online, starting playback');
  director.chat(`/tp ${DIRECTOR} ${CLEAR[0] - 40} ${CLEAR[4] + 60} ${CLEAR[2] - 40}`);
  await sleep(1500);

  const lastTeleport = {};
  let done = 0;
  let skipped = 0;
  return {
    apply(event, stale) {
      if (stale) {
        skipped++;
        return;
      }
      if (event.type === 'pose') {
        const bot = puppets[event.name];
        if (!bot) return;
        const now = Date.now();
        if (lastTeleport[event.name] && now - lastTeleport[event.name] < 100) return;
        lastTeleport[event.name] = now;
        bot.chat(`/tp @s ${event.x.toFixed(2)} ${event.y.toFixed(2)} ${event.z.toFixed(2)}`);
        bot.look(event.yaw, event.pitch, true).catch(() => {});
      } else if (event.type === 'block') {
        director.chat(`/setblock ${event.x} ${event.y} ${event.z} ${event.to}`);
        if (event.to === 'air') {
          let closest = null;
          let closestDistance = Number.POSITIVE_INFINITY;
          const target = new Vec3(event.x, event.y, event.z);
          for (const name of puppetNames) {
            if (!puppets[name]?.entity) continue;
            const distance = puppets[name].entity.position.distanceTo(target);
            if (distance < closestDistance) {
              closestDistance = distance;
              closest = name;
            }
          }
          if (closest && closestDistance < 8) {
            try { puppets[closest].swingArm('right'); } catch {
              // Animation is best-effort and does not affect replay state.
            }
          }
        }
      } else if (event.type === 'chat' && !MUTE) {
        if (!event.text.startsWith('/') && puppets[event.from]) {
          try { puppets[event.from].chat(event.text.slice(0, 250)); } catch {
            // A disconnected puppet should not stop the remaining replay.
          }
        }
      }
      done++;
      if (done % 2000 === 0) {
        console.log(`[replay] ${done}/${playable.length} visual events (${skipped} skipped)`);
      }
    },
    async close() {
      console.log(`[replay] visual playback finished: ${done} events, ${skipped} skipped`);
      await sleep(2000);
      stoppers.forEach(stop => stop());
      for (const name of puppetNames) director.chat(`/gamemode survival ${name}`);
      await sleep(2000);
      for (const bot of Object.values(puppets)) bot.quit();
      director.quit();
      await sleep(1500);
    },
  };
}

function relayChildOutput(stream, prefix, target) {
  stream.setEncoding('utf8');
  let buffered = '';
  stream.on('data', chunk => {
    buffered += chunk;
    const lines = buffered.split('\n');
    buffered = lines.pop();
    for (const line of lines) target.write(`${prefix}${line}\n`);
  });
  stream.on('end', () => {
    if (buffered) target.write(`${prefix}${buffered}\n`);
  });
}

async function startCritic(stream) {
  const script = path.resolve('experiments/analysis/online_critic/replay_critic.py');
  const commandArgs = [
    script,
    '--output', CRITIC_OUTPUT,
    '--trigger-policy', CRITIC_TRIGGER_POLICY,
    '--time-interval-s', String(CRITIC_INTERVAL_S),
    '--message-count', String(CRITIC_MESSAGE_COUNT),
    '--action-lease-s', String(CRITIC_ACTION_LEASE_S),
    '--request-ack-lease-s', String(CRITIC_REQUEST_ACK_LEASE_S),
    '--request-attempt-lease-s', String(CRITIC_REQUEST_ATTEMPT_LEASE_S),
    '--request-result-lease-s', String(CRITIC_REQUEST_RESULT_LEASE_S),
    '--watchdog-interval-s', String(CRITIC_WATCHDOG_INTERVAL_S),
    '--min-trigger-gap-s', String(CRITIC_MIN_TRIGGER_GAP_S),
    '--timeout-s', String(CRITIC_TIMEOUT_S),
  ];
  if (CRITIC_DRY_RUN) commandArgs.push('--dry-run');
  const child = spawn('python3', commandArgs, { stdio: ['pipe', 'pipe', 'pipe'] });
  relayChildOutput(child.stdout, '[critic] ', process.stdout);
  relayChildOutput(child.stderr, '[critic:err] ', process.stderr);
  let stdinError = null;
  child.stdin.on('error', error => { stdinError = error; });
  const exitPromise = new Promise((resolve, reject) => {
    child.once('exit', (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`critic sidecar exited with code=${code} signal=${signal}`));
    });
    child.once('error', reject);
  });
  await Promise.race([once(child, 'spawn'), exitPromise]);

  const reachedS = Math.min(TO_S, stream.trial_end_s);
  const sidecar = {
    child,
    exitPromise,
    get stdinError() { return stdinError; },
    reachedS,
    closed: false,
  };
  await sendCritic(sidecar, {
    kind: 'replay_start',
    trial_id: trialId,
    trace_path: tracePath,
    agents: stream.agents,
    t0: stream.t0,
    trial_end_s: stream.trial_end_s,
    replay_from_s: FROM_S,
    replay_to_s: reachedS,
    speed: SPEED,
  });
  console.log(
    `[replay] critic sidecar online: ${stream.events.length} causal events -> ${CRITIC_OUTPUT}`,
  );
  return sidecar;
}

async function sendCritic(sidecar, row) {
  if (sidecar.stdinError) throw sidecar.stdinError;
  const accepted = sidecar.child.stdin.write(`${JSON.stringify(row)}\n`);
  if (!accepted) await once(sidecar.child.stdin, 'drain');
}

async function closeCritic(sidecar) {
  if (!sidecar || sidecar.closed) return;
  sidecar.closed = true;
  sidecar.child.stdin.end();
  await sidecar.exitPromise;
}

async function main() {
  if (criticStream && FROM_S > criticStream.trial_end_s) {
    throw new Error(`--from=${FROM_S} is after trial end ${criticStream.trial_end_s}s`);
  }

  const visual = CRITIC_ONLY ? null : await setupVisualReplay();
  const sidecar = criticStream ? await startCritic(criticStream) : null;
  let sidecarEnded = false;
  let visualEnded = false;

  try {
    if (sidecar) {
      for (const event of criticStream.events) {
        if (event.relative_time_s >= FROM_S) break;
        if (event.relative_time_s < 0) continue;
        await sendCritic(sidecar, { kind: 'event', ...event });
      }
    }

    const timeline = [];
    let sequence = 0;
    if (visual) {
      for (const event of playable) {
        timeline.push({
          kind: 'visual',
          relative_time_s: (event.t - clockT0) / 1000,
          event,
          sequence: sequence++,
        });
      }
    }
    if (sidecar) {
      for (const event of criticStream.events) {
        if (
          event.relative_time_s < Math.max(0, FROM_S)
          || event.relative_time_s > sidecar.reachedS
        ) continue;
        timeline.push({
          kind: 'critic', relative_time_s: event.relative_time_s, event, sequence: sequence++,
        });
      }
    }
    timeline.sort((left, right) => {
      if (left.relative_time_s !== right.relative_time_s) {
        return left.relative_time_s - right.relative_time_s;
      }
      const leftPriority = left.kind === 'critic' ? 0 : 1;
      const rightPriority = right.kind === 'critic' ? 0 : 1;
      return leftPriority - rightPriority || left.sequence - right.sequence;
    });

    const wallStart = Date.now();
    for (const item of timeline) {
      const due = wallStart + ((item.relative_time_s - FROM_S) * 1000) / SPEED;
      const wait = due - Date.now();
      if (wait > 2) await sleep(wait);
      if (item.kind === 'critic') {
        await sendCritic(sidecar, { kind: 'event', ...item.event });
      } else {
        await visual.apply(item.event, wait < -2000);
      }
    }

    if (sidecar) {
      await sendCritic(sidecar, {
        kind: 'replay_end',
        reached_relative_s: sidecar.reachedS,
        completed_trial: sidecar.reachedS >= criticStream.trial_end_s - 1e-9,
      });
      sidecar.child.stdin.end();
      sidecar.closed = true;
      sidecarEnded = true;
    }

    const visualClose = visual?.close();
    visualEnded = Boolean(visual);
    await Promise.all([
      visualClose,
      sidecar?.exitPromise,
    ].filter(Boolean));
    if (sidecar) console.log(`[replay] critic playback finished -> ${CRITIC_OUTPUT}`);
  } finally {
    if (visual && !visualEnded) {
      visualEnded = true;
      await visual.close();
    }
    if (sidecar && !sidecarEnded) await closeCritic(sidecar);
  }
}

main().catch(error => {
  console.error('[replay] failed:', error);
  process.exitCode = 1;
});
