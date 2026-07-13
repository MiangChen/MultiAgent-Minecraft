// Fixed isometric "god view" recorder: a spectator bot with a static camera
// hovering over the build site. No camera motion -> no FPV dizziness.
//
// Usage (run from repo root so node_modules resolves):
//   node experiments/scripts/god_camera.mjs \
//     [--username candy] [--port 55916] [--center -55.5,-58,10.5] \
//     [--distance 42] [--fov 38] [--fps 12] [--res 1280x720] [--out experiments/out]
//
// Output: <out>/god/videos/<epoch>.mp4 + <epoch>.timeline.tsv  (same layout as
// agent recordings, so make_clips.py can cut it with --agents god)
import mineflayer from 'mineflayer';
import { Viewer } from 'prismarine-viewer/viewer/lib/viewer.js';
import { WorldView } from 'prismarine-viewer/viewer/lib/worldView.js';
import THREE from 'three';
import { createCanvas } from 'node-canvas-webgl/lib/index.js';
import { spawn } from 'child_process';
import fs from 'fs';
import { Vec3 } from 'vec3';
import worker_threads from 'worker_threads';
global.Worker = worker_threads.Worker;

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : dflt;
}

const USERNAME = arg('username', 'candy');
const PORT = parseInt(arg('port', '55916'));
const [cx, cy, cz] = arg('center', '-55.5,-58,10.5').split(',').map(Number);
const DIST = parseFloat(arg('distance', '42'));
const FOV = parseFloat(arg('fov', '38'));
const FPS = parseInt(arg('fps', '12'));
const [W, H] = arg('res', '1280x720').split('x').map(Number);
const OUT = arg('out', 'experiments/out');

const center = new Vec3(cx, cy, cz);
// classic isometric-ish direction: diagonal in x/z, elevated
const dir = { x: 1, y: 1.05, z: 1 };
const dlen = Math.hypot(dir.x, dir.y, dir.z);
const camPos = new Vec3(
  center.x + (dir.x / dlen) * DIST,
  center.y + (dir.y / dlen) * DIST,
  center.z + (dir.z / dlen) * DIST,
);

const bot = mineflayer.createBot({ host: '127.0.0.1', port: PORT, username: USERNAME, auth: 'offline' });

bot.once('spawn', async () => {
  console.log(`[god] ${USERNAME} spawned; camera at ${camPos} looking at ${center}`);
  bot.chat('/gamemode spectator');
  await new Promise(r => setTimeout(r, 500));
  // perch near the site so the server keeps its chunks loaded for us
  bot.chat(`/tp ${USERNAME} ${Math.round(camPos.x)} ${Math.round(camPos.y)} ${Math.round(camPos.z)}`);
  await new Promise(r => setTimeout(r, 2000));

  const dirPath = `${OUT}/god/videos`;
  fs.mkdirSync(dirPath, { recursive: true });
  const startEpoch = Date.now();
  const base = `${dirPath}/${startEpoch}`;

  const canvas = createCanvas(W, H);
  const renderer = new THREE.WebGLRenderer({ canvas });
  const viewer = new Viewer(renderer);
  viewer.setVersion(bot.version);
  viewer.camera.fov = FOV;
  viewer.camera.aspect = W / H;
  viewer.camera.updateProjectionMatrix();

  const worldView = new WorldView(bot.world, 12, center);
  viewer.listen(worldView);
  worldView.listenToBot(bot);
  await worldView.init(center);

  const ffmpeg = spawn('ffmpeg', [
    '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-i', 'pipe:0',
    '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
    '-movflags', '+frag_keyframe+empty_moov', '-r', String(FPS), `${base}.mp4`,
  ], { stdio: ['pipe', 'ignore', fs.openSync(`${base}.ffmpeg.log`, 'w')] });
  ffmpeg.stdin.on('error', () => {});
  fs.writeFileSync(`${base}.timeline.tsv`, `# start_epoch_ms=${startEpoch} fps=${FPS} w=${W} h=${H} static_cam=${camPos} lookAt=${center}\n`);

  let frames = 0, rendering = false, backpressured = false, lastBuf = null;
  ffmpeg.stdin.on('drain', () => { backpressured = false; });

  const tick = async () => {
    if (!rendering) {
      rendering = true;
      try {
        await worldView.updatePosition(center); // keep chunk set anchored on the site
        viewer.camera.position.set(camPos.x, camPos.y, camPos.z);
        viewer.camera.lookAt(center.x, center.y, center.z);
        viewer.update();
        renderer.render(viewer.scene, viewer.camera);
        lastBuf = canvas.toBuffer('image/jpeg');
      } catch (e) { /* transient render errors are fine */ }
      rendering = false;
    }
    if (lastBuf && !backpressured && ffmpeg.stdin.writable) {
      if (!ffmpeg.stdin.write(lastBuf)) backpressured = true;
      frames++;
      if (frames % (FPS * 5) === 0) fs.appendFileSync(`${base}.timeline.tsv`, `${Date.now()}\t${frames}\n`);
    }
  };
  const interval = setInterval(tick, 1000 / FPS);
  console.log(`[god] recording ${W}x${H}@${FPS} -> ${base}.mp4  (Ctrl-C or kill to stop)`);

  const stop = () => {
    clearInterval(interval);
    try { fs.appendFileSync(`${base}.timeline.tsv`, `${Date.now()}\t${frames}\n`); } catch {}
    try { ffmpeg.stdin.end(); } catch {}
    console.log(`[god] stopped after ${frames} frames`);
    setTimeout(() => process.exit(0), 1500);
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  bot.on('end', stop);
});

bot.on('kicked', r => { console.log('[god] kicked:', r); process.exit(1); });
bot.on('error', e => { console.log('[god] error:', e.message); process.exit(1); });
