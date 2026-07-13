#!/usr/bin/env python3
"""Tail a mindcraft run log, timestamp every Task-score line into a tsv."""
import re
import sys
import time

path_in, path_out = sys.argv[1], sys.argv[2]
pat = re.compile(r'Task score: ([0-9.]+)')
# wait for the log file to appear
while True:
    try:
        f = open(path_in, errors='replace')
        break
    except FileNotFoundError:
        time.sleep(0.5)
with f, open(path_out, 'a', buffering=1) as out:
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.2)
            continue
        m = pat.search(line)
        if m:
            out.write(f"{int(time.time() * 1000)}\t{m.group(1)}\n")
