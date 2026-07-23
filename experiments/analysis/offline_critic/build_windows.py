#!/usr/bin/env python3
"""Build causal evidence windows for the offline coordination critic.

The input is the existing unified event stream. Source traces are never edited.
Each packet contains only evidence observable at or before its cutoff.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = (
    ROOT
    / "experiments"
    / "analysis"
    / "open_world_coordination"
    / "derived"
    / "unified_events.jsonl"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "derived" / "critic_windows.jsonl"
TASK_COMMANDS = {"!goal", "!newAction"}
SUCCESS_RE = re.compile(r"success|crafted|placed|gave|received|complete", re.I)
FAILURE_RE = re.compile(r"fail|error|cannot|could not|unable|not enough|no .+ found", re.I)
TRIAL_RE = re.compile(r"^trial_(\d+)$")
TRACE_AGENT_RE = re.compile(r"^trace/([^/]+)\.trace\.jsonl$")
DIRECT_MESSAGE_PREFIX_RE = re.compile(r"^\(To\s+([^)]+)\)\s*", re.I)
LOCAL_COMMAND_RE = re.compile(r"(?<![A-Za-z0-9_])(![A-Za-z][A-Za-z0-9_]*)")


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def truncate(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def evidence_ref(event: dict[str, Any]) -> str:
    return f"{event.get('source_file', 'unknown')}:{event.get('source_line', '?')}"


def structure_chat_out(event: dict[str, Any]) -> dict[str, Any]:
    """Separate routed-message metadata from a command executed by the sender."""
    sender = event.get("agent")
    raw_message = str(event.get("message") or "").strip()
    prefix_match = DIRECT_MESSAGE_PREFIX_RE.match(raw_message)
    prefix_recipient = prefix_match.group(1).strip() if prefix_match else None
    content = raw_message[prefix_match.end() :].lstrip() if prefix_match else raw_message

    raw_recipient = (event.get("raw_evidence") or {}).get("to")
    recipient = raw_recipient.strip() if isinstance(raw_recipient, str) else prefix_recipient
    command_match = LOCAL_COMMAND_RE.search(content)
    if command_match:
        message_text = content[: command_match.start()].strip()
        local_command = command_match.group(1)
        local_command_text = truncate(content[command_match.start() :].strip(), 1000)
        command_executor = sender
    else:
        message_text = content
        local_command = None
        local_command_text = None
        command_executor = None

    return {
        "time_s": relative_time(event),
        "sender": sender,
        "message_recipient": recipient,
        "message_text": truncate(message_text, 1000),
        "local_command": local_command,
        "local_command_text": local_command_text,
        "command_executor": command_executor,
        "evidence": evidence_ref(event),
    }


def trial_number(trial_id: str) -> int:
    match = TRIAL_RE.match(trial_id)
    if not match:
        raise ValueError(f"Invalid trial id: {trial_id}")
    return int(match.group(1))


def iter_trial_events(
    path: Path, start_trial: int, end_trial: int
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Stream the large unified JSONL file one trial at a time."""
    current_id: str | None = None
    current_events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            event_trial_id = event.get("trial_id")
            if not isinstance(event_trial_id, str):
                raise ValueError(f"Missing trial_id at {path}:{line_number}")
            if current_id is not None and event_trial_id != current_id:
                if start_trial <= trial_number(current_id) <= end_trial:
                    yield current_id, current_events
                current_events = []
            current_id = event_trial_id
            if start_trial <= trial_number(event_trial_id) <= end_trial:
                current_events.append(event)
    if current_id is not None and start_trial <= trial_number(current_id) <= end_trial:
        yield current_id, current_events


def load_task_index() -> dict[str, dict[str, Any]]:
    task_index: dict[str, dict[str, Any]] = {}
    task_paths = sorted((ROOT / "experiments" / "tasks" / "matrix").glob("pyr_*.json"))
    task_paths += sorted((ROOT / "experiments" / "tasks" / "craft").glob("craft_*.json"))
    for path in task_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for task_id, task in data.items():
            if isinstance(task, dict) and "goal" in task:
                task_index[task_id] = task
    return task_index


