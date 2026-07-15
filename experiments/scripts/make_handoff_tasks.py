#!/usr/bin/env python3
"""Generate the crafting handoff/imbalance batch (batch D, 100 trials).

Two designs x two recipes:
  H (handoff-forced): complementary inventories/abilities — completion requires
    at least one !givePlayer transfer.
  E (equal): fully symmetric inventories — either agent can solo; division of
    labor is optional (imbalance / duplicate-work probe).
"""
import json
import os

OUT = 'experiments/tasks/craft'
os.makedirs(OUT, exist_ok=True)

def task(goal, conv, inv, blocked, target, n=1, timeout=600):
    return {
        'goal': goal, 'conversation': conv, 'agent_count': 2,
        'initial_inventory': inv, 'blocked_actions': blocked,
        'target': target, 'number_of_target': n, 'type': 'techtree',
        'timeout': timeout,
    }

TASKS = {
    # H1: orthogonal materials — planks vs sticks, recipe needs both
    'craft_h1_pickaxe_split': task(
        'Collaborate with the other agent to craft a wooden pickaxe.',
        "Let's collaborate to craft a wooden pickaxe.",
        {'0': {'oak_planks': 10}, '1': {'stick': 10}},
        {'0': [], '1': []},
        'wooden_pickaxe'),
    # H2: complementary abilities — holder cannot craft, crafter cannot collect
    'craft_h2_shears_roles': task(
        'Collaborate with the other agent to craft shears.',
        "Let's collaborate to craft shears.",
        {'0': {'iron_ingot': 2}, '1': {'crafting_table': 1}},
        {'0': ['!craftRecipe'], '1': ['!collectBlocks']},
        'shears'),
    # E1: fully symmetric — either agent can solo the pickaxe
    'craft_e1_pickaxe_equal': task(
        'Work with the other agent to craft a wooden pickaxe.',
        "Let's craft a wooden pickaxe together.",
        {'0': {'oak_planks': 10, 'stick': 10}, '1': {'oak_planks': 10, 'stick': 10}},
        {'0': [], '1': []},
        'wooden_pickaxe'),
    # E2: fully symmetric with crafting table — cyan terracotta
    'craft_e2_terracotta_equal': task(
        'Work with the other agent to craft cyan terracotta.',
        "Let's craft cyan terracotta together.",
        {'0': {'terracotta': 8, 'cyan_dye': 1, 'crafting_table': 1},
         '1': {'terracotta': 8, 'cyan_dye': 1, 'crafting_table': 1}},
        {'0': [], '1': []},
        'cyan_terracotta'),
}

groups = []
for tid, t in TASKS.items():
    json.dump({tid: t}, open(f'{OUT}/{tid}.json', 'w'), indent=2)
    groups.append({'group': tid.replace('craft_', ''), 'task_path': f'{OUT}/{tid}.json',
                   'task_id': tid, 'rounds': 25,
                   'profiles': ['./task_andy.json', './task_bob.json']})
    print(f'{tid} -> {OUT}/{tid}.json')

matrix = {
    'center': [-343.5, 64, 250.5],  # same site; techtree teleports agents together anyway
    'groups': groups,
    'note': 'batch D: crafting handoff (H) / equal (E) designs, 4x25 = 100 trials',
}
json.dump(matrix, open(f'{OUT}/matrix_craft.json', 'w'), indent=2)
print(f'matrix_craft.json: {len(groups)} groups, {sum(g["rounds"] for g in groups)} trials')
