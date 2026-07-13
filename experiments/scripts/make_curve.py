#!/usr/bin/env python3
"""Plot the task-score curve with demolition drops annotated."""
import argparse
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect_drops import parse_tsv, find_drops  # noqa: E402

NAVY = '#1C2D54'
AMBER = '#F29727'

for f in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams['font.family'] = 'Noto Sans CJK SC'

ap = argparse.ArgumentParser()
ap.add_argument('--tsv', required=True)
ap.add_argument('--out', required=True)
args = ap.parse_args()

seq = parse_tsv(args.tsv)
drops = [d for d in find_drops(seq) if d["from"] > 10]
t0 = seq[0][0]
xs = [(ts - t0) / 60000 for ts, _ in seq]
ys = [s for _, s in seq]

fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
ax.plot(xs, ys, color=NAVY, lw=1.8, label='蓝图完成度')
for i, d in enumerate(drops):
    x = (d['epoch_ms'] - t0) / 60000
    ax.axvline(x, color=AMBER, lw=1.2, ls='--', alpha=0.9)
    ax.annotate(f"拆除 {d['from']:.1f}→{d['to']:.1f}%", (x, d['to']),
                xytext=(x + 0.3, max(5, d['to'] - 9 - 4 * (i % 2))),
                fontsize=9, color=AMBER,
                arrowprops=dict(arrowstyle='->', color=AMBER, lw=1))
ax.set_xlabel('时间（分钟）')
ax.set_ylabel('任务得分（% 蓝图匹配）')
ax.set_ylim(-3, 105)
ax.grid(alpha=0.25)
ax.set_title('双智能体协作建造：得分曲线与互拆事件', color=NAVY)
fig.tight_layout()
fig.savefig(args.out)
print('saved', args.out, f'drops={len(drops)}')
