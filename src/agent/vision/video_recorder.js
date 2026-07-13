import { Viewer } from 'prismarine-viewer/viewer/lib/viewer.js';
import { WorldView } from 'prismarine-viewer/viewer/lib/worldView.js';

import THREE from 'three';
import { createCanvas } from 'node-canvas-webgl/lib/index.js';
import { spawn } from 'child_process';
import fs from 'fs';
import { Vec3 } from 'vec3';
import settings from '../settings.js';

import worker_threads from 'worker_threads';
global.Worker = worker_threads.Worker;

export class VideoRecorder {
    constructor(bot, name) {
        this.bot = bot;
        this.name = name;
        this.fps = settings.video_fps || 12;
        const res = settings.video_resolution || [854, 480];
        this.width = res[0];
        this.height = res[1];
        this.viewDistance = 12;
        this.dir = `./bots/${name}/videos`;
        this.frames_written = 0;
        this.last_buf = null;
        this.rendering = false;
        this.backpressured = false;
        this.stopped = false;
    }

    async start() {
        fs.mkdirSync(this.dir, { recursive: true });
        this.start_epoch_ms = Date.now();
        const base = `${this.dir}/${this.start_epoch_ms}`;
        this.video_path = `${base}.mp4`;

        this.canvas = createCanvas(this.width, this.height);
        this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas });
        this.viewer = new Viewer(this.renderer);
        this.viewer.setVersion(this.bot.version);
        const center = this._center();
        this.worldView = new WorldView(this.bot.world, this.viewDistance, center);
        this.viewer.listen(this.worldView);
        this.worldView.listenToBot(this.bot);
        await this.worldView.init(center);

        // fragmented mp4: file stays playable even if the agent process is hard-killed
        this.ffmpeg = spawn('ffmpeg', [
            '-y', '-f', 'image2pipe', '-framerate', String(this.fps), '-i', 'pipe:0',
            '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-movflags', '+frag_keyframe+empty_moov',
            '-r', String(this.fps), this.video_path,
        ], { stdio: ['pipe', 'ignore', fs.openSync(`${base}.ffmpeg.log`, 'w')] });
        this.ffmpeg.stdin.on('error', () => {});
        this.ffmpeg.stdin.on('drain', () => { this.backpressured = false; });

        // sidecar: wall-clock -> frame index mapping for post-hoc clip alignment
        this.timeline_path = `${base}.timeline.tsv`;
        fs.writeFileSync(this.timeline_path, `# start_epoch_ms=${this.start_epoch_ms} fps=${this.fps} w=${this.width} h=${this.height}\n`);

        this.interval = setInterval(() => this._tick(), 1000 / this.fps);
        console.log(`[recorder] ${this.name}: recording ${this.width}x${this.height}@${this.fps}fps -> ${this.video_path}`);
    }

    _center() {
        const p = this.bot.entity.position;
        return new Vec3(p.x, p.y + this.bot.entity.height, p.z);
    }

    async _tick() {
        if (this.stopped) return;
        if (!this.rendering) {
            this.rendering = true;
            try {
                const center = this._center();
                this.viewer.camera.position.set(center.x, center.y, center.z);
                await this.worldView.updatePosition(center);
                this.viewer.setFirstPersonCamera(this.bot.entity.position, this.bot.entity.yaw, this.bot.entity.pitch);
                this.viewer.update();
                this.renderer.render(this.viewer.scene, this.viewer.camera);
                this.last_buf = this.canvas.toBuffer('image/jpeg');
            } catch (err) {
                if (!this._warned) {
                    console.log(`[recorder] ${this.name}: render error (further errors suppressed): ${err.message}`);
                    this._warned = true;
                }
            }
            this.rendering = false;
        }
        // write latest frame (duplicate if render is slow) to keep video time ~= wall time
        if (this.last_buf && !this.backpressured && this.ffmpeg.stdin.writable) {
            if (!this.ffmpeg.stdin.write(this.last_buf)) this.backpressured = true;
            this.frames_written++;
            if (this.frames_written % (this.fps * 5) === 0) {
                fs.appendFileSync(this.timeline_path, `${Date.now()}\t${this.frames_written}\n`);
            }
        }
    }

    stop() {
        if (this.stopped) return;
        this.stopped = true;
        clearInterval(this.interval);
        try { fs.appendFileSync(this.timeline_path, `${Date.now()}\t${this.frames_written}\n`); } catch {}
        try { this.ffmpeg.stdin.end(); } catch {}
        console.log(`[recorder] ${this.name}: stopped after ${this.frames_written} frames`);
    }
}

export function addVideoRecorder(agent, bot, name) {
    if (!settings.record_bot_video) return null;
    const recorder = new VideoRecorder(bot, name);
    recorder.start().catch(err => {
        console.log(`[recorder] ${name}: failed to start: ${err.message}`);
    });
    bot.on('end', () => recorder.stop());
    process.on('exit', () => recorder.stop());
    return recorder;
}
