#!/usr/bin/env python3
"""v1 dataset export: merge trace streams into per-action samples.

For every agent command, emit one JSONL sample:
  {t, agent, context (last K chat lines), inv_before,
   action {cmd, args}, result, duration_ms,
   world_effects (block changes in the following WINDOW_S seconds)}

Usage: trace_to_dataset.py --trace <trace_dir> --out dataset.jsonl [--context 8] [--window 20]
"""
import argparse
import glob
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument('--trace', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--context', type=int, default=8)
ap.add_argument('--window', type=float, default=20.0)
args = ap.parse_args()


def load(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


world = load(os.path.join(args.trace, 'world_events.jsonl'))
blocks = [e for e in world if e['type'] == 'block']
chats = [e for e in world if e['type'] in ('chat', 'whisper')]

n = 0
with open(args.out, 'w') as out:
    for tr in glob.glob(os.path.join(args.trace, '*.trace.jsonl')):
        agent = os.path.basename(tr).split('.')[0]
        events = load(tr)
        inv = None
        for ev in events:
            if ev['type'] == 'inv':
                inv = ev['items']
            elif ev['type'] == 'cmd':
                ctx = [c for c in chats if c['t'] <= ev['t']][-args.context:]
                effects = [b for b in blocks if ev['t'] <= b['t'] <= ev['t'] + args.window * 1000]
                out.write(json.dumps({
                    't': ev['t'],
                    'agent': agent,
                    'context': [{'from': c['from'], 'text': c['text']} for c in ctx],
                    'inv_before': inv,
                    'action': {'cmd': ev['cmd'], 'args': ev.get('args')},
                    'duration_ms': ev.get('ms'),
                    'result': ev.get('result'),
                    'world_effects': [{k: b[k] for k in ('t', 'x', 'y', 'z', 'from', 'to')} for b in effects][:200],
                }, ensure_ascii=False) + '\n')
                n += 1
print(f'wrote {n} samples -> {args.out}')
