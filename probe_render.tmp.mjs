// Diagnostic probe: connect a bot, render frames, dump viewer internals.
import mineflayer from 'mineflayer';
import { Viewer } from 'prismarine-viewer/viewer/lib/viewer.js';
import { WorldView } from 'prismarine-viewer/viewer/lib/worldView.js';
import THREE from 'three';
import { createCanvas } from 'node-canvas-webgl/lib/index.js';
import fs from 'fs';
import { Vec3 } from 'vec3';
import worker_threads from 'worker_threads';
global.Worker = worker_threads.Worker;

const OUT = process.argv[2] || '/tmp';
const bot = mineflayer.createBot({ host: '127.0.0.1', port: 55916, username: 'probe', auth: 'offline' });

bot.once('spawn', async () => {
  console.log('spawned at', bot.entity.position, 'version', bot.version);
  await new Promise(r => setTimeout(r, 3000));
  const canvas = createCanvas(854, 480);
  const renderer = new THREE.WebGLRenderer({ canvas });
  const viewer = new Viewer(renderer);
  const vres = viewer.setVersion(bot.version);
  console.log('setVersion returned:', vres, typeof vres?.then === 'function' ? '(promise)' : '');
  if (vres && typeof vres.then === 'function') console.log('awaited setVersion ->', await vres);

  const p = bot.entity.position;
  const center = new Vec3(p.x, p.y + bot.entity.height, p.z);
  const worldView = new WorldView(bot.world, 8, center);
  viewer.listen(worldView);
  worldView.listenToBot(bot);
  await worldView.init(center);
  console.log('worldView loadedChunks:', Object.keys(worldView.loadedChunks).length);

  for (let i = 1; i <= 5; i++) {
    await new Promise(r => setTimeout(r, 2000));
    viewer.camera.position.set(center.x, center.y, center.z);
    await worldView.updatePosition(center);
    viewer.setFirstPersonCamera(bot.entity.position, bot.entity.yaw, -0.4);
    viewer.update();
    renderer.render(viewer.scene, viewer.camera);
    fs.writeFileSync(`${OUT}/probe_${i}.jpg`, canvas.toBuffer('image/jpeg'));
    const sections = viewer.world?.sectionMeshs ? Object.keys(viewer.world.sectionMeshs).length : -1;
    console.log(`frame ${i}: scene children=${viewer.scene.children.length} sectionMeshs=${sections}`);
  }
  process.exit(0);
});
bot.on('kicked', r => { console.log('kicked', r); process.exit(1); });
bot.on('error', e => { console.log('error', e.message); process.exit(1); });
