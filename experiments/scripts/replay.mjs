// Trajectory replay: puppet bots re-enact a recorded run (poses, block
// changes, chat) so any camera can re-record it — FPV, follow-cam, god view.
//
// Usage (from repo root; make sure NO real agents are running):
//   node experiments/scripts/replay.mjs --trace <dir with world_events.jsonl> \
//     [--speed 1] [--from 0] [--to 99999] [--mute-chat] [--fpv andy,bob] \
//     [--clear "-62,-60,4,-49,-54,17"] [--port 55916] [--director candy]
//
// Cameras: run god_camera.mjs in parallel for god/follow views; --fpv attaches
// first-person recorders to puppets (writes experiments/out/replay/<name>/videos).
import mineflayer from 'mineflayer';
import fs from 'fs';
import { spawn } from 'child_process';
import { execSync } from 'child_process';
import { Vec3 } from 'vec3';

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : dflt;
}
const has = (name) => process.argv.includes('--' + name);

const TRACE = arg('trace', null);
const SPEED = parseFloat(arg('speed', '1'));
const FROM_S = parseFloat(arg('from', '0'));
const TO_S = parseFloat(arg('to', '1e9'));
const MUTE = has('mute-chat');
const FPV = (arg('fpv', '') || '').split(',').filter(Boolean);
const CLEAR = arg('clear', '-62,-60,4,-49,-54,17').split(',').map(Number);
const PORT = parseInt(arg('port', '55916'));
const DIRECTOR = arg('director', 'candy');
const OUT = arg('out', 'experiments/out/replay');

if (!TRACE) { console.error('need --trace <dir>'); process.exit(1); }

// refuse to run while real agents are online (puppets reuse their names)
try {
  // only our own user's agents matter (other accounts may run their own mindcraft forks)
  const procs = execSync("pgrep -u $(id -u) -af 'node [m]ain.js|[i]nit_agent' || true").toString().trim();
  if (procs) { console.error('[replay] refusing to start: mindcraft agents appear to be running:\n' + procs); process.exit(1); }
} catch { }

const events = fs.readFileSync(`${TRACE}/world_events.jsonl`, 'utf8')
  .split('\n').filter(Boolean).map(l => JSON.parse(l));
const t0 = events.find(e => e.type !== 'meta')?.t ?? events[0].t;
const playable = events.filter(e =>
  ['pose', 'block', 'chat'].includes(e.type) &&
  (e.t - t0) / 1000 >= FROM_S && (e.t - t0) / 1000 <= TO_S);
const puppetNames = [...new Set(playable.filter(e => e.type === 'pose').map(e => e.name))];
console.log(`[replay] ${playable.length} events, puppets: ${puppetNames.join(', ')}, speed x${SPEED}`);