def load_trial_context(
    trial_id: str, task_index: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_path = ROOT / "experiments" / "out" / trial_id / "trace" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta, task_index.get(meta.get("task_id"), {})


def infer_agents(events: Iterable[dict[str, Any]]) -> list[str]:
    agents: set[str] = set()
    for event in events:
        source = event.get("source_file")
        if isinstance(source, str):
            match = TRACE_AGENT_RE.match(source)
            if match:
                agents.add(match.group(1))
    return sorted(agents)


def relative_time(event: dict[str, Any]) -> float | None:
    value = event.get("relative_time_s")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def build_boundaries(
    message_times: list[float],
    trial_end_s: float,
    trigger: str,
    interval_s: float,
    message_count: int,
) -> list[dict[str, Any]]:
    """Return consecutive windows; hybrid uses whichever trigger arrives first."""
    if trigger not in {"time", "messages", "hybrid"}:
        raise ValueError(f"Unsupported trigger: {trigger}")
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if message_count <= 0:
        raise ValueError("message_count must be positive")

    times = sorted(t for t in message_times if 0 <= t <= trial_end_s)
    boundaries: list[dict[str, Any]] = []
    start_s = 0.0
    next_message_index = 0
    epsilon = 1e-9

    while start_s + epsilon < trial_end_s:
        while next_message_index < len(times) and times[next_message_index] <= start_s + epsilon:
            next_message_index += 1

        time_candidate = math.inf
        if trigger in {"time", "hybrid"}:
            time_candidate = start_s + interval_s

        message_candidate = math.inf
        if trigger in {"messages", "hybrid"}:
            index = next_message_index + message_count - 1
            if index < len(times):
                message_candidate = times[index]

        candidate = min(time_candidate, message_candidate, trial_end_s)
        if candidate >= trial_end_s - epsilon:
            end_s = trial_end_s
            reason = "trial_end"
        elif message_candidate <= time_candidate:
            end_s = message_candidate
            reason = "message_count"
        else:
            end_s = time_candidate
            reason = "time_interval"

        if end_s <= start_s + epsilon:
            raise RuntimeError(f"Non-advancing critic window at {start_s}")
        count_in_window = sum(start_s < t <= end_s + epsilon for t in times)
        boundaries.append(
            {
                "start_s": round(start_s, 3),
                "end_s": round(end_s, 3),
                "trigger_reason": reason,
                "message_count": count_in_window,
                "is_terminal": reason == "trial_end",
            }
        )
        start_s = end_s
        while next_message_index < len(times) and times[next_message_index] <= end_s + epsilon:
            next_message_index += 1

    return boundaries


def command_outcome(result: str | None) -> str:
    if not result:
        return "not_recorded"
    if FAILURE_RE.search(result):
        return "failure_or_blocked"
    if SUCCESS_RE.search(result):
        return "reported_success"
    return "unclear"


def score_summary(
    scores: list[dict[str, Any]], start_s: float, end_s: float
) -> dict[str, Any]:
    causal = [event for event in scores if (relative_time(event) or 0.0) <= end_s]
    in_window = [
        event
        for event in causal
        if relative_time(event) is not None
        and start_s <= relative_time(event) <= end_s
        and isinstance(event.get("score"), (int, float))
    ]

    def last_at_or_before(cutoff: float) -> float | None:
        values = [
            float(event["score"])
            for event in causal
            if relative_time(event) is not None
            and relative_time(event) <= cutoff
            and isinstance(event.get("score"), (int, float))
        ]
        return values[-1] if values else None

    start_score = last_at_or_before(start_s)
    end_score = last_at_or_before(end_s)
    delta = None if start_score is None or end_score is None else end_score - start_score
    first_window_score = float(in_window[0]["score"]) if in_window else None
    last_window_score = float(in_window[-1]["score"]) if in_window else None

    previous: float | None = None
    last_increase_s: float | None = None
    for event in causal:
        value = event.get("score")
        timestamp = relative_time(event)
        if not isinstance(value, (int, float)) or timestamp is None:
            continue
        value = float(value)
        if previous is not None and value > previous + 1e-9:
            last_increase_s = timestamp
        previous = value

    return {
        "at_window_start": start_score,
        "at_cutoff": end_score,
        "change_in_window": delta,
        "first_observed_in_window": first_window_score,
        "last_observed_in_window": last_window_score,
        "change_between_window_observations": (
            last_window_score - first_window_score
            if first_window_score is not None and last_window_score is not None
            else None
        ),
        "last_observed_increase_s": round(last_increase_s, 3) if last_increase_s is not None else None,
        "seconds_since_observed_increase": (
            round(end_s - last_increase_s, 3) if last_increase_s is not None else None
        ),
    }


def summarize_world_changes(
    window_events: list[dict[str, Any]], agents: list[str]
) -> tuple[dict[str, Any], dict[str, Counter[str]]]:
    counts: Counter[str] = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)
    by_agent: dict[str, Counter[str]] = {agent: Counter() for agent in agents}
    relevant_total = 0
    confidently_attributed = 0

    for event in window_events:
        if event.get("event_type") != "block":
            continue
        semantic = event.get("semantic") or {}
        if semantic.get("scope") != "blueprint_target":
            continue
        change = semantic.get("world_change") or "unknown_target_change"
        relevant_total += 1
        counts[change] += 1
        if len(evidence[change]) < 5:
            evidence[change].append(evidence_ref(event))

        attribution = event.get("attribution") or {}
        attributed_agent = attribution.get("agent") or event.get("agent")
        confidence = attribution.get("confidence")
        if (
            attributed_agent in by_agent
            and isinstance(confidence, (int, float))
            and confidence >= 0.65
        ):
            confidently_attributed += 1
            by_agent[attributed_agent][change] += 1

    return (
        {
            "target_change_counts": dict(sorted(counts.items())),
            "evidence_examples": dict(sorted(evidence.items())),
            "target_changes_total": relevant_total,
            "confidently_attributed_changes": confidently_attributed,
            "attribution_coverage": (
                round(confidently_attributed / relevant_total, 3) if relevant_total else None
            ),
            "attribution_note": (
                "Only nearest-pose attributions with confidence >= 0.65 are assigned to an agent; "
                "unattributed changes must not be used to assign responsibility."
            ),
        },
        by_agent,
    )


