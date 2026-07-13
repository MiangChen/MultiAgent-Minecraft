// Scan the area around spawn for a flat open building site in a natural world.
// Criteria: 16x16 area, height variance <= 2, all surface blocks grass/dirt
// (no water/leaves/logs inside the footprint), reasonably close to spawn.
//
// Usage: node experiments/scripts/find_site.mjs [--username watcher] [--port 55916] [--radius 160]
// Prints candidate sites sorted by (flatness, tree proximity is fine outside footprint).
import mineflayer from 'mineflayer';
import { Vec3 } from 'vec3';

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : dflt;
}
const USERNAME = arg('username', 'watcher');
const PORT = parseInt(arg('port', '55916'));
const RADIUS = parseInt(arg('radius', '160'));
const SIZE = 16;

const bot = mineflayer.createBot({ host: '127.0.0.1', port: PORT, username: USERNAME, auth: 'offline' });

bot.once('spawn', async () => {
  bot.chat('/gamemode spectator');
  await new Promise(r => setTimeout(r, 600));
  let spawn = bot.entity.position.floored();
  const originArg = arg('origin', null);
  if (originArg) {
    const [ox, oy, oz] = originArg.split(',').map(Number);
    spawn = new Vec3(ox, oy, oz);
  }
  console.log(`[site] scanning around ${spawn}`);

  const GOOD = new Set(['grass_block', 'dirt', 'coarse_dirt']); // grass terrain only (no sand deserts)
  const results = [];

  for (let cx = -RADIUS; cx <= RADIUS; cx += SIZE) {
    for (let cz = -RADIUS; cz <= RADIUS; cz += SIZE) {
      const ox = spawn.x + cx, oz = spawn.z + cz;
      // teleport above the candidate to force-load its chunks
      bot.chat(`/tp ${USERNAME} ${ox} ${spawn.y + 40} ${oz}`);
      await new Promise(r => setTimeout(r, 350));
      let ys = [], ok = true;
      for (let dx = 0; dx < SIZE && ok; dx += 3) {
        for (let dz = 0; dz < SIZE && ok; dz += 3) {
          // scan down for surface
          let surfaceY = null;
          for (let y = spawn.y + 30; y > spawn.y - 30; y--) {
            const b = bot.blockAt(new Vec3(ox + dx, y, oz + dz));
            if (!b) { ok = false; break; }
            if (b.name !== 'air' && !b.name.includes('grass') || b.name === 'grass_block') {
              if (b.name === 'grass_block' || GOOD.has(b.name)) { surfaceY = y; }
              else if (b.name !== 'air' && b.name !== 'short_grass' && b.name !== 'tall_grass' && b.name !== 'fern') { ok = false; }
              if (b.name !== 'air' && b.name !== 'short_grass' && b.name !== 'tall_grass' && b.name !== 'fern') break;
            }
          }
          if (surfaceY === null) ok = false;
          else ys.push(surfaceY);
        }
      }
      if (ok && ys.length) {
        const min = Math.min(...ys), max = Math.max(...ys);
        if (max - min <= 2) {
          const dist = Math.hypot(cx, cz);
          results.push({ x: ox, z: oz, groundY: max, dev: max - min, dist: Math.round(dist) });
        }
      }
    }
  }

  results.sort((a, b) => a.dev - b.dev || a.dist - b.dist);
  console.log(`[site] ${results.length} flat candidates:`);
  for (const r of results.slice(0, 8)) {
    console.log(`  origin=(${r.x},${r.groundY},${r.z}) dev=${r.dev} dist=${r.dist}`);
  }
  process.exit(0);
});
bot.on('error', e => { console.log('[site] error', e.message); process.exit(1); });