function mkBot(username) {
  return new Promise((resolve, reject) => {
    const b = mineflayer.createBot({ host: '127.0.0.1', port: PORT, username, auth: 'offline' });
    b.once('spawn', () => resolve(b));
    b.on('error', reject);
    b.on('kicked', r => console.log(`[replay] ${username} kicked:`, JSON.stringify(r).slice(0, 120)));
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// optional FPV recorder on puppets (same pipeline as agent video_recorder)
async function attachFPV(bot, name) {
  const { Viewer } = await import('prismarine-viewer/viewer/lib/viewer.js');
  const { WorldView } = await import('prismarine-viewer/viewer/lib/worldView.js');
  const THREE = (await import('three')).default;
  const { createCanvas } = await import('node-canvas-webgl/lib/index.js');
  const worker_threads = await import('worker_threads');
  global.Worker = worker_threads.Worker;
  const { Vec3 } = await import('vec3');

  const dir = `${OUT}/${name}/videos`;
  fs.mkdirSync(dir, { recursive: true });
  const base = `${dir}/${Date.now()}`;
  const W = 854, H = 480, FPS = 12;
  const canvas = createCanvas(W, H);
  const renderer = new THREE.WebGLRenderer({ canvas });
  const viewer = new Viewer(renderer);
  viewer.setVersion(bot.version);
  const center = () => new Vec3(bot.entity.position.x, bot.entity.position.y + 1.6, bot.entity.position.z);
  const wv = new WorldView(bot.world, 12, center());
  viewer.listen(wv);
  wv.listenToBot(bot);
  await wv.init(center());
  const ff = spawn('ffmpeg', ['-y', '-f', 'image2pipe', '-framerate', String(FPS), '-i', 'pipe:0',
    '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
    '-movflags', '+frag_keyframe+empty_moov', '-r', String(FPS), `${base}.mp4`],
    { stdio: ['pipe', 'ignore', fs.openSync(`${base}.ffmpeg.log`, 'w')] });
  ff.stdin.on('error', () => { });
  let busy = false, last = null;
  const iv = setInterval(async () => {
    if (!busy) {
      busy = true;
      try {
        await wv.updatePosition(center());
        viewer.setFirstPersonCamera(bot.entity.position, bot.entity.yaw, bot.entity.pitch);
        viewer.update();
        renderer.render(viewer.scene, viewer.camera);
        last = canvas.toBuffer('image/jpeg');
      } catch { }
      busy = false;
    }
    if (last && ff.stdin.writable) ff.stdin.write(last);
  }, 1000 / FPS);
  console.log(`[replay] FPV recorder on ${name} -> ${base}.mp4`);
  return () => { clearInterval(iv); try { ff.stdin.end(); } catch { } };
}

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

const puppets = {};
const stoppers = [];
for (const name of puppetNames) {
  puppets[name] = await mkBot(name);
  puppets[name].physicsEnabled = false; // server /tp drives position; stop client-side physics fighting it
  await sleep(300);
  director.chat(`/gamemode adventure ${name}`);
  if (FPV.includes(name)) stoppers.push(await attachFPV(puppets[name], name));
}
console.log('[replay] puppets online, starting playback');
// park the director far above the arena so it stays out of every camera's frame
// (spectator invisibility is not honored by the prismarine-viewer placeholder renderer)
director.chat(`/tp ${DIRECTOR} ${CLEAR[0] - 40} ${CLEAR[4] + 60} ${CLEAR[2] - 40}`);
await sleep(1500);

const wall0 = Date.now();
let done = 0, skipped = 0;
const lastTp = {};
for (const ev of playable) {
  const due = wall0 + (ev.t - t0 - FROM_S * 1000) / SPEED;
  const wait = due - Date.now();
  if (wait > 2) await sleep(wait);
  else if (wait < -2000) { skipped++; continue; } // fell too far behind; drop stale event

  if (ev.type === 'pose') {
    const b = puppets[ev.name];
    if (!b) continue;
    // cap /tp rate at 10Hz wall-clock per puppet (speed>1 would multiply it and trip spam limits)
    const now = Date.now();
    if (lastTp[ev.name] && now - lastTp[ev.name] < 100) continue;
    lastTp[ev.name] = now;
    b.chat(`/tp @s ${ev.x.toFixed(2)} ${ev.y.toFixed(2)} ${ev.z.toFixed(2)}`);
    b.look(ev.yaw, ev.pitch, true).catch(() => { });
  } else if (ev.type === 'block') {
    director.chat(`/setblock ${ev.x} ${ev.y} ${ev.z} ${ev.to}`);
    if (ev.to === 'air') {
      let best = null, bd = 1e9;
      const target = new Vec3(ev.x, ev.y, ev.z);
      for (const n of puppetNames) {
        if (!puppets[n]?.entity) continue;
        const dist = puppets[n].entity.position.distanceTo(target);
        if (dist < bd) { bd = dist; best = n; }
      }
      if (best && bd < 8) try { puppets[best].swingArm('right'); } catch { }
    }
  } else if (ev.type === 'chat' && !MUTE) {
    if (!ev.text.startsWith('/') && puppets[ev.from]) {
      try { puppets[ev.from].chat(ev.text.slice(0, 250)); } catch { }
    }
  }
  done++;
  if (done % 2000 === 0) console.log(`[replay] ${done}/${playable.length} events (${skipped} skipped)`);
}

console.log(`[replay] playback finished: ${done} events, ${skipped} skipped`);
await sleep(2000);
stoppers.forEach(s => s());
// restore gamemode — it persists per player name and would silently cripple
// the real agents on their next login (they share names with the puppets)
for (const name of puppetNames) director.chat(`/gamemode survival ${name}`);
await sleep(2000);
for (const b of Object.values(puppets)) b.quit();
director.quit();
setTimeout(() => process.exit(0), 1500);
