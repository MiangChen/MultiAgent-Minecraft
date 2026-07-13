// Reset the experiment arena between trials: clear the blueprint volume AND
// restore the surrounding superflat terrain (agents crater it while scavenging),
// so every trial starts from an identical world state.
import mineflayer from 'mineflayer';

const bot = mineflayer.createBot({ host: '127.0.0.1', port: 55916, username: 'candy', auth: 'offline' });

// arena: generous box around the build site (site x -60..-51, z 6..15)
const X1 = -100, X2 = -12, Z1 = -30, Z2 = 55;

bot.once('spawn', async () => {
  const say = async (c, ms = 250) => { bot.chat(c); await new Promise(r => setTimeout(r, ms)); };
  await say('/gamemode spectator');
  await say('/tp candy -55 -30 10', 800);

  const cmds = [];
  // per-layer fills stay under the 32768-block /fill limit (89×86 ≈ 7654 blocks/layer)
  for (let y = -60; y <= -50; y++) cmds.push(`/fill ${X1} ${y} ${Z1} ${X2} ${y} ${Z2} air`);
  cmds.push(`/fill ${X1} -61 ${Z1} ${X2} -61 ${Z2} grass_block`);
  cmds.push(`/fill ${X1} -62 ${Z1} ${X2} -62 ${Z2} dirt`);
  cmds.push(`/fill ${X1} -63 ${Z1} ${X2} -63 ${Z2} dirt`);
  cmds.push('/kill @e[type=item]');
  cmds.push('/time set day');
  cmds.push('/weather clear');
  // gamemode persists per player name — replay puppets may have left agents in
  // adventure mode, which silently breaks normal block interaction (batch-2 incident)
  cmds.push('/gamemode survival andy');
  cmds.push('/gamemode survival bob');
  for (const c of cmds) await say(c);
  console.log('site cleared + terrain reset');
  bot.quit();
  setTimeout(() => process.exit(0), 1000);
});
bot.on('error', e => { console.log('clear_site error:', e.message); process.exit(1); });
