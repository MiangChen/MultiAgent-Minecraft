from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_windows.py"
SPEC = importlib.util.spec_from_file_location("offline_critic_build_windows", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

RUNNER_PATH = Path(__file__).resolve().parents[1] / "run_critic.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("offline_critic_runner", RUNNER_PATH)
assert RUNNER_SPEC and RUNNER_SPEC.loader
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER)


def event(
    time_s: float,
    event_type: str,
    agent: str | None = None,
    line: int = 1,
    **extra,
):
    source = f"trace/{agent}.trace.jsonl" if agent else "trace/world_events.jsonl"
    return {
        "trial_id": "trial_999",
        "group": "test",
        "relative_time_s": time_s,
        "source_file": source,
        "source_line": line,
        "agent": agent,
        "event_type": event_type,
        **extra,
    }


class BoundaryTests(unittest.TestCase):
    def test_hybrid_uses_first_trigger_and_keeps_terminal_window(self):
        boundaries = MODULE.build_boundaries(
            [10, 20, 30, 40, 50],
            trial_end_s=100,
            trigger="hybrid",
            interval_s=60,
            message_count=3,
        )
        self.assertEqual([row["end_s"] for row in boundaries], [30, 90, 100])
        self.assertEqual(
            [row["trigger_reason"] for row in boundaries],
            ["message_count", "time_interval", "trial_end"],
        )

    def test_message_trigger_without_enough_messages_emits_terminal_only(self):
        boundaries = MODULE.build_boundaries(
            [10, 20],
            trial_end_s=45,
            trigger="messages",
            interval_s=60,
            message_count=3,
        )
        self.assertEqual(boundaries, [{
            "start_s": 0.0,
            "end_s": 45,
            "trigger_reason": "trial_end",
            "message_count": 2,
            "is_terminal": True,
        }])


