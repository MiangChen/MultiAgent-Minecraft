#!/usr/bin/env python3
"""Compose one mp4: task banner on top + two FPV clips side by side."""
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
args = ap.parse_args()

W = 1708  # 2x854
BANNER_H = 120
img = Image.new('RGB', (W, BANNER_H), NAVY)
d = ImageDraw.Draw(img)
f_big = ImageFont.truetype(FONT_PATH, 40)
f_small = ImageFont.truetype(FONT_PATH, 26)
d.rectangle([0, 0, 14, BANNER_H], fill=AMBER)
d.text((40, 16), '任务：Make a structure with the blueprint — share materials, build together', font=f_big, fill=WHITE)
d.text((40, 72), 'andy 第一视角（左）  ·  bob 第一视角（右）  ·  MINDcraft construction 互拆实录', font=f_small, fill=AMBER)
banner = os.path.join(args.clips_dir, 'banner.png')
img.save(banner)

a = os.path.join(args.clips_dir, 'andy_fpv.mp4')
b = os.path.join(args.clips_dir, 'bob_fpv.mp4')
subprocess.run(['ffmpeg', '-y', '-v', 'error',
    '-i', a, '-i', b, '-i', banner,
    '-filter_complex',
    '[0:v]scale=854:480[l];[1:v]scale=854:480[r];[l][r]hstack[row];[2:v][row]vstack[out]',
    '-map', '[out]', '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', args.out], check=True)
print('saved', args.out)
