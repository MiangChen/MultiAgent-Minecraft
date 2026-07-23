#!/usr/bin/env python3
"""Process trials 101-300 without modifying source traces.

The script deliberately keeps observation and interpretation separate. Unified
events contain source evidence and conservative block attribution. Commitments
and episodes add explicitly confidence-scored semantic interpretations.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = ROOT / "experiments" / "out"
ANALYSIS_ROOT = Path(__file__).resolve().parent
TRIAL_IDS = range(101, 301)
AGENT_TRACE_SUFFIX = ".trace.jsonl"
AIR = {"air", "cave_air", "void_air"}
ITEM_WORDS = {
    "wooden_pickaxe", "crafting_table", "oak_planks", "stick", "shears",
    "iron_ingot", "cyan_terracotta", "terracotta", "cyan_dye",
    "polished_granite", "polished_andesite", "polished_diorite", "stone",
    "stone_bricks", "gold_block", "quartz_block", "quartz_pillar", "glowstone",
}
FAIL_RE = re.compile(r"fail|error|cannot|could not|unable|not enough|no .+ found", re.I)
SUCCESS_RE = re.compile(r"success|crafted|placed|gave|complete", re.I)
SELF_FUTURE_RE = re.compile(
    r"\b(?:i(?:['’]ll| will| am going to| can| have to| need to)|let me|i['’]ve got .+ and (?:will|can)|"
    r"we(?:['’]ll| will| should| can| need to)|my (?:job|task|role) is|"
    r"(?:crafting|placing|sending|building|gathering|finishing|making) .{0,80} (?:now|next|first))\b", re.I
)
REQUEST_RE = re.compile(
    r"\b(?:can|could|would|will) you\b|\bplease\b|\bi need you to\b|\b(?:give|toss|bring|send|place|craft) me\b",
    re.I,
)
WAIT_RE = re.compile(r"\bwait(?:ing)?\b|\bhold on\b|\bstand by\b", re.I)
HELP_RE = re.compile(r"\bhelp\b|\bassist\b|\bneed .+ from you\b", re.I)
REFUSE_RE = re.compile(r"\b(?:can't|cannot|won't|unable|no spare|don't have|do not have)\b", re.I)


def compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"type": "parse_error", "raw_line": line.rstrip(), "t": None})
                row = rows[-1]
            row["_line"] = line_no
            rows.append(row)
    return rows


def base_block(name: str | None) -> str | None:
    return name.split("[", 1)[0] if name else name


def load_tasks() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    paths = list((ROOT / "experiments" / "tasks" / "matrix").glob("pyr_*.json"))
    paths += list((ROOT / "experiments" / "tasks" / "craft").glob("craft_*.json"))
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for task_id, task in data.items():
            if isinstance(task, dict) and "goal" in task:
                task = dict(task)
                task["_path"] = str(path.relative_to(ROOT))
                index[task_id] = task
    return index


def blueprint_map(task: dict[str, Any]) -> dict[tuple[int, int, int], str]:
    result: dict[tuple[int, int, int], str] = {}
    for level in task.get("blueprint", {}).get("levels", []):
        x0, y0, z0 = level["coordinates"]
        for dz, row in enumerate(level["placement"]):
            for dx, block in enumerate(row):
                if block != "air":
                    result[(x0 + dx, y0, z0 + dz)] = block
    return result


def evidence(source: str, row: dict[str, Any]) -> str:
    return f"{source}:{row.get('_line', '?')}"


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def normalize_t(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    value = int(value)
    while value > 10_000_000_000_000:
        value //= 1000
    return value if 1_000_000_000_000 <= value <= 9_999_999_999_999 else None


def coordinates(text: str) -> list[list[int]]:
    matches = re.findall(
        r"(?:X\s*:?\s*)?(-?\d+)\s*[, ]+\s*(?:Y\s*:?\s*)?(-?\d+)\s*[, ]+\s*(?:Z\s*:?\s*)?(-?\d+)",
        text,
        re.I,
    )
    return [[int(a), int(b), int(c)] for a, b, c in matches[:30]]


def mentioned_items(text: str) -> list[str]:
    lowered = text.lower().replace(" ", "_")
    return sorted(item for item in ITEM_WORDS if item in lowered)


def classify_message(text: str) -> list[str]:
    tags = []
    if REQUEST_RE.search(text):
        tags.append("request")
    if HELP_RE.search(text):
        tags.append("help")
    if WAIT_RE.search(text):
        tags.append("wait")
    if REFUSE_RE.search(text):
        tags.append("constraint_or_refusal")
    if SELF_FUTURE_RE.search(text):
        tags.append("prospective_claim")
    return tags


@dataclass
class TrialData:
    trial_id: str
    number: int
    path: Path
    meta: dict[str, Any]
    task: dict[str, Any]
    blueprint: dict[tuple[int, int, int], str]
    agents: list[str]
    agent_rows: dict[str, list[dict[str, Any]]]
    world_rows: list[dict[str, Any]]
    score_rows: list[dict[str, Any]]
    start_ms: int
    end_ms: int


def load_trial(number: int, tasks: dict[str, dict[str, Any]]) -> TrialData:
    path = OUT_ROOT / f"trial_{number}"
    trace = path / "trace"
    meta = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    agent_rows: dict[str, list[dict[str, Any]]] = {}
    for agent_path in sorted(trace.glob(f"*{AGENT_TRACE_SUFFIX}")):
        agent = agent_path.name.removesuffix(AGENT_TRACE_SUFFIX)
        rows = read_jsonl(agent_path)
        for row in rows:
            row["_source"] = f"trace/{agent_path.name}"
            row["_agent"] = agent
            row["_t"] = normalize_t(row.get("t"))
        agent_rows[agent] = rows
    world_rows = read_jsonl(trace / "world_events.jsonl")
    for row in world_rows:
        row["_source"] = "trace/world_events.jsonl"
        row["_t"] = normalize_t(row.get("t"))
    score_rows: list[dict[str, Any]] = []
    score_path = trace / "scores.tsv"
    if score_path.exists():
        with score_path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, 1):
                parts = line.rstrip().split("\t")
                if len(parts) < 2:
                    continue
                try:
                    row = {"t": int(parts[0]), "score": float(parts[1]), "type": "score", "_line": line_no}
                except ValueError:
                    continue
                row["_source"] = "trace/scores.tsv"
                row["_t"] = normalize_t(row["t"])
                score_rows.append(row)
    trace_start_times = [
        row["_t"] for rows in agent_rows.values() for row in rows
        if row.get("_t") and row.get("type") == "trace_start"
    ]
    candidate_times = trace_start_times
    if not candidate_times:
        candidate_times = [row["_t"] for row in world_rows if row.get("_t") and row.get("type") == "join"]
    if not candidate_times:
        candidate_times = [
            row["_t"] for rows in agent_rows.values() for row in rows if row.get("_t")
        ]
    start_ms = min(candidate_times)
    all_times = [
        row["_t"] for rows in agent_rows.values() for row in rows if row.get("_t")
    ] + [row["_t"] for row in world_rows if row.get("_t") and row["_t"] >= start_ms]
    if score_rows:
        all_times += [row["_t"] for row in score_rows if row.get("_t") and row["_t"] >= start_ms]
    end_ms = max(all_times)
    task = tasks[meta["task_id"]]
    return TrialData(
        trial_id=f"trial_{number}", number=number, path=path, meta=meta, task=task,
        blueprint=blueprint_map(task), agents=sorted(agent_rows), agent_rows=agent_rows,
        world_rows=world_rows, score_rows=score_rows, start_ms=start_ms, end_ms=end_ms,
    )


def pose_index(trial: TrialData) -> dict[str, tuple[list[int], list[dict[str, Any]]]]:
    result = {}
    for agent in trial.agents:
        rows = [r for r in trial.world_rows if r.get("type") == "pose" and r.get("name") == agent and r.get("_t")]
        result[agent] = ([r["_t"] for r in rows], rows)
    return result


def nearest_prior_pose(index: tuple[list[int], list[dict[str, Any]]], t: int) -> tuple[dict[str, Any] | None, int | None]:
    times, rows = index
    pos = bisect.bisect_right(times, t) - 1
    if pos < 0:
        return None, None
    return rows[pos], t - times[pos]


def command_windows(trial: TrialData) -> dict[str, list[tuple[int, int, dict[str, Any]]]]:
    windows: dict[str, list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
    for agent, rows in trial.agent_rows.items():
        for row in rows:
            if row.get("type") != "cmd" or not row.get("_t"):
                continue
            duration = max(0, int(row.get("ms") or 0))
            if duration >= 500:
                windows[agent].append((row["_t"] - duration, row["_t"], row))
    return windows


def attribute_block(
    trial: TrialData,
    row: dict[str, Any],
    poses: dict[str, tuple[list[int], list[dict[str, Any]]]],
    windows: dict[str, list[tuple[int, int, dict[str, Any]]]],
) -> dict[str, Any]:
    t = row["_t"]
    distances = []
    for agent in trial.agents:
        pose, age = nearest_prior_pose(poses[agent], t)
        if not pose or age is None or age > 3000:
            continue
        distance = math.dist((row["x"], row["y"], row["z"]), (pose["x"], pose["y"], pose["z"]))
        active = [
            wrow for start, end, wrow in windows.get(agent, []) if start - 1000 <= t <= end + 1000
        ]
        distances.append({
            "agent": agent, "distance_blocks": round(distance, 2), "pose_age_ms": age,
            "active_commands": [w.get("cmd") for w in active],
        })
    distances.sort(key=lambda x: x["distance_blocks"])
    chosen = None
    confidence = 0.0
    rationale = "no recent agent pose"
    if distances:
        first = distances[0]
        second_distance = distances[1]["distance_blocks"] if len(distances) > 1 else math.inf
        if first["distance_blocks"] <= 5.5 and second_distance - first["distance_blocks"] >= 1.5:
            chosen = first["agent"]
            has_window = bool(first["active_commands"])
            confidence = 0.9 if has_window and first["distance_blocks"] <= 4.5 else (0.75 if has_window else 0.6)
            rationale = "unique nearby agent" + (" with active command window" if has_window else "")
        elif first["distance_blocks"] <= 5.5:
            rationale = "multiple agents are similarly close"
        else:
            rationale = "no agent within 5.5 blocks"
    return {
        "agent": chosen,
        "confidence": confidence,
        "rationale": rationale,
        "candidates": distances,
        "time_window_ms": 3000,
        "distance_threshold_blocks": 5.5,
    }


def inventory_deltas(trial: TrialData) -> dict[tuple[str, int], dict[str, int]]:
    result: dict[tuple[str, int], dict[str, int]] = {}
    for agent, rows in trial.agent_rows.items():
        previous: dict[str, int] | None = None
        for row in rows:
            if row.get("type") != "inv" or not row.get("_t"):
                continue
            current = {k: int(v) for k, v in row.get("items", {}).items()}
            if previous is not None:
                keys = current.keys() | previous.keys()
                delta = {key: current.get(key, 0) - previous.get(key, 0) for key in keys}
                result[(agent, row["_t"])] = {k: v for k, v in delta.items() if v}
            else:
                result[(agent, row["_t"])] = {}
            previous = current
    return result


def score_changes(trial: TrialData) -> list[dict[str, Any]]:
    rows = []
    last_by_t: dict[int, dict[str, Any]] = {}
    for row in trial.score_rows:
        if row.get("_t") and row["_t"] >= trial.start_ms:
            last_by_t[row["_t"]] = row
    previous = None
    for row in sorted(last_by_t.values(), key=lambda r: r["_t"]):
        delta = None if previous is None else row["score"] - previous["score"]
        rows.append({**row, "delta": delta})
        previous = row
    return rows


def world_semantics(trial: TrialData, row: dict[str, Any]) -> dict[str, Any]:
    if row.get("type") != "block":
        return {}
    coord = (row["x"], row["y"], row["z"])
    expected = trial.blueprint.get(coord)
    old, new = base_block(row.get("from")), base_block(row.get("to"))
    if trial.blueprint:
        scope = "blueprint_target" if expected else (
            "blueprint_envelope" if -350 <= coord[0] <= -336 and 63 <= coord[1] <= 70 and 244 <= coord[2] <= 258
            else "environment"
        )
    else:
        scope = "near_agents_or_environment"
    change = "unclassified"
    if expected:
        if new == expected and old != expected:
            change = "correct_placement" if old in AIR else "correction"
        elif old == expected and new != expected:
            change = "correct_block_removed" if new in AIR else "correct_block_overwritten"
        elif old != expected and new != expected:
            change = "nonmatching_target_change"
    elif old in AIR and new not in AIR:
        change = "off_target_placement"
    elif old not in AIR and new in AIR:
        change = "off_target_removal"
    return {"scope": scope, "expected": expected, "world_change": change}


def unified_events(trial: TrialData) -> tuple[list[dict[str, Any]], dict[tuple[str, int], dict[str, int]]]:
    poses = pose_index(trial)
    windows = command_windows(trial)
    inv_deltas = inventory_deltas(trial)
    events = []
    raw_rows: list[dict[str, Any]] = []
    for rows in trial.agent_rows.values():
        raw_rows.extend(rows)
    raw_rows.extend(row for row in trial.world_rows if row.get("type") != "meta")
    raw_rows.extend(trial.score_rows)
    for row in raw_rows:
        t = row.get("_t")
        if not t or t < trial.start_ms - 1000:
            continue
        source = row["_source"]
        kind = row.get("type", "unknown")
        agent = row.get("_agent") or row.get("name") or row.get("from")
        message = row.get("text") if kind in {"chat", "whisper", "chat_out"} else None
        position = None
        if kind == "pose":
            position = {k: row.get(k) for k in ("x", "y", "z", "yaw", "pitch")}
        block_delta = None
        attribution = None
        semantic = {}
        if kind == "block":
            block_delta = {k: row.get(k) for k in ("x", "y", "z", "from", "to")}
            semantic = world_semantics(trial, row)
            attribution = attribute_block(trial, row, poses, windows)
            agent = attribution["agent"]
        inventory_delta = inv_deltas.get((row.get("_agent"), t)) if kind == "inv" else None
        events.append({
            "trial_id": trial.trial_id,
            "group": trial.meta["group"],
            "epoch_ms": t,
            "relative_time_s": round((t - trial.start_ms) / 1000, 3),
            "source_file": source,
            "source_line": row.get("_line"),
            "agent": agent,
            "event_type": kind,
            "command": row.get("cmd"),
            "message": message,
            "inventory_delta": inventory_delta,
            "position": position,
            "block_delta": block_delta,
            "score": row.get("score"),
            "semantic": semantic or None,
            "attribution": attribution,
            "raw_evidence": clean_row(row),
        })
    events.sort(key=lambda e: (e["epoch_ms"], e["source_file"], e["source_line"] or 0))
    return events, inv_deltas


def extract_recipient(text: str, agents: Iterable[str]) -> str | None:
    for agent in agents:
        if re.search(rf"\b{re.escape(agent)}\b", text, re.I):
            return agent
    return None


def canonical_agent(value: str | None, agents: Iterable[str]) -> str | None:
    if value is None:
        return None
    for agent in agents:
        if agent.lower() == value.lower():
            return agent
    return value


def extract_commitments(trial: TrialData, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_goals: set[tuple[str, str]] = set()
    seen_text: list[tuple[str, str, int]] = []
    for agent, rows in trial.agent_rows.items():
        for row in rows:
            if row.get("type") != "cmd" or not row.get("_t"):
                continue
            cmd = row.get("cmd")
            args = row.get("args") or []
            text = str(args[0]) if args else ""
            ctype = None
            recipient = None
            actor = agent
            confidence = 0.0
            declared_t = row["_t"]
            if cmd == "!goal" and text:
                key = (agent, text.strip().lower())
                if key in seen_goals:
                    continue
                seen_goals.add(key)
                ctype, confidence = "assigned_task_goal", 0.7
            elif cmd == "!newAction" and text:
                ctype, confidence = "self_action_commitment", 0.95
                declared_t = row["_t"] - max(0, int(row.get("ms") or 0))
            elif cmd == "!startConversation" and len(args) >= 2:
                recipient, text = canonical_agent(str(args[0]), trial.agents), str(args[1])
                if recipient == "[object Object]":
                    continue
                if REQUEST_RE.search(text):
                    ctype, confidence = "requested_commitment", 0.82
                    actor = recipient
                elif SELF_FUTURE_RE.search(text):
                    ctype, confidence = "dialogue_commitment", 0.78
            if not ctype:
                continue
            seen_text.append((agent, text.strip().lower(), declared_t))
            candidates.append({
                "speaker": agent, "agent": actor, "commitment_type": ctype,
                "declared_goal": text.strip(), "declared_t": declared_t,
                "source_file": row["_source"], "source_line": row["_line"],
                "source_event_t": row["_t"], "source_command": cmd,
                "intended_recipient": recipient,
                "semantic_confidence": confidence,
                "command_result": row.get("result"), "command_ms": row.get("ms"),
            })
    # Explicit natural-language commitments can precede a non-newAction command.
    for agent, rows in trial.agent_rows.items():
        for row in rows:
            if row.get("type") != "chat_out" or not row.get("_t"):
                continue
            full_text = str(row.get("text") or "")
            plain = full_text.split("!", 1)[0].replace(f"(To {agent})", "").strip()
            if len(plain) < 8 or not SELF_FUTURE_RE.search(plain):
                continue
            lowered = plain.lower()
            if any(a == agent and (lowered in txt or txt in lowered) and abs(row["_t"] - t) < 5000 for a, txt, t in seen_text):
                continue
            candidates.append({
                "speaker": agent, "agent": agent, "commitment_type": "dialogue_commitment",
                "declared_goal": plain, "declared_t": row["_t"],
                "source_file": row["_source"], "source_line": row["_line"],
                "source_event_t": row["_t"], "source_command": None,
                "intended_recipient": extract_recipient(full_text, (a for a in trial.agents if a != agent)),
                "semantic_confidence": 0.75, "command_result": None, "command_ms": None,
            })
    candidates.sort(key=lambda c: c["declared_t"])
    relevant_blocks = [
        e for e in events if e["event_type"] == "block" and e.get("semantic", {}).get("scope") == "blueprint_target"
    ]
    inv_events = [e for e in events if e["event_type"] == "inv" and e.get("inventory_delta")]
    score_events = [e for e in events if e["event_type"] == "score"]
    for idx, item in enumerate(candidates, 1):
        text = item["declared_goal"]
        start = item["declared_t"]
        next_same = next((c for c in candidates[idx:] if c["agent"] == item["agent"]), None)
        horizon = min(trial.end_ms, start + 120_000)
        if next_same:
            horizon = min(horizon, next_same["declared_t"])
        coords = coordinates(text)
        items = mentioned_items(text)
        agent = item["agent"]
        action_evidence = []
        for event in relevant_blocks:
            if start - 1000 <= event["epoch_ms"] <= horizon and event.get("agent") == agent:
                if not coords or [event["block_delta"][k] for k in ("x", "y", "z")] in coords:
                    action_evidence.append(event)
        for event in inv_events:
            if start - 1000 <= event["epoch_ms"] <= horizon and event.get("agent") == agent:
                if not items or any(name in event["inventory_delta"] for name in items):
                    action_evidence.append(event)
        command_result = str(item.get("command_result") or "")
        nearby_commands = [
            event for event in events
            if event["event_type"] == "cmd" and event.get("agent") == agent
            and start - 1000 <= event["epoch_ms"] <= min(trial.end_ms, start + 10_000)
            and event.get("command") in {"!craftRecipe", "!givePlayer", "!placeHere", "!useOn"}
        ]
        action_evidence.extend(nearby_commands)
        if item["source_command"] == "!newAction" and item.get("command_ms", 0) >= 500:
            follow = True
            follow_reason = "newAction entered an execution window"
        elif action_evidence:
            follow = True
            follow_reason = "matching inventory or attributed world action followed"
        else:
            follow = False
            follow_reason = "no matching observable action in the bounded window"
        completed = False
        if command_result and SUCCESS_RE.search(command_result) and not FAIL_RE.search(command_result):
            completed = True
        if any(
            SUCCESS_RE.search(str(event.get("raw_evidence", {}).get("result") or ""))
            and not FAIL_RE.search(str(event.get("raw_evidence", {}).get("result") or ""))
            for event in nearby_commands
        ):
            completed = True
        if items:
            for event in inv_events:
                if start <= event["epoch_ms"] <= trial.end_ms and event.get("agent") == agent:
                    if any(event["inventory_delta"].get(name, 0) > 0 for name in items):
                        completed = True
        if coords:
            matched_coords = {
                tuple(event["block_delta"][k] for k in ("x", "y", "z"))
                for event in relevant_blocks
                if start <= event["epoch_ms"] <= trial.end_ms
                and event.get("semantic", {}).get("world_change") in {"correct_placement", "correction"}
            }
            if all(tuple(coord) in matched_coords for coord in coords):
                completed = True
        if item["commitment_type"] == "assigned_task_goal":
            completed = any(
                e["event_type"] == "score" and e.get("score") == 100 for e in events
            ) or task_success_from_log(trial)
            follow = completed or bool(relevant_blocks) or any(
                e["event_type"] == "cmd" and e.get("command") == "!craftRecipe"
                for e in events
            )
            follow_reason = "task-directed world or crafting activity followed" if follow else follow_reason
        if completed:
            status, status_conf = "completed", 0.82 if (coords or items) else 0.68
        elif next_same and next_same["declared_t"] - start < 120_000:
            status, status_conf = "abandoned_or_revised", 0.62
        else:
            status, status_conf = "unknown", 0.45
        dependencies = []
        if re.search(r"\bif\b|\bafter\b|\bonce\b|\bwhen\b", text, re.I):
            dependencies.append("conditional_or_sequential")
        if re.search(r"\b(?:give|toss|bring|share|from|need .+ block|need .+ stick|need .+ ingot)\b", text, re.I):
            dependencies.append("resource_or_teammate")
        item.update({
            "trial_id": trial.trial_id, "group": trial.meta["group"],
            "commitment_id": f"{trial.trial_id}_c{idx:03d}",
            "declared_at_s": round((start - trial.start_ms) / 1000, 3),
            "revised_at_s": round((next_same["declared_t"] - trial.start_ms) / 1000, 3) if next_same else None,
            "target": {"objects_or_resources": items, "coordinates": coords},
            "expected_output": text,
            "dependency": dependencies,
            "status": status, "status_confidence": status_conf,
            "observable_follow_through": follow, "follow_through_reason": follow_reason,
            "supporting_evidence": [
                f"{item['source_file']}:{item['source_line']}"
            ] + [f"{e['source_file']}:{e['source_line']}" for e in action_evidence[:8]],
        })
        for key in ("declared_t", "source_event_t", "command_result", "command_ms"):
            item.pop(key, None)
    for item in candidates:
        relations = []
        for other in candidates:
            if other is item or other["agent"] == item["agent"]:
                continue
            if abs(other["declared_at_s"] - item["declared_at_s"]) > 45:
                continue
            item_targets = set(item["target"]["objects_or_resources"])
            other_targets = set(other["target"]["objects_or_resources"])
            item_coords = {tuple(x) for x in item["target"]["coordinates"]}
            other_coords = {tuple(x) for x in other["target"]["coordinates"]}
            item_text = item["declared_goal"].lower()
            other_text = other["declared_goal"].lower()
            relation = None
            rationale = None
            confidence = 0.0
            if item["commitment_type"] == "requested_commitment" or other["commitment_type"] == "requested_commitment":
                relation = "dependency"
                rationale = "one concurrent candidate assigns or requests work from the other agent"
                confidence = 0.82
            elif (item_coords & other_coords) or ("blueprint" in item_text and "blueprint" in other_text):
                relation = "overlapping_or_duplicate_scope"
                rationale = "concurrent commitments include the same coordinates or both claim the blueprint scope"
                confidence = 0.84
            elif item_targets and other_targets and not (item_targets & other_targets):
                relation = "potentially_complementary_scope"
                rationale = "concurrent commitments name disjoint observable resources or outputs"
                confidence = 0.62
            elif item_targets & other_targets:
                relation = "overlapping_or_duplicate_scope"
                rationale = "concurrent commitments name at least one common resource or output"
                confidence = 0.7
            if relation:
                relations.append({
                    "other_commitment_id": other["commitment_id"], "relation": relation,
                    "rationale": rationale, "confidence": confidence,
                })
        item["relation_to_concurrent_commitments"] = relations
    return candidates


def task_success_from_log(trial: TrialData) -> bool:
    path = trial.path / "run.log.gz"
    if not path.exists():
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return "Task finished: Task successful" in handle.read()
    except OSError:
        return False


def transfer_candidates(trial: TrialData, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transfers = []
    successful_gives = []
    for event in events:
        if event["event_type"] != "cmd" or event.get("command") != "!givePlayer":
            continue
        raw = event.get("raw_evidence", {})
        args = raw.get("args") or []
        result = str(raw.get("result") or "")
        if len(args) < 3 or not re.search(r"received|discarded", result, re.I) or FAIL_RE.search(result):
            continue
        recipient = canonical_agent(str(args[0]), trial.agents)
        try:
            amount = int(args[2])
        except (TypeError, ValueError):
            amount = None
        transfer = {
            "t": event["epoch_ms"], "from": event["agent"], "to": recipient,
            "item": str(args[1]), "amount": amount, "confidence": 0.96,
            "rationale": "successful givePlayer command result names the recipient and item",
            "evidence": [f"{event['source_file']}:{event['source_line']}"],
        }
        transfers.append(transfer)
        successful_gives.append(transfer)
    changes = []
    for event in events:
        if event["event_type"] != "inv" or not event.get("inventory_delta"):
            continue
        for item, delta in event["inventory_delta"].items():
            changes.append((event["epoch_ms"], event["agent"], item, delta, event))
    used = set()
    for i, (t1, a1, item1, d1, e1) in enumerate(changes):
        if d1 >= 0:
            continue
        for j, (t2, a2, item2, d2, e2) in enumerate(changes):
            if j in used or a1 == a2 or item1 != item2 or d2 <= 0 or abs(t2 - t1) > 8000:
                continue
            amount = min(-d1, d2)
            confirmed = next((
                tr for tr in successful_gives
                if tr["from"] == a1 and tr["to"] == a2 and tr["item"] == item1
                and abs(tr["t"] - max(t1, t2)) <= 12_000
            ), None)
            if confirmed:
                confirmed["evidence"] = sorted(set(confirmed["evidence"] + [
                    f"{e1['source_file']}:{e1['source_line']}", f"{e2['source_file']}:{e2['source_line']}"
                ]))
                confirmed["rationale"] += "; matched inventory loss/gain also observed"
                used.add(j)
                break
            transfers.append({
                "t": max(t1, t2), "from": a1, "to": a2, "item": item1, "amount": amount,
                "confidence": 0.42,
                "rationale": "coincident inventory loss/gain within 8 seconds without a give command; crafting or pickup is a plausible alternative",
                "evidence": [f"{e1['source_file']}:{e1['source_line']}", f"{e2['source_file']}:{e2['source_line']}"],
            })
            used.add(j)
            break
    return transfers


def make_episodes(
    trial: TrialData, events: list[dict[str, Any]], commitments: list[dict[str, Any]], transfers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    boundaries: list[tuple[int, str, str]] = [(trial.start_ms, "trial_start", "start")]
    for commitment in commitments:
        t = trial.start_ms + round(commitment["declared_at_s"] * 1000)
        boundaries.append((t, "commitment", commitment["commitment_id"]))
    for transfer in transfers:
        boundaries.append((transfer["t"], "resource_transfer", transfer["item"]))
    scores = [e for e in events if e["event_type"] == "score" and e.get("score") is not None]
    prior = None
    last_change = None
    for event in scores:
        if prior is not None and event["score"] != prior["score"]:
            delta = event["score"] - prior["score"]
            boundaries.append((event["epoch_ms"], "progress_change", f"{delta:+.3f}"))
            if last_change and event["epoch_ms"] - last_change > 60_000:
                boundaries.append((last_change + 60_000, "progress_plateau", ">60s"))
            last_change = event["epoch_ms"]
        elif prior is None:
            last_change = event["epoch_ms"]
        prior = event
    for event in events:
        if event["event_type"] == "block" and event.get("semantic", {}).get("world_change") in {
            "correct_block_removed", "correct_block_overwritten"
        }:
            boundaries.append((event["epoch_ms"], "correct_state_lost", f"{event['source_file']}:{event['source_line']}"))
        if event["event_type"] in {"chat", "chat_out", "whisper"} and event.get("message"):
            tags = classify_message(event["message"])
            if any(tag in tags for tag in ("help", "wait", "constraint_or_refusal")):
                boundaries.append((event["epoch_ms"], "interaction_shift", ",".join(tags)))
        if event["event_type"] in {"leave"}:
            boundaries.append((event["epoch_ms"], "agent_leave", str(event.get("agent"))))
    boundaries.append((trial.end_ms, "trial_end", "end"))
    boundaries.sort()
    clustered: list[dict[str, Any]] = []
    for t, kind, detail in boundaries:
        if clustered and t - clustered[-1]["t"] <= 2500:
            clustered[-1]["reasons"].append({"kind": kind, "detail": detail})
        else:
            clustered.append({"t": t, "reasons": [{"kind": kind, "detail": detail}]})
    episodes = []
    for idx in range(len(clustered) - 1):
        start, end = clustered[idx]["t"], clustered[idx + 1]["t"]
        if end <= start:
            continue
        window = [e for e in events if start <= e["epoch_ms"] < end]
        active_commitments = [
            c for c in commitments
            if trial.start_ms + round(c["declared_at_s"] * 1000) <= start
            and (c["revised_at_s"] is None or trial.start_ms + round(c["revised_at_s"] * 1000) > start)
        ]
        commands = [e for e in window if e["event_type"] == "cmd"]
        blocks = [e for e in window if e["event_type"] == "block" and e.get("semantic", {}).get("scope") == "blueprint_target"]
        inv = [e for e in window if e["event_type"] == "inv" and e.get("inventory_delta")]
        messages = [e for e in window if e["event_type"] == "chat_out" and e.get("message")]
        episode_transfers = [tr for tr in transfers if start <= tr["t"] < end]
        score_values = [e["score"] for e in window if e["event_type"] == "score" and e.get("score") is not None]
        block_counts = Counter(e.get("semantic", {}).get("world_change") for e in blocks)
        participants = sorted({e["agent"] for e in commands + blocks + inv + messages if e.get("agent")})
        outcomes = []
        if score_values:
            delta = score_values[-1] - score_values[0]
            if delta > 0:
                outcomes.append("progress_increase")
            elif delta < 0:
                outcomes.append("progress_decrease")
        if block_counts["correct_block_removed"] or block_counts["correct_block_overwritten"]:
            outcomes.append("correct_state_lost")
        if block_counts["correct_placement"] or block_counts["correction"]:
            outcomes.append("correct_state_added")
        if episode_transfers:
            outcomes.append("resource_transfer_candidate")
        if not outcomes and not commands and not messages:
            outcomes.append("observable_inactivity_or_unlogged_activity")
        key_evidence = []
        for event in (messages[:4] + commands[:4] + blocks[:6] + inv[:4]):
            key_evidence.append(f"{event['source_file']}:{event['source_line']}")
        episodes.append({
            "trial_id": trial.trial_id, "group": trial.meta["group"],
            "episode_id": f"{trial.trial_id}_e{len(episodes)+1:03d}",
            "start_s": round((start - trial.start_ms) / 1000, 3),
            "end_s": round((end - trial.start_ms) / 1000, 3),
            "boundary_reason": clustered[idx]["reasons"],
            "participants": participants,
            "entering_commitments": [c["commitment_id"] for c in active_commitments],
            "actual_actions": [
                {"agent": e["agent"], "command": e["command"], "relative_time_s": e["relative_time_s"],
                 "evidence": f"{e['source_file']}:{e['source_line']}"} for e in commands[:30]
            ],
            "world_changes": dict(block_counts),
            "resource_changes": [
                {"agent": e["agent"], "delta": e["inventory_delta"], "relative_time_s": e["relative_time_s"],
                 "evidence": f"{e['source_file']}:{e['source_line']}"} for e in inv[:30]
            ],
            "transfer_candidates": episode_transfers,
            "messages": [
                {"agent": e["agent"], "message": e["message"][:500], "relative_time_s": e["relative_time_s"],
                 "tags": classify_message(e["message"]), "evidence": f"{e['source_file']}:{e['source_line']}"}
                for e in messages[:20]
            ],
            "teammate_effect": {
                "attributed_correct_changes_by_agent": dict(Counter(
                    e["agent"] for e in blocks
                    if e.get("agent") and e.get("semantic", {}).get("world_change") in {"correct_placement", "correction"}
                )),
                "attributed_losses_by_agent": dict(Counter(
                    e["agent"] for e in blocks
                    if e.get("agent") and e.get("semantic", {}).get("world_change") in {"correct_block_removed", "correct_block_overwritten"}
                )),
                "score_start": score_values[0] if score_values else None,
                "score_end": score_values[-1] if score_values else None,
            },
            "episode_result": outcomes or ["unknown"],
            "evidence_positions": key_evidence,
            "semantic_confidence": 0.75 if key_evidence else 0.4,
            "phenomenon_labels": [],
        })
    return episodes


def summarize_trial(
    trial: TrialData, events: list[dict[str, Any]], commitments: list[dict[str, Any]],
    episodes: list[dict[str, Any]], transfers: list[dict[str, Any]],
) -> dict[str, Any]:
    scores = [e["score"] for e in events if e["event_type"] == "score" and e.get("score") is not None]
    relevant = [e for e in events if e["event_type"] == "block" and e.get("semantic", {}).get("scope") == "blueprint_target"]
    changes = [e.get("semantic", {}).get("world_change") for e in relevant]
    attributed_correct = Counter(
        e["agent"] for e in relevant
        if e.get("agent") and e.get("semantic", {}).get("world_change") in {"correct_placement", "correction"}
    )
    total_attr = sum(attributed_correct.values())
    concentration = max(attributed_correct.values(), default=0) / total_attr if total_attr else None
    success = task_success_from_log(trial)
    target = trial.task.get("target")
    target_gains = 0
    if target:
        target_gains = sum(
            max(0, (e.get("inventory_delta") or {}).get(target, 0))
            for e in events if e["event_type"] == "inv"
        )
    successful_target_crafts = [
        e for e in events if e["event_type"] == "cmd" and e.get("command") == "!craftRecipe"
        and target and str((e.get("raw_evidence", {}).get("args") or [None])[0]) == target
        and re.search(rf"Successfully crafted {re.escape(target)}", str(e.get("raw_evidence", {}).get("result") or ""), re.I)
    ]
    parse_errors = sum(e["event_type"] == "parse_error" for e in events)
    block_total = sum(e["event_type"] == "block" for e in events)
    unattributed_relevant = sum(e.get("agent") is None for e in relevant)
    return {
        "trial_id": trial.trial_id, "group": trial.meta["group"], "agents": ",".join(trial.agents),
        "duration_s": round((trial.end_ms - trial.start_ms) / 1000, 3),
        "success_from_run_log": success,
        "final_score": scores[-1] if scores else None, "peak_score": max(scores) if scores else None,
        "target_inventory_gain": target_gains,
        "successful_target_craft_commands": len(successful_target_crafts),
        "successful_target_crafters": ",".join(sorted({e["agent"] for e in successful_target_crafts})),
        "messages": sum(e["event_type"] == "chat_out" for e in events),
        "commands": sum(e["event_type"] == "cmd" for e in events),
        "commitments": len(commitments),
        "commitment_follow_through_rate": round(sum(c["observable_follow_through"] for c in commitments) / len(commitments), 3) if commitments else None,
        "episodes": len(episodes), "transfer_candidates": len(transfers),
        "blueprint_correct_additions": changes.count("correct_placement") + changes.count("correction"),
        "blueprint_correct_losses": changes.count("correct_block_removed") + changes.count("correct_block_overwritten"),
        "blueprint_attributed_correct_by_agent": compact(attributed_correct),
        "max_agent_share_of_attributed_correct": round(concentration, 3) if concentration is not None else None,
        "relevant_blocks_unattributed": unattributed_relevant,
        "relevant_blocks_total": len(relevant), "world_blocks_total": block_total,
        "parse_errors": parse_errors,
        "score_rows": len(scores),
        "meta_timestamp_raw": trial.meta.get("start_epoch_ms"), "derived_start_epoch_ms": trial.start_ms,
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(compact(row) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=101)
    parser.add_argument("--end", type=int, default=300)
    parser.add_argument("--output", type=Path, default=ANALYSIS_ROOT / "derived")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    unified_path = args.output / "unified_events.jsonl"
    ledger_path = args.output / "commitment_ledger.jsonl"
    episode_path = args.output / "coordination_episodes.jsonl"
    summaries = []
    quality = []
    with unified_path.open("w", encoding="utf-8") as unified_handle, \
            ledger_path.open("w", encoding="utf-8") as ledger_handle, \
            episode_path.open("w", encoding="utf-8") as episode_handle:
        for number in range(args.start, args.end + 1):
            trial = load_trial(number, tasks)
            events, _ = unified_events(trial)
            commitments = extract_commitments(trial, events)
            transfers = transfer_candidates(trial, events)
            episodes = make_episodes(trial, events, commitments, transfers)
            summary = summarize_trial(trial, events, commitments, episodes, transfers)
            summaries.append(summary)
            for row in events:
                unified_handle.write(compact(row) + "\n")
            for row in commitments:
                ledger_handle.write(compact(row) + "\n")
            for row in episodes:
                episode_handle.write(compact(row) + "\n")
            quality.append({
                "trial_id": trial.trial_id,
                "meta_timestamp_digits": len(str(trial.meta.get("start_epoch_ms", ""))),
                "derived_start_epoch_ms": trial.start_ms,
                "event_count": len(events),
                "parse_errors": summary["parse_errors"],
                "relevant_block_attribution_rate": round(
                    1 - summary["relevant_blocks_unattributed"] / summary["relevant_blocks_total"], 3
                ) if summary["relevant_blocks_total"] else None,
                "missing_scores": not bool(trial.score_rows),
                "missing_run_log": not (trial.path / "run.log.gz").exists(),
            })
            print(f"{trial.trial_id}: {len(events)} events, {len(commitments)} commitments, {len(episodes)} episodes")
    if summaries:
        with (args.output / "trial_summary.tsv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summaries[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(summaries)
    write_jsonl(args.output / "quality_report.jsonl", quality)


if __name__ == "__main__":
    main()