class PacketTests(unittest.TestCase):
    def test_message_recipient_is_distinct_from_local_command_executor(self):
        routed = event(
            10,
            "chat_out",
            "andy",
            4,
            message='(To bob) I will handle the fixes. !newAction("fix two blocks")',
            raw_evidence={"type": "chat_out"},
        )
        structured = MODULE.structure_chat_out(routed)
        self.assertEqual(structured["sender"], "andy")
        self.assertEqual(structured["message_recipient"], "bob")
        self.assertEqual(structured["message_text"], "I will handle the fixes.")
        self.assertEqual(structured["local_command"], "!newAction")
        self.assertEqual(structured["command_executor"], "andy")
        self.assertEqual(structured["evidence"], "trace/andy.trace.jsonl:4")

    def test_explicit_trace_recipient_is_preserved_without_a_command(self):
        routed = event(
            10,
            "chat_out",
            "andy",
            5,
            message="Please bring quartz.",
            raw_evidence={"type": "chat_out", "to": "bob"},
        )
        structured = MODULE.structure_chat_out(routed)
        self.assertEqual(structured["message_recipient"], "bob")
        self.assertEqual(structured["message_text"], "Please bring quartz.")
        self.assertIsNone(structured["local_command"])
        self.assertIsNone(structured["command_executor"])

    def test_packet_excludes_future_claim_and_progress(self):
        events = [
            event(1, "cmd", "andy", 1, command="!goal", raw_evidence={"args": ["build base"]}),
            event(10, "chat_out", "andy", 2, message="I will build the base."),
            event(20, "chat_out", "bob", 2, message="I will gather blocks."),
            event(50, "chat_out", "andy", 3, message="Base in progress."),
            event(65, "cmd", "bob", 3, command="!newAction", raw_evidence={"args": ["future task"]}),
            event(
                70,
                "block",
                None,
                10,
                semantic={"scope": "blueprint_target", "world_change": "correct_placement"},
                attribution={"agent": "bob", "confidence": 0.9},
            ),
            event(100, "leave", "andy", 4),
        ]
        # Add a trace source for bob so infer_agents includes both workers.
        events.insert(1, event(2, "cmd", "bob", 1, command="!goal", raw_evidence={"args": ["gather"]}))
        packets = MODULE.build_packets_for_trial(
            "trial_999",
            events,
            {"task_id": "test", "group": "test"},
            {"goal": "build"},
            trigger="time",
            interval_s=60,
            message_count=8,
        )
        first = packets[0]
        bob = next(row for row in first["agents"] if row["agent"] == "bob")
        self.assertEqual(first["window"]["end_s"], 60)
        self.assertEqual(bob["latest_task_claim_at_cutoff"]["text"], "gather")
        self.assertEqual(first["team_observations"]["world_changes"]["target_changes_total"], 0)

    def test_low_confidence_world_change_is_not_assigned(self):
        events = [
            event(1, "cmd", "andy", 1, command="!goal", raw_evidence={"args": ["build"]}),
            event(1, "cmd", "bob", 1, command="!goal", raw_evidence={"args": ["build"]}),
            event(
                20,
                "block",
                None,
                5,
                semantic={"scope": "blueprint_target", "world_change": "correct_block_removed"},
                attribution={"agent": "andy", "confidence": 0.4},
            ),
            event(30, "leave", "andy", 6),
        ]
        packet = MODULE.build_packets_for_trial(
            "trial_999",
            events,
            {"task_id": "test", "group": "test"},
            {"goal": "build"},
        )[0]
        world = packet["team_observations"]["world_changes"]
        self.assertEqual(world["target_changes_total"], 1)
        self.assertEqual(world["confidently_attributed_changes"], 0)
        self.assertEqual(world["attribution_coverage"], 0.0)

    def test_first_window_score_change_uses_observed_samples(self):
        events = [
            event(1, "cmd", "andy", 1, command="!goal", raw_evidence={"args": ["build"]}),
            event(1, "cmd", "bob", 1, command="!goal", raw_evidence={"args": ["build"]}),
            event(2, "score", None, 1, score=0.0, source_file="trace/scores.tsv"),
            event(30, "score", None, 2, score=25.0, source_file="trace/scores.tsv"),
            event(60, "leave", "andy", 3),
        ]
        packet = MODULE.build_packets_for_trial(
            "trial_999",
            events,
            {"task_id": "test", "group": "test"},
            {"goal": "build"},
            trigger="time",
            interval_s=60,
        )[0]
        score = packet["team_observations"]["score"]
        self.assertIsNone(score["at_window_start"])
        self.assertEqual(score["change_between_window_observations"], 25.0)


class LocalSchemaTests(unittest.TestCase):
    def test_rejects_extra_keys_and_invalid_enum(self):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["verdict"],
            "properties": {"verdict": {"type": "string", "enum": ["unknown"]}},
        }
        RUNNER.validate_schema({"verdict": "unknown"}, schema)
        with self.assertRaisesRegex(ValueError, "additional keys"):
            RUNNER.validate_schema({"verdict": "unknown", "extra": True}, schema)
        with self.assertRaisesRegex(ValueError, "must be one of"):
            RUNNER.validate_schema({"verdict": "imbalanced"}, schema)

    def test_rejects_inconsistent_manager_advisory(self):
        schema = json.loads(RUNNER.SCHEMA_PATH.read_text(encoding="utf-8"))
        packet = {
            "critic_id": "trial_999_w001",
            "trial_id": "trial_999",
            "window": {"end_s": 60.0},
        }
        result = {
            "critic_id": "trial_999_w001",
            "trial_id": "trial_999",
            "window_end_s": 60.0,
            "verdict": "unknown",
            "imbalance_types": [],
            "confidence": 0.5,
            "observations": [],
            "agent_assessments": [{
                "agent": "andy",
                "load_state": "unknown",
                "summary": "Insufficient evidence.",
                "evidence": [],
            }],
            "manager_advisory": {
                "send": False,
                "priority": "monitor",
                "message": "",
            },
            "limitations": [],
        }
        with self.assertRaisesRegex(ValueError, "priority must be none"):
            RUNNER.validate_identity(result, packet, schema)


if __name__ == "__main__":
    unittest.main()