def summarize_agent(
    agent: str,
    history_events: list[dict[str, Any]],
    window_events: list[dict[str, Any]],
    by_agent_world: Counter[str],
    cutoff_s: float,
) -> dict[str, Any]:
    agent_history = [event for event in history_events if event.get("agent") == agent]
    agent_window = [event for event in window_events if event.get("agent") == agent]
    commands = [event for event in agent_window if event.get("event_type") == "cmd"]
    inventory_history = [event for event in agent_history if event.get("event_type") == "inv"]
    inventory_window = [event for event in agent_window if event.get("event_type") == "inv"]
    claims = [
        event
        for event in agent_history
        if event.get("event_type") == "cmd" and event.get("command") in TASK_COMMANDS
    ]

    latest_claim = None
    if claims:
        claim = claims[-1]
        args = (claim.get("raw_evidence") or {}).get("args") or []
        latest_claim = {
            "time_s": relative_time(claim),
            "command": claim.get("command"),
            "text": truncate(args[0] if args else None, 900),
            "evidence": evidence_ref(claim),
        }

    command_records = []
    for event in commands:
        raw = event.get("raw_evidence") or {}
        result = raw.get("result")
        command_records.append(
            {
                "time_s": relative_time(event),
                "command": event.get("command"),
                "arguments": truncate(compact(raw.get("args") or []), 700),
                "outcome": command_outcome(result),
                "result_excerpt": truncate(result, 260),
                "duration_ms": raw.get("ms"),
                "evidence": evidence_ref(event),
            }
        )

    net_inventory: Counter[str] = Counter()
    inventory_events = []
    for event in inventory_window:
        delta = event.get("inventory_delta") or {}
        for item, amount in delta.items():
            if isinstance(amount, (int, float)):
                net_inventory[item] += amount
        if delta:
            inventory_events.append(
                {
                    "time_s": relative_time(event),
                    "delta": delta,
                    "evidence": evidence_ref(event),
                }
            )

    activity_times = [
        relative_time(event)
        for event in agent_history
        if event.get("event_type") in {"cmd", "chat_out"}
        or (event.get("event_type") == "inv" and event.get("inventory_delta"))
    ]
    last_activity_s = max((t for t in activity_times if t is not None), default=None)

    return {
        "agent": agent,
        "latest_task_claim_at_cutoff": latest_claim,
        "initial_observed_inventory": (
            (inventory_history[0].get("raw_evidence") or {}).get("items")
            if inventory_history
            else None
        ),
        "latest_observed_inventory": (
            (inventory_history[-1].get("raw_evidence") or {}).get("items")
            if inventory_history
            else None
        ),
        "message_count_in_window": sum(
            event.get("event_type") == "chat_out" for event in agent_window
        ),
        "command_count_in_window": len(commands),
        "command_counts": dict(sorted(Counter(event.get("command") for event in commands).items())),
        "command_evidence": command_records,
        "inventory_net_change_in_window": {
            item: amount for item, amount in sorted(net_inventory.items()) if amount != 0
        },
        "inventory_change_evidence": inventory_events[:12],
        "confidently_attributed_target_changes": dict(sorted(by_agent_world.items())),
        "last_recorded_message_command_or_inventory_change_s": (
            round(last_activity_s, 3) if last_activity_s is not None else None
        ),
        "seconds_since_recorded_message_command_or_inventory_change": (
            round(cutoff_s - last_activity_s, 3) if last_activity_s is not None else None
        ),
    }


