#!/usr/bin/env python3
"""Detect Task-score drops (demolition events) from a mindcraft run.

Modes:
  --log <run.log>          sequence-only backtest (no timestamps)
  --tsv <score_timeline.tsv>  epoch_ms<TAB>score lines (from the run watcher)
"""
import argparse
import re
import sys

THRESH = 0.3  # percent-points; one pyramid block ~= 0.6


def parse_log(path):
    seq = []
    pat = re.compile(r'Task score: ([0-9.]+)')
    with open(path, errors='replace') as f:
        for line in f:
            m = pat.search(line)
            if m:
                seq.append((None, float(m.group(1))))
    return seq


def parse_tsv(path):
    seq = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) == 2:
                try:
                    seq.append((int(parts[0]), float(parts[1])))
                except ValueError:
                    continue
    return seq


def find_drops(seq):
    drops = []
    prev = None
    for i, (ts, s) in enumerate(seq):
        if prev is not None and s < 1 and prev[1] > 50:
            continue  # unloaded-chunk artifact: restarted agent reads the site as all-air (score ~0)
        if prev is not None and s < prev[1] - THRESH:
            drops.append({'idx': i, 'epoch_ms': ts, 'from': prev[1], 'to': s})
        prev = (ts, s)
    return drops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log')
    ap.add_argument('--tsv')
    args = ap.parse_args()
    seq = parse_log(args.log) if args.log else parse_tsv(args.tsv)
    if not seq:
        print('NO_DATA')
        return 1
    drops = find_drops(seq)
    peak = max(s for _, s in seq)
    final = seq[-1][1]
    print(f'samples={len(seq)} peak={peak:.1f} final={final:.1f} drops={len(drops)}')
    for d in drops:
        ts = d['epoch_ms']
        print(f"DROP idx={d['idx']} epoch_ms={ts} {d['from']:.2f} -> {d['to']:.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
