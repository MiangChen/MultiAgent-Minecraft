#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "replay_critic.py"


def load_module():
    spec = importlib.util.spec_from_file_location("replay_critic_under_test", MODULE_PATH)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot import {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CRITIC = load_module()


class ReplayStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.trace_path = Path(self.temp_dir.name)
        self.snapshots: list[dict] = []
        self.state = CRITIC.ReplayState(
            {
                "trial_id": "trial_test",
                "trace_path": str(self.trace_path),
                "agents": ["andy", "bob"],
                "trial_end_s": 300.0,
                "replay_from_s": 0.0,
                "replay_to_s": 300.0,
                "speed": 1.0,
            },
            interval_s=180.0,
            message_count=999,
            on_snapshot=self.snapshots.append,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def event(event_type: str, time_s: float, agent: str, **values):
        return {
            "kind": "event",
            "event_type": event_type,
            "relative_time_s": time_s,
            "agent": agent,
            "source_file": f"trace/{agent}.trace.jsonl",
            "source_line": 11,
            **values,
        }

    def test_active_command_is_visible_at_cutoff_without_future_result(self) -> None:
        start = self.event(
            "cmd_start",
            97.86,
            "bob",
            command="!newAction",
            arguments=["Build the remaining structure"],
            command_id="trace/bob.trace.jsonl:11",
            reconstruction_note="Reconstructed start",
        )
        self.state.process_event(start)
        self.state.advance_before(180.001)

        self.assertEqual(len(self.snapshots), 1)
        packet = self.snapshots[0]
        bob = next(row for row in packet["agents"] if row["agent"] == "bob")
        self.assertEqual(bob["current_execution"]["status"], "acting")
        self.assertEqual(bob["current_execution"]["command"], "!newAction")
        self.assertAlmostEqual(bob["current_execution"]["elapsed_s"], 82.14)
        self.assertEqual(bob["completed_commands_in_window"], [])
        self.assertNotIn("future success", json.dumps(packet))

    def test_only_matching_command_end_clears_active_state(self) -> None:
        self.state.process_event(
            self.event(
                "cmd_start",
                97.86,
                "bob",
                command="!newAction",
                arguments=[],
                command_id="trace/bob.trace.jsonl:11",
            )
        )
        self.state.process_event(
            self.event(
                "cmd_end",
                120.0,
                "bob",
                command="!newAction",
                command_id="trace/bob.trace.jsonl:99",
                duration_ms=1,
                result="unrelated",
            )
        )
        self.assertIn("bob", self.state.active_commands)

        self.state.process_event(
            self.event(
                "cmd_end",
                236.759,
                "bob",
                command="!newAction",
                command_id="trace/bob.trace.jsonl:11",
                duration_ms=138899,
                result="future success",
            )
        )
        self.assertNotIn("bob", self.state.active_commands)

    def test_instant_goal_does_not_hide_long_action_or_replace_specific_claim(self) -> None:
        self.state.process_event(
            self.event(
                "cmd_start",
                12.59,
                "bob",
                command="!newAction",
                arguments=["Build the full blueprint"],
                command_id="trace/bob.trace.jsonl:14",
            )
        )
        self.state.process_event(
            self.event(
                "cmd_start",
                25.711,
                "bob",
                command="!goal",
                arguments=["Make a structure with the blueprint below"],
                command_id="trace/bob.trace.jsonl:7",
            )
        )
        self.state.process_event(
            self.event(
                "cmd_end",
                25.711,
                "bob",
                command="!goal",
                command_id="trace/bob.trace.jsonl:7",
                duration_ms=0,
            )
        )

        packet = self.state._packet(73.693, "test", False)
        bob = next(row for row in packet["agents"] if row["agent"] == "bob")
        self.assertEqual(bob["current_execution"]["status"], "acting")
        self.assertEqual(bob["current_execution"]["command"], "!newAction")
        self.assertAlmostEqual(bob["current_execution"]["elapsed_s"], 61.103)
        self.assertEqual(bob["latest_task_claim_at_cutoff"]["command"], "!newAction")
        self.assertEqual(bob["latest_task_claim_at_cutoff"]["text"], "Build the full blueprint")

    def test_message_recipient_does_not_change_command_executor(self) -> None:
        self.state.process_event(
            self.event(
                "chat_out",
                42.0,
                "andy",
                message='(To bob) !newAction("Finish the blueprint")',
                recipient=None,
            )
        )
        packet = self.state._packet(60.0, "test", False)
        message = packet["message_timeline"][0]
        self.assertEqual(message["message_recipient"], "bob")
        self.assertEqual(message["local_command"], "!newAction")
        self.assertEqual(message["command_executor"], "andy")

    def test_first_inventory_and_score_observations_become_window_baselines(self) -> None:
        self.state.process_event(
            self.event("inv", 5.0, "andy", items={"stone": 12, "diamond_pickaxe": 1})
        )
        self.state.process_event(
            {
                "kind": "event",
                "event_type": "score",
                "relative_time_s": 5.0,
                "agent": None,
                "source_file": "trace/scores.tsv",
                "source_line": 1,
                "score": 2.5,
            }
        )
        packet = self.state._packet(20.0, "test", False)
        andy = next(row for row in packet["agents"] if row["agent"] == "andy")
        self.assertEqual(andy["inventory_at_window_start"], andy["inventory_at_cutoff"])
        self.assertEqual(andy["inventory_net_change_in_window"], {})
        self.assertEqual(packet["team_observations"]["score"]["at_window_start"], 2.5)
        self.assertEqual(packet["team_observations"]["score"]["change_in_window"], 0.0)


class EventLeaseReplayStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.trace_path = Path(self.temp_dir.name)
        self.snapshots: list[dict] = []
        self.state = CRITIC.ReplayState(
            {
                "trial_id": "trial_test",
                "trace_path": str(self.trace_path),
                "agents": ["andy", "bob"],
                "trial_end_s": 300.0,
                "replay_from_s": 0.0,
                "replay_to_s": 300.0,
                "speed": 1.0,
            },
            interval_s=90.0,
            message_count=8,
            on_snapshot=self.snapshots.append,
            trigger_policy="event_leases",
            action_lease_s=10.0,
            request_ack_lease_s=5.0,
            request_attempt_lease_s=10.0,
            request_result_lease_s=15.0,
            watchdog_interval_s=100.0,
            min_trigger_gap_s=1.0,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def event(event_type: str, time_s: float, agent: str | None, **values):
        source_agent = agent or "world"
        return {
            "kind": "event",
            "event_type": event_type,
            "relative_time_s": time_s,
            "agent": agent,
            "source_file": f"trace/{source_agent}.trace.jsonl",
            "source_line": 11,
            **values,
        }

    def test_unproductive_running_action_triggers_at_lease_deadline(self) -> None:
        self.state.process_event(
            self.event(
                "cmd_start",
                2.0,
                "bob",
                command="!newAction",
                arguments=["Build"],
                command_id="bob:11",
            )
        )
        self.state.advance_before(12.001)

        self.assertEqual(len(self.snapshots), 1)
        packet = self.snapshots[0]
        self.assertEqual(packet["window"]["trigger_reason"], "action_lease_expired_without_recent_progress")
        self.assertEqual(
            packet["trigger_context"]["candidate_signals"][0]["watch_id"], "bob:11"
        )
        bob = next(row for row in packet["agents"] if row["agent"] == "bob")
        self.assertEqual(bob["current_execution"]["status"], "acting")

    def test_observed_progress_extends_action_lease_and_closes_without_review(self) -> None:
        self.state.process_event(self.event("score", 1.0, None, score=0.0))
        self.state.process_event(
            self.event(
                "cmd_start",
                2.0,
                "bob",
                command="!newAction",
                arguments=["Build"],
                command_id="bob:11",
            )
        )
        self.state.process_event(self.event("score", 9.0, None, score=1.0))
        self.state.advance_before(18.5)
        self.assertEqual(self.snapshots, [])

        self.state.process_event(
            self.event(
                "cmd_end",
                19.0,
                "bob",
                command="!newAction",
                command_id="bob:11",
                duration_ms=17000,
                result="completed",
            )
        )
        self.state.finish_timestamp(19.0)
        self.assertEqual(self.snapshots, [])

    def test_claimed_command_does_not_satisfy_request_without_cmd_start(self) -> None:
        self.state.process_event(
            self.event(
                "cmd_start",
                10.0,
                "andy",
                command="!startConversation",
                arguments=["bob", "Can you help gather and place the missing blocks?"],
                command_id="andy:11",
            )
        )
        self.state.process_event(
            self.event(
                "chat_out",
                12.0,
                "bob",
                message="(To andy) On it, I will handle the blocks. !checkBlueprint",
                recipient=None,
            )
        )
        self.state.process_event(
            self.event(
                "chat_out",
                15.0,
                "bob",
                message='(To andy) Almost there. !newAction("Finish it")',
                recipient=None,
            )
        )
        self.state.advance_before(22.001)

        self.assertEqual(len(self.snapshots), 1)
        candidate = self.snapshots[0]["trigger_context"]["candidate_signals"][0]
        self.assertEqual(candidate["type"], "request_actual_attempt_overdue")
        self.assertIsNotNone(candidate["claimed_attempt_evidence"])
        self.assertIsNone(candidate["actual_attempt_evidence"])

    def test_request_watch_survives_an_unrelated_snapshot(self) -> None:
        self.state.process_event(
            self.event(
                "cmd_start",
                10.0,
                "andy",
                command="!startConversation",
                arguments=["bob", "Could you help with quartz?"],
                command_id="andy:11",
            )
        )
        self.state._trigger(12.0, "test_snapshot")
        self.assertEqual(len(self.snapshots[0]["open_watches"]["coordination_requests"]), 1)

        self.state.advance_before(15.001)
        self.assertEqual(len(self.snapshots), 2)
        candidate = self.snapshots[1]["trigger_context"]["candidate_signals"][0]
        self.assertEqual(candidate["type"], "request_ack_overdue")

    def test_requester_verification_can_trigger_before_attempt_timeout(self) -> None:
        self.state.process_event(
            self.event(
                "cmd_start",
                10.0,
                "andy",
                command="!startConversation",
                arguments=["bob", "Can you help place the missing blocks?"],
                command_id="andy:11",
            )
        )
        self.state.process_event(
            self.event(
                "chat_out",
                12.0,
                "bob",
                message="(To andy) On it.",
                recipient=None,
            )
        )
        self.state.process_event(
            self.event(
                "cmd_end",
                16.0,
                "andy",
                command="!checkBlueprint",
                command_id="andy:16",
                duration_ms=4,
                result="Level 0 requires the following fixes: Place quartz_block",
            )
        )
        self.state.finish_timestamp(16.0)

        self.assertEqual(len(self.snapshots), 1)
        candidate = self.snapshots[0]["trigger_context"]["candidate_signals"][0]
        self.assertEqual(candidate["type"], "request_verification_still_unresolved")


if __name__ == "__main__":
    unittest.main()