def build_packets_for_trial(
    trial_id: str,
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    task: dict[str, Any],
    trigger: str = "hybrid",
    interval_s: float = 90.0,
    message_count: int = 8,
) -> list[dict[str, Any]]:
    agents = infer_agents(events)
    if not agents:
        raise ValueError(f"No executor agents found for {trial_id}")
    timed_events = [event for event in events if relative_time(event) is not None]
    trial_end_s = max((relative_time(event) or 0.0 for event in timed_events), default=0.0)
    if trial_end_s <= 0:
        raise ValueError(f"No positive-duration evidence for {trial_id}")
    messages = [
        event
        for event in timed_events
        if event.get("event_type") == "chat_out" and (relative_time(event) or -1) >= 0
    ]
    boundaries = build_boundaries(
        [relative_time(event) or 0.0 for event in messages],
        trial_end_s,
        trigger,
        interval_s,
        message_count,
    )
    scores = [event for event in timed_events if event.get("event_type") == "score"]
    packets = []

    for index, boundary in enumerate(boundaries, 1):
        start_s = boundary["start_s"]
        end_s = boundary["end_s"]
        history = [event for event in timed_events if (relative_time(event) or 0.0) <= end_s]
        window = [
            event
            for event in timed_events
            if 0 <= (relative_time(event) or 0.0) <= end_s
            and (
                (index == 1 and (relative_time(event) or 0.0) >= start_s)
                or (index > 1 and (relative_time(event) or 0.0) > start_s)
            )
        ]
        window_messages = sorted(
            (event for event in window if event.get("event_type") == "chat_out"),
            key=lambda event: relative_time(event) or 0.0,
        )
        world_summary, by_agent_world = summarize_world_changes(window, agents)
        agent_summaries = [
            summarize_agent(agent, history, window, by_agent_world[agent], end_s)
            for agent in agents
        ]
        event_counts = Counter(event.get("event_type") for event in window)

        packets.append(
            {
                "schema_version": "offline_critic_window.v2",
                "critic_id": f"{trial_id}_w{index:03d}",
                "trial_id": trial_id,
                "group": meta.get("group") or (events[0].get("group") if events else None),
                "task": {
                    "task_id": meta.get("task_id"),
                    "goal": truncate(task.get("goal"), 1200),
                    "initial_team_instruction": truncate(task.get("conversation"), 500),
                    "executor_count": len(agents),
                },
                "window": {
                    **boundary,
                    "cutoff_s": end_s,
                    "trigger_policy": {
                        "mode": trigger,
                        "time_interval_s": interval_s,
                        "message_count": message_count,
                    },
                },
                "message_timeline": [structure_chat_out(event) for event in window_messages],
                "agents": agent_summaries,
                "team_observations": {
                    "event_counts_in_window": dict(sorted(event_counts.items())),
                    "score": score_summary(scores, start_s, end_s),
                    "world_changes": world_summary,
                },
                "evidence_boundaries": [
                    "The packet contains no event after window.cutoff_s.",
                    "Agent chat and command claims are observations of statements, not proof of completion.",
                    "Activity volume alone is not collaboration quality or workload balance.",
                    "Pose-based block attribution is conservative and may remain unknown.",
                    "A concentrated workload can be legitimate specialization or a task phase; infer imbalance only with contextual evidence.",
                    "In message_timeline, message_recipient is only the routed audience; command_executor is the agent that locally executes local_command. Do not infer delegation from the recipient.",
                ],
            }
        )
    return packets


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(compact(row) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=int, default=101)
    parser.add_argument("--end", type=int, default=300)
    parser.add_argument("--trigger", choices=("time", "messages", "hybrid"), default="hybrid")
    parser.add_argument("--time-interval-s", type=float, default=90.0)
    parser.add_argument("--message-count", type=int, default=8)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start must be <= --end")

    task_index = load_task_index()
    total_trials = 0
    total_windows = 0
    trigger_counts: Counter[str] = Counter()

    def packets() -> Iterator[dict[str, Any]]:
        nonlocal total_trials, total_windows
        for trial_id, events in iter_trial_events(args.input, args.start, args.end):
            meta, task = load_trial_context(trial_id, task_index)
            trial_packets = build_packets_for_trial(
                trial_id,
                events,
                meta,
                task,
                trigger=args.trigger,
                interval_s=args.time_interval_s,
                message_count=args.message_count,
            )
            total_trials += 1
            total_windows += len(trial_packets)
            trigger_counts.update(packet["window"]["trigger_reason"] for packet in trial_packets)
            yield from trial_packets

    written = write_jsonl(args.output, packets())
    print(
        compact(
            {
                "output": str(args.output),
                "trials": total_trials,
                "windows": total_windows,
                "written": written,
                "trigger_counts": dict(sorted(trigger_counts.items())),
            }
        )
    )


if __name__ == "__main__":
    main()
