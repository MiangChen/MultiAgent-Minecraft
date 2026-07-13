// Pure trajectory observer: records world-truth events (player poses, block
// changes, chat) to JSONL. NO rendering, NO video — data collection and
// rendering are fully decoupled (render later via replay.mjs + cameras).
//
// Usage: node experiments/scripts/observer.mjs --out <trace_dir> \
//          [--username watcher] [--port 55916] [--center -55.5,-58,10.5] [--pose-hz 10]
import mineflayer from 'mineflayer';
import fs from 'fs';
import path from 'path';

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : dflt;
}

const USERNAME = arg('username', 'watcher');
const PORT = parseInt(arg('port', '55916'));
const OUT = arg('out', 'experiments/out/trace');
const POSE_HZ = parseFloat(arg('pose-hz', '10'));
const [cx, cy, cz] = arg('center', '-55.5,-58,10.5').split(',').map(Number);

fs.mkdirSync(OUT, { recursive: true });
const eventsPath = path.join(OUT, 'world_events.jsonl');
const stream = fs.createWriteStream(eventsPath, { flags: 'a' });
let nEvents = 0;

function emit(obj) {
  obj.t = Date.now();
  stream.write(JSON.stringify(obj) + '\n');
  nEvents++;
}

function blockStr(block) {
  if (!block) return 'air';
  let s = block.name;
  try {
    const props = block.getProperties();
    const keys = Object.keys(props);
    if (keys.length) s += '[' + keys.map(k => `${k}=${props[k]}`).join(',') + ']';
  } catch { /* stateless block */ }
  return s;
}

const bot = mineflayer.createBot({ host: '127.0.0.1', port: PORT, username: USERNAME, auth: 'offline' });

bot.once('spawn', async () => {
  bot.chat('/gamemode spectator');
  await new Promise(r => setTimeout(r, 500));
  bot.chat(`/tp ${USERNAME} ${Math.round(cx)} ${Math.round(cy + 30)} ${Math.round(cz)}`);
  await new Promise(r => setTimeout(r, 1500));

  emit({ type: 'meta', observer: USERNAME, version: bot.version, center: [cx, cy, cz], pose_hz: POSE_HZ });
  console.log(`[observer] recording to ${eventsPath}`);

  // --- block changes (world truth) ---
  bot.world.on('blockUpdate', (oldBlock, newBlock) => {
    if (!newBlock) return;
    const from = blockStr(oldBlock), to = blockStr(newBlock);
    if (from === to) return;
    const p = newBlock.position;
    emit({ type: 'block', x: p.x, y: p.y, z: p.z, from, to });
  });

  // --- player poses, throttled to POSE_HZ per player ---
  const lastPose = {};
  bot.on('entityMoved', (entity) => {
    if (entity.type !== 'player' || entity.username === USERNAME) return;
    const now = Date.now();
    if (lastPose[entity.username] && now - lastPose[entity.username] < 1000 / POSE_HZ) return;
    lastPose[entity.username] = now;
    const p = entity.position;
    emit({
      type: 'pose', name: entity.username,
      x: +p.x.toFixed(3), y: +p.y.toFixed(3), z: +p.z.toFixed(3),
      yaw: +entity.yaw.toFixed(3), pitch: +entity.pitch.toFixed(3),
    });
  });

  // --- chat / whispers ---
  bot.on('chat', (username, message) => {
    if (username === USERNAME) return;
    emit({ type: 'chat', from: username, text: message });
  });
  bot.on('whisper', (username, message) => {
    if (username === USERNAME) return;
    emit({ type: 'whisper', from: username, text: message });
  });

  bot.on('playerJoined', (player) => emit({ type: 'join', name: player.username }));
  bot.on('playerLeft', (player) => emit({ type: 'leave', name: player.username }));

  setInterval(() => console.log(`[observer] ${nEvents} events`), 30000);
});

const stop = () => {
  console.log(`[observer] stopping with ${nEvents} events`);
  stream.end(() => process.exit(0));
  setTimeout(() => process.exit(0), 1500);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
bot.on('kicked', r => { console.log('[observer] kicked:', r); stop(); });
bot.on('error', e => { console.log('[observer] error:', e.message); });
