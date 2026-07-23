#!/usr/bin/env python3
"""Consume replay-timed NDJSON events and run causal shadow critic snapshots."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OFFLINE_DIR = HERE.parent / "offline_critic"
PROMPT_PATH = HERE / "critic_prompt.md"
SCHEMA_PATH = OFFLINE_DIR / "critic_output.schema.json"
RUNNER_PATH = OFFLINE_DIR / "run_critic.py"
BUILDER_PATH = OFFLINE_DIR / "build_windows.py"
TASK_COMMANDS = {"!goal", "!newAction"}
REQUEST_RE = re.compile(
    r"\b(?:can|could|would|will)\s+you\b|\bplease\b|\bhelp\b|\bneed\s+you\b",
    re.I,
)
ACK_RE = re.compile(
    r"\b(?:on it|got it|sure|okay|ok|i(?:'|’)ll|i will|handling|working on|almost there)\b",
    re.I,
)
CONTROL_COMMANDS = {
    "!goal",
    "!checkBlueprint",
    "!inventory",
    "!startConversation",
    "!endConversation",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_module("online_critic_runner", RUNNER_PATH)
BUILDER = load_module("online_critic_builder", BUILDER_PATH)


def evidence_ref(event: dict[str, Any]) -> str:
    return f"{event.get('source_file', 'replay')}:{event.get('source_line', '?')}"


def numeric_time(event: dict[str, Any]) -> float:
    value = event.get("relative_time_s")
    if not isinstance(value, (int, float)):
        raise ValueError(f"Replay event lacks relative_time_s: {event}")
    return float(value)


def inventory_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    items = set(before) | set(after)
    return {
        item: after.get(item, 0) - before.get(item, 0)
        for item in sorted(items)
        if after.get(item, 0) != before.get(item, 0)
    }


class ReplayState:
    def __init__(
        self,
        header: dict[str, Any],
        interval_s: float,
        message_count: int,
        on_snapshot: Callable[[dict[str, Any]], None],
        trigger_policy: str = "hybrid",
        action_lease_s: float = 135.0,
        request_ack_lease_s: float = 20.0,
        request_attempt_lease_s: float = 30.0,
        request_result_lease_s: float = 60.0,
        watchdog_interval_s: float = 120.0,
        min_trigger_gap_s: float = 20.0,
    ) -> None:
        self.header = header
        self.trial_id = header["trial_id"]
        self.agents = list(header.get("agents") or [])
        self.interval_s = interval_s
        self.message_limit = message_count
        self.trigger_policy = trigger_policy
        self.action_lease_s = action_lease_s
        self.request_ack_lease_s = request_ack_lease_s
        self.request_attempt_lease_s = request_attempt_lease_s
        self.request_result_lease_s = request_result_lease_s
        self.watchdog_interval_s = watchdog_interval_s
        self.min_trigger_gap_s = min_trigger_gap_s
        self.on_snapshot = on_snapshot
        self.live_from_s = float(header.get("replay_from_s", 0.0))
        self.replay_to_s = float(header.get("replay_to_s", header.get("trial_end_s", 0.0)))
        self.trial_end_s = float(header.get("trial_end_s", self.replay_to_s))

        self.window_start_s = 0.0
        self.next_time_cutoff_s = interval_s
        self.window_events: list[dict[str, Any]] = []
        self.window_message_count = 0
        self.latest_inventory = {agent: {} for agent in self.agents}
        self.window_start_inventory = {agent: {} for agent in self.agents}
        self.inventory_seen = {agent: False for agent in self.agents}
        self.active_commands: dict[str, dict[str, dict[str, Any]]] = {}
        self.latest_claim: dict[str, dict[str, Any] | None] = {
            agent: None for agent in self.agents
        }
        self.last_activity_s: dict[str, float | None] = {agent: None for agent in self.agents}
        self.last_position: dict[str, dict[str, Any] | None] = {
            agent: None for agent in self.agents
        }
        self.current_score: float | None = None
        self.window_start_score: float | None = None
        self.last_score_increase_s: float | None = None
        self.previous_score: float | None = None
        self.last_processed_s = 0.0
        self.snapshot_index = 0

        # Event watches live across critic snapshots. Snapshot windows are presentation
        # units; they must not erase an unresolved commitment or handoff.
        self.action_watches: dict[str, dict[str, Any]] = {}
        self.request_watches: dict[str, dict[str, Any]] = {}
        self.request_sequence = 0
        self.block_change_total = 0
        self.last_verifiable_progress_s: float | None = None
        self.score_high_watermark: float | None = None
        self.score_regression_open = False
        self.last_snapshot_s: float | None = None
        self.next_watchdog_s = watchdog_interval_s
        self.pending_candidates: list[dict[str, Any]] = []
        self.deferred_candidates: list[dict[str, Any]] = []
        self.deferred_deadline_s: float | None = None
        self.current_trigger_context: list[dict[str, Any]] = []
        self.task_activity_seen = False

        self.task = self._load_task_context()

    def _load_task_context(self) -> dict[str, Any]:
        trace_path = Path(self.header["trace_path"])
        meta_path = trace_path / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        task = BUILDER.load_task_index().get(meta.get("task_id"), {})
        return {
            "task_id": meta.get("task_id"),
            "group": meta.get("group"),
            "goal": BUILDER.truncate(task.get("goal"), 1200),
            "initial_team_instruction": BUILDER.truncate(task.get("conversation"), 500),
            "executor_count": len(self.agents),
        }

    def _should_submit(self, cutoff_s: float) -> bool:
        return cutoff_s > self.live_from_s + 1e-9 and cutoff_s <= self.replay_to_s + 1e-9

    def advance_before(self, event_time_s: float) -> None:
        if self.trigger_policy == "hybrid":
            while self.next_time_cutoff_s < event_time_s - 1e-9:
                self._trigger(self.next_time_cutoff_s, "time_interval")
            return
        self._advance_event_deadlines(event_time_s, inclusive=False)

    def process_event(self, event: dict[str, Any]) -> None:
        timestamp = numeric_time(event)
        self.last_processed_s = max(self.last_processed_s, timestamp)
        self.window_events.append(event)
        event_type = event.get("event_type")
        agent = event.get("agent")
        command = event.get("command")
        inventory_before: dict[str, Any] | None = None
        score_delta: float | None = None

        if event_type == "cmd_start" and agent:
            active = {
                "command_id": event.get("command_id"),
                "command": event.get("command"),
                "arguments": event.get("arguments") or [],
                "started_at_s": timestamp,
                "evidence": evidence_ref(event),
                "start_time_provenance": event.get("reconstruction_note"),
            }
            command_id = active.get("command_id")
            if command_id:
                self.active_commands.setdefault(agent, {})[command_id] = active
            self.last_activity_s[agent] = timestamp
            if event.get("command") in TASK_COMMANDS:
                args = event.get("arguments") or []
                current_claim = self.latest_claim.get(agent)
                if event.get("command") == "!newAction" or current_claim is None:
                    self.latest_claim[agent] = {
                        "time_s": timestamp,
                        "command": event.get("command"),
                        "text": BUILDER.truncate(args[0] if args else None, 900),
                        "command_executor": agent,
                        "evidence": evidence_ref(event),
                    }
        elif event_type == "cmd_end" and agent:
            active_for_agent = self.active_commands.get(agent)
            if active_for_agent:
                active_for_agent.pop(event.get("command_id"), None)
                if not active_for_agent:
                    self.active_commands.pop(agent, None)
            self.last_activity_s[agent] = timestamp
        elif event_type == "chat_out" and agent:
            self.last_activity_s[agent] = timestamp
            self.window_message_count += 1
        elif event_type == "inv" and agent:
            inventory_before = dict(self.latest_inventory.get(agent) or {})
            inventory = dict(event.get("items") or {})
            if not self.inventory_seen.get(agent):
                self.window_start_inventory[agent] = dict(inventory)
                self.inventory_seen[agent] = True
            self.latest_inventory[agent] = inventory
            self.last_activity_s[agent] = timestamp
        elif event_type == "pose" and agent in self.last_position:
            raw = event.get("raw_evidence") or {}
            self.last_position[agent] = {
                "x": raw.get("x"),
                "y": raw.get("y"),
                "z": raw.get("z"),
                "time_s": timestamp,
                "evidence": evidence_ref(event),
            }
            self.last_activity_s[agent] = timestamp
        elif event_type == "score":
            score = event.get("score")
            if isinstance(score, (int, float)):
                score = float(score)
                if self.previous_score is not None:
                    score_delta = score - self.previous_score
                if self.previous_score is None and self.window_start_score is None:
                    self.window_start_score = score
                if self.previous_score is not None and score > self.previous_score + 1e-9:
                    self.last_score_increase_s = timestamp
                self.previous_score = score
                self.current_score = score
        elif event_type == "block":
            self.block_change_total += 1

        if self.trigger_policy == "event_leases":
            self._process_event_watch(event, timestamp, inventory_before, score_delta)

    def finish_timestamp(self, timestamp: float) -> None:
        if self.trigger_policy == "hybrid":
            if self.window_message_count >= self.message_limit:
                self._trigger(timestamp, "message_count")
            elif abs(self.next_time_cutoff_s - timestamp) <= 1e-9:
                self._trigger(timestamp, "time_interval")
            return
        self._advance_event_deadlines(timestamp, inclusive=True)
        if self.pending_candidates:
            candidates = self.pending_candidates
            self.pending_candidates = []
            self._emit_or_defer(timestamp, candidates)

    def finish_replay(self, reached_s: float, completed_trial: bool) -> None:
        self.advance_before(reached_s + 1e-6)
        if completed_trial and self.window_start_s < reached_s - 1e-9:
            self._trigger(
                reached_s,
                "trial_end",
                terminal=True,
                trigger_context=[
                    {
                        "type": "terminal_review",
                        "observed_at_s": round(reached_s, 3),
                        "detail": "Retrospective review at the end of the revealed trial.",
                    }
                ],
            )

    def _trigger(
        self,
        cutoff_s: float,
        reason: str,
        terminal: bool = False,
        trigger_context: list[dict[str, Any]] | None = None,
    ) -> None:
        self.current_trigger_context = list(trigger_context or [])
        if self._should_submit(cutoff_s):
            self.snapshot_index += 1
            self.on_snapshot(self._packet(cutoff_s, reason, terminal))
        self.last_snapshot_s = cutoff_s
        self.window_start_s = cutoff_s
        if self.trigger_policy == "hybrid":
            self.next_time_cutoff_s = cutoff_s + self.interval_s
        else:
            self.next_watchdog_s = cutoff_s + self.watchdog_interval_s
        self.window_events = []
        self.window_message_count = 0
        self.window_start_inventory = {
            agent: dict(self.latest_inventory.get(agent) or {}) for agent in self.agents
        }
        self.window_start_score = self.current_score
        self.current_trigger_context = []

    @staticmethod
    def _candidate(
        candidate_type: str,
        observed_at_s: float,
        **values: Any,
    ) -> dict[str, Any]:
        return {
            "type": candidate_type,
            "observed_at_s": round(observed_at_s, 3),
            **values,
        }

    def _request_from_event(
        self, event: dict[str, Any], timestamp: float
    ) -> dict[str, Any] | None:
        sender = event.get("agent")
        recipient = None
        message = None
        if event.get("event_type") == "cmd_start" and event.get("command") == "!startConversation":
            args = event.get("arguments") or []
            if len(args) >= 2:
                recipient, message = args[0], str(args[1])
        elif event.get("event_type") == "chat_out":
            structured = BUILDER.structure_chat_out(
                {
                    "relative_time_s": timestamp,
                    "agent": sender,
                    "message": event.get("message"),
                    "raw_evidence": {"to": event.get("recipient")},
                    "source_file": event.get("source_file"),
                    "source_line": event.get("source_line"),
                }
            )
            recipient = structured.get("message_recipient")
            message = structured.get("message_text")
        if (
            not isinstance(sender, str)
            or not isinstance(recipient, str)
            or recipient not in self.agents
            or recipient == sender
            or not isinstance(message, str)
            or not REQUEST_RE.search(message)
        ):
            return None
        return {
            "sender": sender,
            "recipient": recipient,
            "message": BUILDER.truncate(message, 600),
            "evidence": evidence_ref(event),
        }

    def _open_request_watch(
        self, request: dict[str, Any], timestamp: float
    ) -> None:
        for watch in self.request_watches.values():
            if (
                not watch.get("closed")
                and watch["requester"] == request["sender"]
                and watch["recipient"] == request["recipient"]
                and timestamp - watch["opened_at_s"] < 2.0
            ):
                return
        self.request_sequence += 1
        watch_id = f"request_{self.request_sequence:03d}"
        self.request_watches[watch_id] = {
            "watch_id": watch_id,
            "kind": "coordination_request",
            "requester": request["sender"],
            "recipient": request["recipient"],
            "request_text": request["message"],
            "opened_at_s": timestamp,
            "request_evidence": request["evidence"],
            "score_at_open": self.current_score,
            "stage": "awaiting_ack",
            "deadline_s": timestamp + self.request_ack_lease_s,
            "ack_at_s": None,
            "ack_evidence": None,
            "claimed_attempt_evidence": None,
            "attempt_command_id": None,
            "attempt_started_at_s": None,
            "alerted": False,
            "closed": False,
            "resolution": None,
        }

    def _record_acknowledgement(self, event: dict[str, Any], timestamp: float) -> None:
        structured = BUILDER.structure_chat_out(
            {
                "relative_time_s": timestamp,
                "agent": event.get("agent"),
                "message": event.get("message"),
                "raw_evidence": {"to": event.get("recipient")},
                "source_file": event.get("source_file"),
                "source_line": event.get("source_line"),
            }
        )
        sender = structured.get("sender")
        recipient = structured.get("message_recipient")
        message = structured.get("message_text") or ""
        for watch in self.request_watches.values():
            if watch.get("closed") or watch.get("stage") != "awaiting_ack":
                continue
            if sender != watch["recipient"] or recipient != watch["requester"]:
                continue
            if ACK_RE.search(message):
                watch.update(
                    {
                        "stage": "awaiting_attempt",
                        "ack_at_s": timestamp,
                        "ack_evidence": structured.get("evidence"),
                        "deadline_s": timestamp + self.request_attempt_lease_s,
                    }
                )

    def _record_claimed_attempt(self, event: dict[str, Any], timestamp: float) -> None:
        structured = BUILDER.structure_chat_out(
            {
                "relative_time_s": timestamp,
                "agent": event.get("agent"),
                "message": event.get("message"),
                "raw_evidence": {"to": event.get("recipient")},
                "source_file": event.get("source_file"),
                "source_line": event.get("source_line"),
            }
        )
        if structured.get("local_command") in CONTROL_COMMANDS or not structured.get("local_command"):
            return
        for watch in self.request_watches.values():
            if (
                not watch.get("closed")
                and watch["recipient"] == event.get("agent")
                and timestamp >= watch["opened_at_s"]
            ):
                watch["claimed_attempt_evidence"] = structured.get("evidence")

    def _record_actual_attempt(self, event: dict[str, Any], timestamp: float) -> None:
        command = event.get("command")
        agent = event.get("agent")
        if not command or command in CONTROL_COMMANDS:
            return
        for watch in self.request_watches.values():
            if (
                watch.get("closed")
                or watch.get("attempt_command_id")
                or watch["recipient"] != agent
                or timestamp < watch["opened_at_s"]
            ):
                continue
            watch.update(
                {
                    "stage": "awaiting_result",
                    "attempt_command_id": event.get("command_id"),
                    "attempt_command": command,
                    "attempt_started_at_s": timestamp,
                    "attempt_evidence": evidence_ref(event),
                    "deadline_s": timestamp + self.request_result_lease_s,
                    "score_at_attempt": self.current_score,
                    "recipient_inventory_at_attempt": dict(
                        self.latest_inventory.get(agent) or {}
                    ),
                }
            )

    def _close_request(self, watch: dict[str, Any], resolution: str, timestamp: float) -> None:
        watch.update(
            {
                "closed": True,
                "stage": "closed",
                "deadline_s": None,
                "closed_at_s": timestamp,
                "resolution": resolution,
            }
        )

    def _request_candidate(
        self, candidate_type: str, watch: dict[str, Any], timestamp: float, **values: Any
    ) -> dict[str, Any]:
        return self._candidate(
            candidate_type,
            timestamp,
            watch_id=watch["watch_id"],
            requester=watch["requester"],
            recipient=watch["recipient"],
            opened_at_s=round(watch["opened_at_s"], 3),
            request_evidence=watch["request_evidence"],
            ack_evidence=watch.get("ack_evidence"),
            claimed_attempt_evidence=watch.get("claimed_attempt_evidence"),
            actual_attempt_evidence=watch.get("attempt_evidence"),
            **values,
        )

    def _action_progress(self, watch: dict[str, Any]) -> dict[str, Any]:
        score_start = watch.get("score_at_start")
        score_change = (
            self.current_score - score_start
            if self.current_score is not None and score_start is not None
            else None
        )
        inventory_changed = (
            dict(self.latest_inventory.get(watch["agent"]) or {})
            != watch.get("inventory_at_start", {})
        )
        return {
            "score_change_since_start": score_change,
            "score_progress_observed_since_start": bool(
                watch.get("score_progress_observed")
            ),
            "agent_inventory_changed_since_start": inventory_changed,
            "team_block_changes_since_start": self.block_change_total
            - watch.get("block_change_total_at_start", 0),
        }

    @staticmethod
    def _has_observed_progress(progress: dict[str, Any]) -> bool:
        score_change = progress.get("score_change_since_start")
        return bool(
            (isinstance(score_change, (int, float)) and score_change > 1e-9)
            or progress.get("score_progress_observed_since_start")
            or progress.get("agent_inventory_changed_since_start")
        )

    def _process_event_watch(
        self,
        event: dict[str, Any],
        timestamp: float,
        inventory_before: dict[str, Any] | None,
        score_delta: float | None,
    ) -> None:
        event_type = event.get("event_type")
        agent = event.get("agent")
        command = event.get("command")

        request = self._request_from_event(event, timestamp)
        if request:
            self._open_request_watch(request, timestamp)

        if event_type == "chat_out":
            self._record_acknowledgement(event, timestamp)
            self._record_claimed_attempt(event, timestamp)

        if event_type == "cmd_start" and agent:
            if command in TASK_COMMANDS:
                self.task_activity_seen = True
            if command == "!newAction" and event.get("command_id"):
                self.action_watches[event["command_id"]] = {
                    "watch_id": event["command_id"],
                    "kind": "task_action",
                    "agent": agent,
                    "command": command,
                    "arguments": BUILDER.truncate(
                        RUNNER.compact(event.get("arguments") or []), 500
                    ),
                    "opened_at_s": timestamp,
                    "deadline_s": timestamp + self.action_lease_s,
                    "evidence": evidence_ref(event),
                    "score_at_start": self.current_score,
                    "inventory_at_start": dict(self.latest_inventory.get(agent) or {}),
                    "block_change_total_at_start": self.block_change_total,
                    "score_progress_observed": False,
                    "alerted": False,
                }
            self._record_actual_attempt(event, timestamp)

        if event_type == "score" and isinstance(score_delta, (int, float)):
            if score_delta > 1e-9:
                self.last_verifiable_progress_s = timestamp
                for watch in self.action_watches.values():
                    if not watch.get("alerted"):
                        watch["score_progress_observed"] = True
                        watch["deadline_s"] = timestamp + self.action_lease_s
                for watch in self.request_watches.values():
                    score_at_open = watch.get("score_at_open")
                    if (
                        not watch.get("closed")
                        and isinstance(score_at_open, (int, float))
                        and isinstance(self.current_score, (int, float))
                        and self.current_score > score_at_open + 1e-9
                    ):
                        self._close_request(
                            watch,
                            "team_progress_after_request_observed_unattributed",
                            timestamp,
                        )

            if self.score_high_watermark is None:
                self.score_high_watermark = self.current_score
            elif (
                isinstance(self.current_score, (int, float))
                and self.current_score >= self.score_high_watermark - 1e-9
            ):
                self.score_high_watermark = max(self.score_high_watermark, self.current_score)
                self.score_regression_open = False
            elif score_delta < -1e-9 and not self.score_regression_open:
                self.score_regression_open = True
                self.pending_candidates.append(
                    self._candidate(
                        "score_regression",
                        timestamp,
                        before_score=round(float(event["score"] - score_delta), 6),
                        after_score=round(float(event["score"]), 6),
                        prior_high_watermark=round(float(self.score_high_watermark), 6),
                        evidence=evidence_ref(event),
                        attribution="unknown",
                    )
                )

        if event_type == "inv" and agent and inventory_before is not None:
            inventory_after = dict(event.get("items") or {})
            if inventory_after != inventory_before:
                self.last_verifiable_progress_s = timestamp
                for watch in self.action_watches.values():
                    if watch["agent"] == agent and not watch.get("alerted"):
                        watch["deadline_s"] = timestamp + self.action_lease_s

        if event_type == "cmd_end" and agent:
            command_id = event.get("command_id")
            action_watch = self.action_watches.pop(command_id, None)
            if action_watch:
                progress = self._action_progress(action_watch)
                outcome = BUILDER.command_outcome(event.get("result"))
                if outcome == "failure_or_blocked" or not self._has_observed_progress(progress):
                    self.pending_candidates.append(
                        self._candidate(
                            "action_closed_without_verified_progress",
                            timestamp,
                            watch_id=action_watch["watch_id"],
                            agent=agent,
                            opened_at_s=round(action_watch["opened_at_s"], 3),
                            elapsed_s=round(timestamp - action_watch["opened_at_s"], 3),
                            command_evidence=action_watch["evidence"],
                            result_evidence=evidence_ref(event),
                            recorded_outcome=outcome,
                            progress=progress,
                        )
                    )
                else:
                    self.last_verifiable_progress_s = timestamp

            for watch in self.request_watches.values():
                if watch.get("closed") or watch.get("attempt_command_id") != command_id:
                    continue
                score_at_attempt = watch.get("score_at_attempt")
                score_progress = (
                    self.current_score is not None
                    and score_at_attempt is not None
                    and self.current_score > score_at_attempt + 1e-9
                )
                inventory_progress = dict(self.latest_inventory.get(agent) or {}) != watch.get(
                    "recipient_inventory_at_attempt", {}
                )
                outcome = BUILDER.command_outcome(event.get("result"))
                if score_progress or inventory_progress:
                    self._close_request(watch, "team_or_recipient_progress_observed", timestamp)
                else:
                    watch["alerted"] = True
                    watch["deadline_s"] = None
                    self.pending_candidates.append(
                        self._request_candidate(
                            "request_attempt_closed_without_verified_result",
                            watch,
                            timestamp,
                            result_evidence=evidence_ref(event),
                            recorded_outcome=outcome,
                        )
                    )

            if command == "!checkBlueprint":
                result = str(event.get("result") or "")
                for watch in self.request_watches.values():
                    if (
                        watch.get("closed")
                        or watch.get("alerted")
                        or watch["requester"] != agent
                        or watch.get("ack_at_s") is None
                        or timestamp < watch["ack_at_s"]
                    ):
                        continue
                    if "requires the following fixes" in result:
                        watch["alerted"] = True
                        watch["stage"] = "verification_failed"
                        watch["deadline_s"] = None
                        self.pending_candidates.append(
                            self._request_candidate(
                                "request_verification_still_unresolved",
                                watch,
                                timestamp,
                                verification_evidence=evidence_ref(event),
                            )
                        )
                    elif "is complete" in result and "requires the following fixes" not in result:
                        self._close_request(watch, "requester_verification_complete", timestamp)

    def _next_event_deadline(self) -> float | None:
        deadlines: list[float] = [self.next_watchdog_s]
        deadlines.extend(
            float(watch["deadline_s"])
            for watch in self.action_watches.values()
            if not watch.get("alerted") and isinstance(watch.get("deadline_s"), (int, float))
        )
        deadlines.extend(
            float(watch["deadline_s"])
            for watch in self.request_watches.values()
            if not watch.get("closed")
            and not watch.get("alerted")
            and isinstance(watch.get("deadline_s"), (int, float))
        )
        if self.deferred_deadline_s is not None:
            deadlines.append(self.deferred_deadline_s)
        return min(deadlines) if deadlines else None

    def _due_candidates(self, cutoff_s: float) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if self.deferred_deadline_s is not None and self.deferred_deadline_s <= cutoff_s + 1e-9:
            candidates.extend(self.deferred_candidates)
            self.deferred_candidates = []
            self.deferred_deadline_s = None

        for watch in self.action_watches.values():
            deadline = watch.get("deadline_s")
            if watch.get("alerted") or not isinstance(deadline, (int, float)):
                continue
            if deadline <= cutoff_s + 1e-9:
                watch["alerted"] = True
                progress = self._action_progress(watch)
                candidates.append(
                    self._candidate(
                        "action_lease_expired_without_recent_progress",
                        cutoff_s,
                        watch_id=watch["watch_id"],
                        agent=watch["agent"],
                        opened_at_s=round(watch["opened_at_s"], 3),
                        elapsed_s=round(cutoff_s - watch["opened_at_s"], 3),
                        deadline_s=round(deadline, 3),
                        command_evidence=watch["evidence"],
                        progress=progress,
                    )
                )

        for watch in self.request_watches.values():
            deadline = watch.get("deadline_s")
            if (
                watch.get("closed")
                or watch.get("alerted")
                or not isinstance(deadline, (int, float))
                or deadline > cutoff_s + 1e-9
            ):
                continue
            watch["alerted"] = True
            stage = watch.get("stage")
            candidate_type = {
                "awaiting_ack": "request_ack_overdue",
                "awaiting_attempt": "request_actual_attempt_overdue",
                "awaiting_result": "request_result_overdue",
            }.get(stage, "request_lease_overdue")
            candidates.append(
                self._request_candidate(
                    candidate_type,
                    watch,
                    cutoff_s,
                    deadline_s=round(deadline, 3),
                )
            )

        if self.next_watchdog_s <= cutoff_s + 1e-9:
            progress_anchor = self.last_verifiable_progress_s
            if progress_anchor is not None and progress_anchor + self.watchdog_interval_s > cutoff_s:
                self.next_watchdog_s = progress_anchor + self.watchdog_interval_s
            elif self.task_activity_seen:
                candidates.append(
                    self._candidate(
                        "watchdog_no_verified_progress",
                        cutoff_s,
                        last_verifiable_progress_s=(
                            round(progress_anchor, 3) if progress_anchor is not None else None
                        ),
                        watchdog_interval_s=self.watchdog_interval_s,
                    )
                )
                self.next_watchdog_s = cutoff_s + self.watchdog_interval_s
            else:
                self.next_watchdog_s = cutoff_s + self.watchdog_interval_s
        return candidates

    def _advance_event_deadlines(self, target_s: float, inclusive: bool) -> None:
        while True:
            deadline = self._next_event_deadline()
            if deadline is None:
                return
            due = deadline <= target_s + 1e-9 if inclusive else deadline < target_s - 1e-9
            if not due:
                return
            candidates = self._due_candidates(deadline)
            if candidates:
                self._emit_or_defer(deadline, candidates)

    def _emit_or_defer(
        self, cutoff_s: float, candidates: list[dict[str, Any]]
    ) -> None:
        if not candidates:
            return
        earliest = (
            self.last_snapshot_s + self.min_trigger_gap_s
            if self.last_snapshot_s is not None
            else None
        )
        if earliest is not None and cutoff_s < earliest - 1e-9:
            self.deferred_candidates.extend(candidates)
            self.deferred_deadline_s = earliest
            return
        unique_types = list(dict.fromkeys(row["type"] for row in candidates))
        reason = unique_types[0] if len(unique_types) == 1 else "event_bundle"
        self._trigger(cutoff_s, reason, trigger_context=candidates)

    def _packet(self, cutoff_s: float, reason: str, terminal: bool) -> dict[str, Any]:
        event_counts = Counter(event.get("event_type") for event in self.window_events)
        message_timeline = []
        for event in self.window_events:
            if event.get("event_type") != "chat_out":
                continue
            structured = BUILDER.structure_chat_out(
                {
                    "relative_time_s": numeric_time(event),
                    "agent": event.get("agent"),
                    "message": event.get("message"),
                    "raw_evidence": {"to": event.get("recipient")},
                    "source_file": event.get("source_file"),
                    "source_line": event.get("source_line"),
                }
            )
            message_timeline.append(structured)

        agent_rows = []
        for agent in self.agents:
            active_for_agent = self.active_commands.get(agent) or {}
            active = max(
                active_for_agent.values(),
                key=lambda row: row["started_at_s"],
                default=None,
            )
            execution = {
                "status": "acting" if active else "no_active_command_observed",
                "command": active.get("command") if active else None,
                "arguments": (
                    BUILDER.truncate(RUNNER.compact(active.get("arguments") or []), 700)
                    if active
                    else None
                ),
                "started_at_s": active.get("started_at_s") if active else None,
                "elapsed_s": round(cutoff_s - active["started_at_s"], 3) if active else None,
                "evidence": active.get("evidence") if active else None,
                "start_time_provenance": active.get("start_time_provenance") if active else None,
            }
            agent_events = [event for event in self.window_events if event.get("agent") == agent]
            completed = [
                {
                    "time_s": numeric_time(event),
                    "command": event.get("command"),
                    "duration_ms": event.get("duration_ms"),
                    "outcome": BUILDER.command_outcome(event.get("result")),
                    "result_excerpt": BUILDER.truncate(event.get("result"), 260),
                    "evidence": evidence_ref(event),
                }
                for event in agent_events
                if event.get("event_type") == "cmd_end"
            ]
            last_activity = self.last_activity_s.get(agent)
            agent_rows.append(
                {
                    "agent": agent,
                    "current_execution": execution,
                    "latest_task_claim_at_cutoff": self.latest_claim.get(agent),
                    "inventory_at_window_start": self.window_start_inventory.get(agent) or {},
                    "inventory_at_cutoff": self.latest_inventory.get(agent) or {},
                    "inventory_net_change_in_window": inventory_delta(
                        self.window_start_inventory.get(agent) or {},
                        self.latest_inventory.get(agent) or {},
                    ),
                    "latest_position": self.last_position.get(agent),
                    "event_counts_in_window": dict(
                        sorted(Counter(event.get("event_type") for event in agent_events).items())
                    ),
                    "completed_commands_in_window": completed[-8:],
                    "last_observed_activity_s": last_activity,
                    "seconds_since_observed_activity": (
                        round(cutoff_s - last_activity, 3) if last_activity is not None else None
                    ),
                }
            )

        block_events = [event for event in self.window_events if event.get("event_type") == "block"]
        return {
            "schema_version": "online_replay_critic.v2",
            "critic_id": f"{self.trial_id}_online_t{round(cutoff_s * 1000):09d}",
            "trial_id": self.trial_id,
            "task": self.task,
            "window": {
                "start_s": round(self.window_start_s, 3),
                "end_s": round(cutoff_s, 3),
                "cutoff_s": round(cutoff_s, 3),
                "trigger_reason": reason,
                "is_terminal": terminal,
                "trigger_policy": {
                    "mode": self.trigger_policy,
                    "time_interval_s": self.interval_s,
                    "message_count": self.message_limit,
                    "action_lease_s": (
                        self.action_lease_s if self.trigger_policy == "event_leases" else None
                    ),
                    "request_ack_lease_s": (
                        self.request_ack_lease_s
                        if self.trigger_policy == "event_leases"
                        else None
                    ),
                    "request_attempt_lease_s": (
                        self.request_attempt_lease_s
                        if self.trigger_policy == "event_leases"
                        else None
                    ),
                    "request_result_lease_s": (
                        self.request_result_lease_s
                        if self.trigger_policy == "event_leases"
                        else None
                    ),
                    "watchdog_interval_s": (
                        self.watchdog_interval_s
                        if self.trigger_policy == "event_leases"
                        else None
                    ),
                    "min_trigger_gap_s": (
                        self.min_trigger_gap_s
                        if self.trigger_policy == "event_leases"
                        else None
                    ),
                },
            },
            "replay_context": {
                "mode": "causal_shadow_replay",
                "source_trace": self.header.get("trace_path"),
                "speed": self.header.get("speed"),
                "execution_state_note": (
                    "cmd_start is reconstructed from each recorded cmd end timestamp minus duration_ms, "
                    "then revealed to the critic only when the replay clock reaches that start. "
                    "Overlapping commands are tracked independently by command_id."
                ),
            },
            "message_timeline": message_timeline[-20:],
            "trigger_context": {
                "candidate_signals": self.current_trigger_context,
                "interpretation_note": (
                    "A trigger selects a moment for evaluation; it is not itself proof that "
                    "coordination is imbalanced or that an advisory should be sent."
                ),
            },
            "open_watches": {
                "task_actions": [
                    {
                        "watch_id": watch["watch_id"],
                        "agent": watch["agent"],
                        "opened_at_s": round(watch["opened_at_s"], 3),
                        "deadline_s": round(watch["deadline_s"], 3),
                        "evidence": watch["evidence"],
                        "alerted": bool(watch.get("alerted")),
                    }
                    for watch in self.action_watches.values()
                ],
                "coordination_requests": [
                    {
                        key: value
                        for key, value in watch.items()
                        if key
                        in {
                            "watch_id",
                            "requester",
                            "recipient",
                            "request_text",
                            "opened_at_s",
                            "request_evidence",
                            "stage",
                            "deadline_s",
                            "ack_at_s",
                            "ack_evidence",
                            "claimed_attempt_evidence",
                            "attempt_command",
                            "attempt_started_at_s",
                            "attempt_evidence",
                            "alerted",
                        }
                    }
                    for watch in self.request_watches.values()
                    if not watch.get("closed")
                ],
            },
            "agents": agent_rows,
            "team_observations": {
                "event_counts_in_window": dict(sorted(event_counts.items())),
                "score": {
                    "at_window_start": self.window_start_score,
                    "at_cutoff": self.current_score,
                    "change_in_window": (
                        self.current_score - self.window_start_score
                        if self.current_score is not None and self.window_start_score is not None
                        else None
                    ),
                    "last_observed_increase_s": self.last_score_increase_s,
                    "seconds_since_observed_increase": (
                        round(cutoff_s - self.last_score_increase_s, 3)
                        if self.last_score_increase_s is not None
                        else None
                    ),
                },
                "world_changes": {
                    "block_change_count": len(block_events),
                    "evidence_examples": [evidence_ref(event) for event in block_events[:6]],
                    "attribution_note": (
                        "Raw replay block changes are not assigned to an executor in this online snapshot."
                    ),
                },
            },
            "evidence_boundaries": [
                "The snapshot contains no event revealed after window.cutoff_s.",
                "An acting command is execution state, not proof of progress or eventual success.",
                "No active command observed is not sufficient by itself to label an executor idle.",
                "Message recipient and local command executor are separate fields.",
                "Replay block changes remain unattributed unless a separate reliable source identifies the executor.",
                "Event-lease trigger candidates schedule review and are not coordination verdicts.",
            ],
        }


class SnapshotEvaluator:
    def __init__(self, output: Path, dry_run: bool, timeout_s: float) -> None:
        self.output = output
        self.dry_run = dry_run
        self.timeout_s = timeout_s
        self.prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
        self.output_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        RUNNER.load_model_profile()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="online-critic")
        self.futures = []
        self.write_lock = threading.Lock()

    def submit(self, packet: dict[str, Any]) -> None:
        print(
            RUNNER.compact(
                {
                    "event": "critic_snapshot_submitted",
                    "critic_id": packet["critic_id"],
                    "cutoff_s": packet["window"]["cutoff_s"],
                    "active": [
                        row["agent"]
                        for row in packet["agents"]
                        if row["current_execution"]["status"] == "acting"
                    ],
                }
            ),
            flush=True,
        )
        self.futures.append(self.executor.submit(self._evaluate, packet))

    def _evaluate(self, packet: dict[str, Any]) -> None:
        record = {
            "critic_id": packet["critic_id"],
            "trial_id": packet["trial_id"],
            "window_end_s": packet["window"]["end_s"],
            "model": RUNNER.MODEL,
            "reasoning_effort": RUNNER.REASONING_EFFORT,
            "mode": "online_replay_shadow",
            "packet": packet,
        }
        try:
            if self.dry_run:
                record["status"] = "dry_run"
            else:
                prompt = RUNNER.build_prompt(self.prompt_template, packet, self.output_schema)
                result, elapsed_s = RUNNER.run_one(prompt, self.timeout_s)
                RUNNER.validate_identity(result, packet, self.output_schema)
                record.update(
                    {"status": "ok", "elapsed_s": round(elapsed_s, 3), "result": result}
                )
        except Exception as exc:
            record.update({"status": "error", "error": str(exc)})
        with self.write_lock:
            RUNNER.append_record(self.output, record)
        print(
            RUNNER.compact(
                {
                    "event": "critic_snapshot_completed",
                    "critic_id": packet["critic_id"],
                    "status": record["status"],
                    "verdict": (record.get("result") or {}).get("verdict"),
                }
            ),
            flush=True,
        )

    def close(self) -> None:
        for future in self.futures:
            future.result()
        self.executor.shutdown(wait=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-interval-s", type=float, default=90.0)
    parser.add_argument("--message-count", type=int, default=8)
    parser.add_argument(
        "--trigger-policy", choices=("hybrid", "event_leases"), default="hybrid"
    )
    parser.add_argument("--action-lease-s", type=float, default=135.0)
    parser.add_argument("--request-ack-lease-s", type=float, default=20.0)
    parser.add_argument("--request-attempt-lease-s", type=float, default=30.0)
    parser.add_argument("--request-result-lease-s", type=float, default=60.0)
    parser.add_argument("--watchdog-interval-s", type=float, default=120.0)
    parser.add_argument("--min-trigger-gap-s", type=float, default=20.0)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    positive_intervals = (
        args.time_interval_s,
        args.action_lease_s,
        args.request_ack_lease_s,
        args.request_attempt_lease_s,
        args.request_result_lease_s,
        args.watchdog_interval_s,
        args.min_trigger_gap_s,
    )
    if any(value <= 0 for value in positive_intervals) or args.message_count <= 0:
        parser.error("Trigger intervals must be positive")

    evaluator = SnapshotEvaluator(args.output, args.dry_run, args.timeout_s)
    state: ReplayState | None = None
    buffered_time: float | None = None
    buffered_events: list[dict[str, Any]] = []

    def flush_group() -> None:
        nonlocal buffered_time, buffered_events
        if state is None or buffered_time is None:
            return
        state.advance_before(buffered_time)
        for event in buffered_events:
            state.process_event(event)
        state.finish_timestamp(buffered_time)
        buffered_time = None
        buffered_events = []

    started = time.monotonic()
    for line_number, line in enumerate(sys.stdin, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid replay NDJSON at stdin:{line_number}: {exc}") from exc
        kind = row.get("kind")
        if kind == "replay_start":
            if state is not None:
                raise ValueError("Duplicate replay_start")
            state = ReplayState(
                row,
                interval_s=args.time_interval_s,
                message_count=args.message_count,
                on_snapshot=evaluator.submit,
                trigger_policy=args.trigger_policy,
                action_lease_s=args.action_lease_s,
                request_ack_lease_s=args.request_ack_lease_s,
                request_attempt_lease_s=args.request_attempt_lease_s,
                request_result_lease_s=args.request_result_lease_s,
                watchdog_interval_s=args.watchdog_interval_s,
                min_trigger_gap_s=args.min_trigger_gap_s,
            )
        elif kind == "event":
            if state is None:
                raise ValueError("event received before replay_start")
            timestamp = numeric_time(row)
            if buffered_time is not None and abs(timestamp - buffered_time) > 1e-9:
                flush_group()
            if buffered_time is None:
                buffered_time = timestamp
            buffered_events.append(row)
        elif kind == "replay_end":
            if state is None:
                raise ValueError("replay_end received before replay_start")
            flush_group()
            state.finish_replay(
                float(row.get("reached_relative_s", state.last_processed_s)),
                bool(row.get("completed_trial")),
            )

    flush_group()
    evaluator.close()
    print(
        RUNNER.compact(
            {
                "event": "online_replay_critic_finished",
                "elapsed_s": round(time.monotonic() - started, 3),
                "output": str(args.output),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
