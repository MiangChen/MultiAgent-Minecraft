// Agent-side trajectory tracer: appends JSONL events (commands, chat,
// inventory snapshots, code output) to bots/<name>/trace.jsonl.
// Enabled via settings.trace (default off). World-truth events (blocks,
// poses) are recorded separately by experiments/scripts/observer.mjs.
import fs from 'fs';
import settings from './settings.js';
import { getInventoryCounts } from './library/world.js';

const INV_POLL_MS = 5000;

export class Tracer {
    constructor(agent) {
        this.agent = agent;
        this.enabled = !!settings.trace;
        if (!this.enabled) return;
        const dir = `./bots/${agent.name}`;
        fs.mkdirSync(dir, { recursive: true });
        this.path = `${dir}/trace.jsonl`;
        this.stream = fs.createWriteStream(this.path, { flags: 'a' });
        this.last_inv = null;
        this.emit('trace_start', { agent: agent.name, pid: process.pid });
        this.inv_timer = setInterval(() => this._pollInventory(), INV_POLL_MS);
        console.log(`[tracer] ${agent.name}: tracing to ${this.path}`);
    }

    emit(type, data) {
        if (!this.enabled || !this.stream.writable) return;
        try {
            this.stream.write(JSON.stringify({ t: Date.now(), type, ...data }) + '\n');
        } catch { /* never break the agent for tracing */ }
    }

    _pollInventory() {
        try {
            const inv = getInventoryCounts(this.agent.bot);
            const s = JSON.stringify(inv);
            if (s !== this.last_inv) {
                this.last_inv = s;
                this.emit('inv', { items: inv });
            }
        } catch { /* bot may be mid-respawn */ }
    }

    stop() {
        if (!this.enabled) return;
        clearInterval(this.inv_timer);
        this.emit('trace_end', {});
        try { this.stream.end(); } catch { }
    }
}

export function truncate(s, n = 500) {
    if (typeof s !== 'string') s = JSON.stringify(s);
    return s && s.length > n ? s.slice(0, n) + `…(+${s.length - n})` : s;
}
