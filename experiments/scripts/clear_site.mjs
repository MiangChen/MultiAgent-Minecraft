// Clear the pyramid blueprint region + dropped items via an opped bot.
import mineflayer from 'mineflayer';
const bot = mineflayer.createBot({ host: '127.0.0.1', port: 55916, username: 'candy', auth: 'offline' });
bot.once('spawn', async () => {
  const cmds = [
    '/fill -62 -60 4 -49 -54 17 air',
    '/kill @e[type=item]',
    '/time set day',
    '/weather clear',
  ];
  for (const c of cmds) { bot.chat(c); await new Promise(r => setTimeout(r, 800)); }
  console.log('site cleared');
  bot.quit();
  setTimeout(() => process.exit(0), 1000);
});
