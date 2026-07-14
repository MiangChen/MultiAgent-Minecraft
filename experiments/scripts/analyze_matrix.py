#!/usr/bin/env python3
"""Matrix analysis: per-group outcome classes, removal intensity, and
self-vs-cross demolition attribution via pose proximity.

Attribution: for every in-region structure block placement/removal, the acting
agent is the one whose latest pose (within ATTR_WINDOW_MS before the event) is
nearest to the block and within ATTR_RADIUS. cross-removal = remover differs
from the block's last placer.
"""
import argparse
import glob
import json
import os
import re
from collections import defaultdict

STRUCT = {'stone_bricks', 'stone', 'gold_block', 'quartz_block', 'quartz_pillar',
          'polished_andesite', 'polished_diorite', 'polished_granite', 'glowstone'}
REGION = (-348, 64, 246, -339, 69, 255)
ATTR_RADIUS = 6.0
ATTR_WINDOW_MS = 15000


def in_region(e):
    x1, y1, z1, x2, y2, z2 = REGION
    return x1 <= e['x'] <= x2 and y1 <= e['y'] <= y2 and z1 <= e['z'] <= z2


def nearest_agent(poses, t, x, y, z):
    best, bd = None, 1e9
    for name, plist in poses.items():
        # latest pose at or before t (plist sorted by t)
        lo, hi = 0, len(plist) - 1
        idx = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if plist[mid][0] <= t:
                idx = mid; lo = mid + 1
            else:
                hi = mid - 1
        if idx < 0 or t - plist[idx][0] > ATTR_WINDOW_MS:
            continue
        _, px, py, pz = plist[idx]
        d = ((px - x) ** 2 + (py - y) ** 2 + (pz - z) ** 2) ** 0.5
        if d < bd:
            bd, best = d, name
    return best if bd <= ATTR_RADIUS else None


def analyze_trial(tdir):
    wev = os.path.join(tdir, 'trace', 'world_events.jsonl')
    stsv = os.path.join(tdir, 'trace', 'scores.tsv')
    if not os.path.exists(wev):
        return None
    poses = defaultdict(list)
    blocks = []
    for l in open(wev):
        e = json.loads(l)
        if e['type'] == 'pose':
            poses[e['name']].append((e['t'], e['x'], e['y'], e['z']))
        elif e['type'] == 'block':
            blocks.append(e)
    placer = {}
    removals = []
    for e in blocks:
        if not in_region(e):
            continue
        key = (e['x'], e['y'], e['z'])
        to_base = e['to'].split('[')[0]
        from_base = e['from'].split('[')[0]
        if to_base in STRUCT:
            who = nearest_agent(poses, e['t'], e['x'], e['y'], e['z'])
            placer[key] = who
        elif from_base in STRUCT and e['to'] == 'air':
            who = nearest_agent(poses, e['t'], e['x'], e['y'], e['z'])
            removals.append({'t': e['t'], 'block': from_base, 'remover': who,
                             'placer': placer.get(key)})
    cross = sum(1 for r in removals
                if r['remover'] and r['placer'] and r['remover'] != r['placer'])
    self_rm = sum(1 for r in removals
                  if r['remover'] and r['placer'] and r['remover'] == r['placer'])
    unattr = len(removals) - cross - self_rm
    peak = final = 0.0
    try:
        rows = [l.split('\t') for l in open(stsv) if '\t' in l]
        vals = [float(r[1]) for r in rows]
        peak, final = max(vals), vals[-1]
    except Exception:
        pass
    return {'removals': len(removals), 'cross': cross, 'self': self_rm,
            'unattr': unattr, 'peak': peak, 'final': final}


def outcome(r):
    if r['peak'] >= 99.9:
        return '完成'
    if r['peak'] < 10:
        return '空转'
    if r['peak'] - r['final'] > 3:
        return '进度受损'
    return '停滞'


ap = argparse.ArgumentParser()
ap.add_argument('--summary', default='experiments/out/trials_summary.txt')
ap.add_argument('--out-json', default=None)
args = ap.parse_args()

group_of = {}
for l in open(args.summary):
    m = re.match(r'(trial_\d+) group=(\S+)', l)
    if m and 'smoke' not in m.group(2):
        group_of[m.group(1)] = m.group(2)

by_group = defaultdict(list)
for tdir in sorted(glob.glob('experiments/out/trial_1[0-9][0-9]')):
    name = os.path.basename(tdir)
    if name not in group_of:
        continue
    r = analyze_trial(tdir)
    if r:
        r['trial'] = name
        by_group[group_of[name]].append(r)

report = {}
print(f"{'组':8} {'n':>3} {'互拆轮':>4} {'互拆率':>6} {'自拆轮':>4} {'完成':>3} {'停滞':>3} {'空转':>3} {'受损':>3} {'峰均':>6} {'终均':>6} {'总互拆':>4}")
for g in ['2a_d0', '2a_d11', '2a_d22', '2a_d33', '3a_d22']:
    rs = by_group.get(g, [])
    if not rs:
        continue
    n = len(rs)
    cross_trials = sum(1 for r in rs if r['cross'] > 0)
    self_trials = sum(1 for r in rs if r['self'] > 0)
    oc = defaultdict(int)
    for r in rs:
        oc[outcome(r)] += 1
    peak_m = sum(r['peak'] for r in rs) / n
    fin_m = sum(r['final'] for r in rs) / n
    tot_cross = sum(r['cross'] for r in rs)
    print(f"{g:8} {n:3} {cross_trials:4} {cross_trials/n*100:5.0f}% {self_trials:4} "
          f"{oc['完成']:3} {oc['停滞']:3} {oc['空转']:3} {oc['进度受损']:3} {peak_m:5.1f}% {fin_m:5.1f}% {tot_cross:4}")
    report[g] = {'n': n, 'cross_trials': cross_trials, 'self_trials': self_trials,
                 'outcomes': dict(oc), 'peak_mean': peak_m, 'final_mean': fin_m,
                 'total_cross': tot_cross,
                 'trials': [{k: r[k] for k in ('trial', 'removals', 'cross', 'self', 'peak', 'final')} for r in rs]}

if args.out_json:
    json.dump(report, open(args.out_json, 'w'), ensure_ascii=False, indent=1)
    print('json ->', args.out_json)
