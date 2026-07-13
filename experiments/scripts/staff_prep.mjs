// Pre-trial staff pass on a fresh template world: restore agent gamemodes,
// set time/weather, and pre-load site chunks. Run by watcher (opped).
import mineflayer from 'mineflayer';

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : dflt;
}
const [cx, cy, cz] = arg('center', '-343.5,64,250.5').split(',').map(Number);

const bot = mineflayer.createBot({ host: '127.0.0.1', port: 55916, username: 'watcher', auth: 'offline' });
bot.once('spawn', async () => {
  const say = async (c, ms = 300) => { bot.chat(c); await new Promise(r => setTimeout(r, ms)); };
  await say('/gamemode spectator');
  await say(`/tp watcher ${Math.round(cx)} ${Math.round(cy + 30)} ${Math.round(cz)}`, 1500); // pre-load site chunks
  for (const a of ['andy', 'bob', 'candy']) await say(`/gamemode survival ${a}`, 150);
  await say('/time set day');
  await say('/weather clear');
  console.log('staff prep done');
  bot.quit();
  setTimeout(() => process.exit(0), 800);
});
bot.on('error', e => { console.log('staff_prep error:', e.message); process.exit(1); });
