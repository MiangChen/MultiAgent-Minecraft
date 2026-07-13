#!/usr/bin/env python3
"""Generate the 100-trial pressure-scan task matrix on the natural-terrain site.

- Rebases the pyramid blueprint from the superflat origin (-60,-60,6) to the
  natural site origin (default -348,64,246; ground block y=63).
- Emits 2-agent tasks at material deficits {0,11,22,33}% and a 3-agent task
  at 22%, plus matrix.json describing groups for run_matrix.sh.
"""
import copy
import json
import os

SRC = 'tasks/construction_tasks/custom/pyramid_three_agents.json'
OUT_DIR = 'experiments/tasks/matrix'
NEW_ORIGIN = (-348, 64, 246)   # blueprint base layer (ground block at y=63)
OLD_ORIGIN = (-60, -60, 6)
TIMEOUT = 720
STONE_FAMILY = ['stone_bricks', 'stone', 'polished_andesite', 'polished_diorite']

src = json.load(open(SRC))['pyramid_three_agents']
DX, DY, DZ = (NEW_ORIGIN[i] - OLD_ORIGIN[i] for i in range(3))

bp = copy.deepcopy(src['blueprint'])
for lvl in bp['levels']:
    c = lvl['coordinates']
    lvl['coordinates'] = [c[0] + DX, c[1] + DY, c[2] + DZ]

total_blocks = sum(v for v in bp['materials'].values())

TOOLS = {'diamond_pickaxe': 1, 'diamond_axe': 1, 'diamond_shovel': 1}
INV2_FULL = {
    '0': {**TOOLS, 'polished_granite': 1, 'polished_andesite': 34, 'polished_diorite': 21,
          'stone': 23, 'stone_bricks': 41},
    '1': {**TOOLS, 'gold_block': 27, 'quartz_block': 16, 'quartz_pillar': 2, 'glowstone': 3},
}
INV3_FULL = {
    '0': {**TOOLS, 'polished_granite': 1, 'polished_andesite': 34, 'polished_diorite': 21},
    '1': {**TOOLS, 'gold_block': 27, 'quartz_block': 16, 'quartz_pillar': 2},
    '2': {**TOOLS, 'stone_bricks': 41, 'stone': 23, 'glowstone': 3},
}


def apply_deficit(inv_full, pct):
    """Remove round(total*pct) blocks from stone-family items, proportionally."""
    inv = copy.deepcopy(inv_full)
    target = round(total_blocks * pct / 100)
    if target == 0:
        return inv, 0
    pool = []  # (agent, item, count)
    for a, items in inv.items():
        for it in STONE_FAMILY:
            if it in items:
                pool.append([a, it, items[it]])
    pool_total = sum(p[2] for p in pool)
    removed = 0
    for i, (a, it, cnt) in enumerate(pool):
        cut = round(target * cnt / pool_total) if i < len(pool) - 1 else target - removed
        cut = min(cut, cnt - 1)  # always leave at least 1 for realism
        inv[a][it] = cnt - cut
        removed += cut
    return inv, removed


os.makedirs(OUT_DIR, exist_ok=True)
groups = []
for agents, pct, rounds in [(2, 0, 20), (2, 11, 20), (2, 22, 20), (2, 33, 20), (3, 22, 20)]:
    inv_full = INV2_FULL if agents == 2 else INV3_FULL
    inv, removed = apply_deficit(inv_full, pct)
    tid = f'pyr_{agents}a_d{pct}'
    task = {
        'type': 'construction',
        'goal': src['goal'],
        'conversation': src['conversation'],
        'agent_count': agents,
        'timeout': TIMEOUT,
        'initial_inventory': inv,
        'blueprint': bp,
    }
    path = f'{OUT_DIR}/{tid}.json'
    json.dump({tid: task}, open(path, 'w'), indent=2)
    profiles = ['./task_andy.json', './task_bob.json'] + (['./task_candy.json'] if agents == 3 else [])
    groups.append({'group': f'{agents}a_d{pct}', 'task_path': path, 'task_id': tid,
                   'rounds': rounds, 'profiles': profiles, 'deficit_blocks': removed})
    print(f'{tid}: agents={agents} deficit={pct}% (-{removed} blocks) -> {path}')

matrix = {
    'site_origin': NEW_ORIGIN,
    'ground_y': NEW_ORIGIN[1] - 1,
    'center': [NEW_ORIGIN[0] + 4.5, NEW_ORIGIN[1], NEW_ORIGIN[2] + 4.5],
    'clear_region': [NEW_ORIGIN[0] - 2, NEW_ORIGIN[1] - 1, NEW_ORIGIN[2] - 2,
                     NEW_ORIGIN[0] + 12, NEW_ORIGIN[1] + 6, NEW_ORIGIN[2] + 12],
    'total_blocks': total_blocks,
    'groups': groups,
}
json.dump(matrix, open(f'{OUT_DIR}/matrix.json', 'w'), indent=2)
print(f'matrix.json: {len(groups)} groups, {sum(g["rounds"] for g in groups)} trials, blueprint {total_blocks} blocks')
