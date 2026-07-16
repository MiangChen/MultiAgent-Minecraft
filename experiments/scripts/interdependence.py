#!/usr/bin/env python3
"""Interdependence analysis for construction (Who is Helping Whom, arXiv 2502.06976).

Maps the Minecraft build trajectory to a STRIPS-style pre/add/del formalism and
measures cooperation as inter-agent action dependencies, independent of task score.

Constructive interdependence (Int_cons): agent B places a block whose support
  (block directly below) was placed by a DIFFERENT agent A -> add(A) ⊆ pre(B).
  Counted as constructive only if goal-reaching (B's block matches the blueprint)
  and acyclic (that cell isn't later torn down and rebuilt).
Non-constructive (Int_noncons): cross-agent support dependency that is cyclic
  (cell churns place/remove) or non-goal-reaching (wrong block / later removed).
Destructive interdependence (Int_dest, our extension of the del/add framework —
  "who is HURTING whom"): agent B removes a correct blueprint block that agent A
  had placed -> del(B) clobbers add(A).
Parallelization index: self-support / (self + cross) support-dependent placements;
  high => agents build independently (shadow-equilibrium / Non-RC signature).
"""
import glob
import json
import os
import re
from collections import defaultdict

STRUCT = {'stone_bricks', 'stone', 'gold_block', 'quartz_block', 'quartz_pillar',
          'polished_andesite', 'polished_diorite', 'polished_granite', 'glowstone'}
ATTR_RADIUS = 6.0
ATTR_WINDOW_MS = 15000

TASK_OF_GROUP = {
    '2a_d0': 'pyr_2a_d0', '2a_d11': 'pyr_2a_d11', '2a_d22': 'pyr_2a_d22',
    '2a_d33': 'pyr_2a_d33', '3a_d22': 'pyr_3a_d22',
}


def load_blueprint(task_id):
    """coord (x,y,z) -> expected block type, from the task JSON blueprint."""
    p = f'experiments/tasks/matrix/{task_id}.json'
    data = json.load(open(p))[task_id]
    bp = {}
    for lvl in data['blueprint']['levels']:
        sx, sy, sz = lvl['coordinates']
        for zoff, row in enumerate(lvl['placement']):
            for xoff, name in enumerate(row):
                if name != 'air':
                    bp[(sx + xoff, sy, sz + zoff)] = name
    return bp


def nearest_agent(poses, t, x, y, z):
    best, bd = None, 1e9
    for name, plist in poses.items():
        lo, hi, idx = 0, len(plist) - 1, -1
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


def analyze_trial(tdir, blueprint):
    wev = os.path.join(tdir, 'trace', 'world_events.jsonl')
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

    # final occupancy per cell (to test acyclic / survives-to-end)
    final_type = {}
    churn = defaultdict(int)  # place/remove transitions per cell
    for e in blocks:
        k = (e['x'], e['y'], e['z'])
        tb, fb = e['to'].split('[')[0], e['from'].split('[')[0]
        if tb in STRUCT or (fb in STRUCT and e['to'] == 'air'):
            churn[k] += 1
        final_type[k] = e['to'].split('[')[0]

    placer = {}   # cell -> (agent, type, correct)
    cons = noncons = dest = self_sup = cross_sup = 0
    dest_pairs = defaultdict(int)   # (hurter, victim) -> count
    cons_pairs = defaultdict(int)   # (giver, receiver) -> count
    first_cross_t = None
    t0 = blocks[0]['t'] if blocks else 0

    for e in blocks:
        k = (e['x'], e['y'], e['z'])
        tb, fb = e['to'].split('[')[0], e['from'].split('[')[0]
        if tb in STRUCT:
            who = nearest_agent(poses, e['t'], e['x'], e['y'], e['z'])
            correct = blueprint.get(k) == tb
            below = placer.get((e['x'], e['y'] - 1, e['z']))
            if below and who:
                giver = below[0]
                if giver != who:                        # cross-agent support dependency
                    cross_sup += 1
                    if first_cross_t is None:
                        first_cross_t = e['t']
                    goal_reaching = correct and final_type.get(k) == tb
                    acyclic = churn[k] <= 1
                    if goal_reaching and acyclic:
                        cons += 1
                        cons_pairs[(giver, who)] += 1
                    else:
                        noncons += 1
                else:
                    self_sup += 1
            placer[k] = (who, tb, correct)
        elif fb in STRUCT and e['to'] == 'air':
            who = nearest_agent(poses, e['t'], e['x'], e['y'], e['z'])
            orig = placer.get(k)
            if who and orig and orig[0] and orig[0] != who and orig[2]:
                dest += 1                                 # destroyed a teammate's CORRECT block
                dest_pairs[(who, orig[0])] += 1

    total_sup = self_sup + cross_sup
    return {
        'int_cons': cons, 'int_noncons': noncons, 'int_dest': dest,
        'self_sup': self_sup, 'cross_sup': cross_sup,
        'parallel_index': self_sup / total_sup if total_sup else None,
        'cross_ratio': cross_sup / total_sup if total_sup else None,
        'first_cross_s': round((first_cross_t - t0) / 1000) if first_cross_t else None,
        'dest_pairs': dict(dest_pairs), 'cons_pairs': dict(cons_pairs),
    }


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sx = (sum((p[0] - mx) ** 2 for p in pairs)) ** 0.5
    sy = (sum((p[1] - my) ** 2 for p in pairs)) ** 0.5
    if sx == 0 or sy == 0:
        return None
    cov = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    return cov / (sx * sy)


