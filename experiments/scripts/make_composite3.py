#!/usr/bin/env python3
"""Compose the paper-style three-view video:
banner on top, god view (isometric static cam) as the main pane,
two agent FPVs side by side at the bottom.

Usage: make_composite3.py --clips-dir <dir with god_fpv/andy_fpv/bob_fpv mp4s> --out out.mp4
(clip files produced by make_clips.py --agents god,andy,bob)
"""
import argparse
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

NAVY = (28, 45, 84)
AMBER = (242, 151, 39)
WHITE = (245, 246, 248)
FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'

ap = argparse.ArgumentParser()
ap.add_argument('--clips-dir', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--title', default='任务：Make a structure with the blueprint — share materials, build together')
ap.add_argument('--subtitle', default='上：固定等轴测机位（全景）  ·  下：andy / bob 第一视角  ·  材料缺口 22% 压力档')
args = ap.parse_args()

W, BANNER_H = 960, 90
img = Image.new('RGB', (W, BANNER_H), NAVY)
d = ImageDraw.Draw(img)
d.rectangle([0, 0, 10, BANNER_H], fill=AMBER)
d.text((32, 12), args.title, font=ImageFont.truetype(FONT_PATH, 26), fill=WHITE)
d.text((32, 54), args.subtitle, font=ImageFont.truetype(FONT_PATH, 19), fill=AMBER)
banner = os.path.join(args.clips_dir, 'banner3.png')
img.save(banner)

god = os.path.join(args.clips_dir, 'god_fpv.mp4')
a = os.path.join(args.clips_dir, 'andy_fpv.mp4')
b = os.path.join(args.clips_dir, 'bob_fpv.mp4')
subprocess.run(['ffmpeg', '-y', '-v', 'error',
    '-i', god, '-i', a, '-i', b, '-i', banner,
    '-filter_complex',
    '[0:v]scale=960:540[g];[1:v]scale=480:270[l];[2:v]scale=480:270[r];'
    '[l][r]hstack[row];[3:v][g][row]vstack=inputs=3[out]',
    '-map', '[out]', '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', args.out], check=True)
print('saved', args.out)
