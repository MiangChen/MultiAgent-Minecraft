#!/usr/bin/env python3
"""Cut per-agent FPV clips around the demolition window and build a composite.

Usage: make_clips.py --tsv run_scores.tsv --videos-root mindcraft/bots --agents andy,bob --out outdir
"""
import argparse
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect_drops import parse_tsv, find_drops  # noqa: E402

PRE_S = 40   # seconds before first drop
POST_S = 50  # seconds after last drop
MAX_LEN = 150


def run(cmd):
    print('+', ' '.join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def video_duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'default=nw=1:nk=1', path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def video_meta(videos_dir, win_start_ms=None):
    """Pick the segment covering win_start_ms (agents may have restarted -> multiple mp4s)."""
    mp4s = sorted(glob.glob(os.path.join(videos_dir, '*.mp4')))
    if not mp4s:
        raise SystemExit(f'no mp4 in {videos_dir}')
    if win_start_ms is not None:
        for path in mp4s:
            start = int(os.path.basename(path).split('.')[0])
            end = start + video_duration(path) * 1000
            if start <= win_start_ms < end:
                return path, start
        # fallback: segment with latest start before the window
        best = max((p for p in mp4s if int(os.path.basename(p).split('.')[0]) <= win_start_ms),
                   key=lambda p: int(os.path.basename(p).split('.')[0]), default=mp4s[-1])
        return best, int(os.path.basename(best).split('.')[0])
    path = mp4s[-1]
    return path, int(os.path.basename(path).split('.')[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tsv', required=True)
    ap.add_argument('--videos-root', required=True)
    ap.add_argument('--agents', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    agents = args.agents.split(',')
    os.makedirs(args.out, exist_ok=True)

    seq = parse_tsv(args.tsv)
    drops = [d for d in find_drops(seq) if d['from'] > 10]  # ignore early setup noise
    if not drops:
        raise SystemExit('NO_DROPS')
    t0 = drops[0]['epoch_ms'] - PRE_S * 1000
    t1 = drops[-1]['epoch_ms'] + POST_S * 1000
    dur_s = (t1 - t0) / 1000
    speed = 1.0
    if dur_s > MAX_LEN:
        speed = dur_s / MAX_LEN
    print(f'window {t0}..{t1} ({dur_s:.0f}s), speed x{speed:.2f}, drops={len(drops)}')

    info = {'drops': drops, 'win_start_ms': t0, 'win_end_ms': t1, 'speed': speed}
    clips = []
    for name in agents:
        vpath, vstart = video_meta(os.path.join(args.videos_root, name, 'videos'), t0)
        off = max(0, (t0 - vstart) / 1000)
        clip = os.path.join(args.out, f'{name}_fpv.mp4')
        vf = f'setpts=PTS/{speed:.4f}' if speed > 1.001 else 'null'
        run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{off:.2f}', '-t', f'{dur_s:.2f}', '-i', vpath,
             '-vf', vf, '-an', '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
             '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip])
        # poster at first drop moment
        poster_off = max(0, (drops[0]['epoch_ms'] - vstart) / 1000)
        run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{poster_off:.2f}', '-i', vpath,
             '-vframes', '1', os.path.join(args.out, f'{name}_poster.jpg')])
        info[name] = {'video': vpath, 'video_start_ms': vstart, 'clip_offset_s': off}
        clips.append(clip)

    with open(os.path.join(args.out, 'clips_info.json'), 'w') as f:
        json.dump(info, f, indent=2)
    print('OK')


if __name__ == '__main__':
    main()