def final_score(tdir):
    stsv = os.path.join(tdir, 'trace', 'scores.tsv')
    try:
        rows = [l.split('\t') for l in open(stsv) if '\t' in l]
        return float(rows[-1][1])
    except Exception:
        return None


if __name__ == '__main__':
    group_of = {}
    for l in open('experiments/out/trials_summary.txt'):
        m = re.match(r'(trial_\d+) group=(\S+)', l)
        if m and m.group(2) in TASK_OF_GROUP:
            group_of[m.group(1)] = m.group(2)

    bp_cache = {g: load_blueprint(t) for g, t in TASK_OF_GROUP.items()}
    by_group = defaultdict(list)
    all_score, all_cons, all_ratio = [], [], []
    for tdir in sorted(glob.glob('experiments/out/trial_[12][0-9][0-9]')):
        name = os.path.basename(tdir)
        g = group_of.get(name)
        if not g:
            continue
        r = analyze_trial(tdir, bp_cache[g])
        if not r:
            continue
        r['trial'] = name
        r['score'] = final_score(tdir)
        by_group[g].append(r)
        all_score.append(r['score'])
        all_cons.append(r['int_cons'])
        all_ratio.append(r['cross_ratio'])

    print(f"{'组':8} {'n':>3} {'Int_cons':>8} {'Int_nc':>7} {'Int_dest':>8} {'跨支撑占比':>8} {'并行指数':>7} {'终分均':>6}")
    report = {'groups': {}}
    for g in ('2a_d0', '2a_d11', '2a_d22', '2a_d33', '3a_d22'):
        rs = by_group.get(g, [])
        if not rs:
            continue
        n = len(rs)
        mc = sum(r['int_cons'] for r in rs) / n
        mnc = sum(r['int_noncons'] for r in rs) / n
        md = sum(r['int_dest'] for r in rs) / n
        ratios = [r['cross_ratio'] for r in rs if r['cross_ratio'] is not None]
        par = [r['parallel_index'] for r in rs if r['parallel_index'] is not None]
        mr = sum(ratios) / len(ratios) if ratios else 0
        mp = sum(par) / len(par) if par else 0
        ms = sum(r['score'] for r in rs if r['score'] is not None) / n
        print(f"{g:8} {n:3} {mc:8.1f} {mnc:7.1f} {md:8.1f} {mr*100:7.0f}% {mp*100:6.0f}% {ms:5.1f}%")
        report['groups'][g] = {
            'n': n, 'int_cons_mean': mc, 'int_noncons_mean': mnc, 'int_dest_mean': md,
            'cross_ratio_mean': mr, 'parallel_index_mean': mp, 'score_mean': ms,
            'trials': [{k: r[k] for k in ('trial', 'int_cons', 'int_noncons', 'int_dest',
                                          'cross_ratio', 'parallel_index', 'score')} for r in rs],
        }

    r_cons = pearson(all_score, all_cons)
    r_ratio = pearson(all_score, all_ratio)
    print(f"\n解耦检验（n={len([s for s in all_score if s is not None])}）：")
    print(f"  r(终分, Int_cons绝对数) = {r_cons:.3f}")
    print(f"  r(终分, 跨支撑占比) = {r_ratio:.3f}   ← 论文 Non-RC 参照 r≈0.19")
    report['decoupling'] = {'r_score_intcons': r_cons, 'r_score_crossratio': r_ratio,
                            'paper_nonrc_ref': 0.19}
    json.dump(report, open('experiments/out/interdep_report.json', 'w'), ensure_ascii=False, indent=1)
    print('\njson -> experiments/out/interdep_report.json')
