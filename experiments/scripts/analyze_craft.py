#!/usr/bin/env python3
"""Batch D analysis: crafting handoff-failure and workload-imbalance metrics.

Per trial, from the command trace of each agent:
  - completed: did any run.log say "Task finished: Task successful"
  - handoffs: count of successful !givePlayer transfers
  - first_handoff_s: seconds from trial start to first !givePlayer
  - productive per-agent command counts (collect/craft/smelt/give) -> share, gini
  - duplicate craft: both agents issued !craftRecipe of the target (redundant work)

Groups: h1/h2 = handoff-forced, e1/e2 = equal (imbalance probe).
"""
import glob
import gzip
import json
import os
import re
from collections import defaultdict

PRODUCTIVE = {'!collectBlocks', '!craftRecipe', '!smeltItem', '!givePlayer'}


def gini(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0 or sum(xs) == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * sum(xs)) - (n + 1) / n


def read_completed(tdir):
    for p in (os.path.join(tdir, 'run.log.gz'), os.path.join(tdir, 'run.log')):
        if os.path.exists(p):
            opener = gzip.open if p.endswith('.gz') else open
            try:
                with opener(p, 'rt', errors='replace') as f:
                    return 'Task finished: Task successful' in f.read()
            except Exception:
                pass
    return False


def analyze(tdir):
    traces = glob.glob(os.path.join(tdir, 'trace', '*.trace.jsonl'))
    if not traces:
        return None
    t0 = None
    per_agent = defaultdict(lambda: defaultdict(int))
    handoffs = []          # (t, args, ok)
    craft_targets = defaultdict(list)
    for tr in traces:
        agent = os.path.basename(tr).split('.')[0]
        for l in open(tr):
            e = json.loads(l)
            if t0 is None or e['t'] < t0:
                t0 = e['t']
            if e.get('type') != 'cmd':
                continue
            cmd = e['cmd']
            if cmd in PRODUCTIVE:
                per_agent[agent][cmd] += 1
            if cmd == '!givePlayer':
                ok = 'gave' in str(e.get('result', '')).lower() or 'reached' in str(e.get('result', '')).lower()
                handoffs.append((e['t'], e.get('args'), ok))
            if cmd == '!craftRecipe':
                craft_targets[agent].append(str(e.get('args')))
    totals = {a: sum(c.values()) for a, c in per_agent.items()}
    shares = list(totals.values())
    max_share = max(shares) / sum(shares) if sum(shares) else 0
    dup_craft = len(craft_targets) >= 2 and all(v for v in craft_targets.values())
    first_ho = None
    if handoffs and t0:
        first_ho = round((min(h[0] for h in handoffs) - t0) / 1000)
    return {
        'completed': read_completed(tdir),
        'n_handoff': len(handoffs),
        'first_handoff_s': first_ho,
        'max_share': max_share,
        'gini': gini(shares) if len(shares) > 1 else 0.0,
        'dup_craft': dup_craft,
        'per_agent_total': totals,
    }


group_of = {}
for l in open('experiments/out/trials_summary.txt'):
    m = re.match(r'(trial_\d+) group=(\S+)', l)
    if m and m.group(2).startswith(('h1', 'h2', 'e1', 'e2')):
        group_of[m.group(1)] = m.group(2)

by_group = defaultdict(list)
for tdir in sorted(glob.glob('experiments/out/trial_[23]??')):
    name = os.path.basename(tdir)
    if name in group_of:
        r = analyze(tdir)
        if r:
            by_group[group_of[name]].append(r)

LABEL = {'h1_pickaxe_split': 'H1 木镐·正交材料', 'h2_shears_roles': 'H2 剪刀·能力互补',
         'e1_pickaxe_equal': 'E1 木镐·对等', 'e2_terracotta_equal': 'E2 陶瓦·对等'}
print(f"{'组':20} {'n':>3} {'完成率':>6} {'交接失败率':>8} {'均交接次数':>8} {'首次交接s':>8} {'最大份额':>7} {'基尼':>5} {'重复合成率':>8}")
report = {}
for g in ('h1_pickaxe_split', 'h2_shears_roles', 'e1_pickaxe_equal', 'e2_terracotta_equal'):
    rs = by_group.get(g, [])
    if not rs:
        continue
    n = len(rs)
    comp = sum(r['completed'] for r in rs)
    fail = n - comp
    hos = [r['n_handoff'] for r in rs]
    fhs = [r['first_handoff_s'] for r in rs if r['first_handoff_s'] is not None]
    shares = [r['max_share'] for r in rs if r['per_agent_total']]
    ginis = [r['gini'] for r in rs if r['per_agent_total']]
    dup = sum(r['dup_craft'] for r in rs)
    row = {
        'n': n, 'completed': comp, 'complete_rate': comp / n,
        'handoff_fail_rate': fail / n,
        'mean_handoffs': sum(hos) / n,
        'first_handoff_s_median': sorted(fhs)[len(fhs) // 2] if fhs else None,
        'max_share_mean': sum(shares) / len(shares) if shares else 0,
        'gini_mean': sum(ginis) / len(ginis) if ginis else 0,
        'dup_craft_rate': dup / n,
    }
    report[g] = row
    fh = row['first_handoff_s_median']
    print(f"{LABEL[g]:20} {n:3} {row['complete_rate']*100:5.0f}% {row['handoff_fail_rate']*100:7.0f}% "
          f"{row['mean_handoffs']:8.1f} {(str(fh)+'s' if fh is not None else '—'):>8} "
          f"{row['max_share_mean']*100:6.0f}% {row['gini_mean']:5.2f} {row['dup_craft_rate']*100:7.0f}%")

json.dump(report, open('experiments/out/craft_report.json', 'w'), ensure_ascii=False, indent=1)
print('\njson -> experiments/out/craft_report.json')
