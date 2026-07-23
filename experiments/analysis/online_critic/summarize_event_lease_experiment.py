#!/usr/bin/env python3
"""Summarize and causally validate the 106/162 trigger-policy pilot."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
DEFAULT_EVENT_ROOT = HERE / "derived" / "event_lease_v1" / "results"
DEFAULT_FIXED_ROOT = HERE / "derived" / "timeline_106_162_v2" / "results"
DEFAULT_OUTPUT_ROOT = HERE / "derived" / "event_lease_v1"


def load_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("trial_*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
                record["_source"] = str(path)
                records.append(record)
    return records


def iter_times(packet: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    for index, message in enumerate(packet.get("message_timeline") or []):
        yield f"message_timeline[{index}].time_s", message.get("time_s")
    for agent_index, agent in enumerate(packet.get("agents") or []):
        prefix = f"agents[{agent_index}]"
        execution = agent.get("current_execution") or {}
        yield f"{prefix}.current_execution.started_at_s", execution.get("started_at_s")
        claim = agent.get("latest_task_claim_at_cutoff") or {}
        yield f"{prefix}.latest_task_claim_at_cutoff.time_s", claim.get("time_s")
        position = agent.get("latest_position") or {}
        yield f"{prefix}.latest_position.time_s", position.get("time_s")
        yield f"{prefix}.last_observed_activity_s", agent.get("last_observed_activity_s")
        for command_index, command in enumerate(agent.get("completed_commands_in_window") or []):
            yield f"{prefix}.completed_commands[{command_index}].time_s", command.get("time_s")
    score = (packet.get("team_observations") or {}).get("score") or {}
    yield "team_observations.score.last_observed_increase_s", score.get(
        "last_observed_increase_s"
    )
    trigger = packet.get("trigger_context") or {}
    for index, candidate in enumerate(trigger.get("candidate_signals") or []):
        yield f"trigger_context.candidate_signals[{index}].observed_at_s", candidate.get(
            "observed_at_s"
        )
        yield f"trigger_context.candidate_signals[{index}].opened_at_s", candidate.get(
            "opened_at_s"
        )
    watches = packet.get("open_watches") or {}
    for group in ("task_actions", "coordination_requests"):
        for index, watch in enumerate(watches.get(group) or []):
            for field in ("opened_at_s", "ack_at_s", "attempt_started_at_s"):
                yield f"open_watches.{group}[{index}].{field}", watch.get(field)


def causal_violations(record: dict[str, Any]) -> list[dict[str, Any]]:
    packet = record.get("packet") or {}
    cutoff = ((packet.get("window") or {}).get("cutoff_s"))
    if not isinstance(cutoff, (int, float)):
        return [{"critic_id": record.get("critic_id"), "field": "cutoff_s", "value": cutoff}]
    violations = []
    for field, value in iter_times(packet):
        if isinstance(value, (int, float)) and value > cutoff + 1e-9:
            violations.append(
                {
                    "critic_id": record.get("critic_id"),
                    "cutoff_s": cutoff,
                    "field": field,
                    "value": value,
                }
            )
    return violations


def policy_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    sends = [record for record in records if ((record.get("result") or {}).get("manager_advisory") or {}).get("send")]
    terminals = [record for record in records if ((record.get("packet") or {}).get("window") or {}).get("is_terminal")]
    return {
        "snapshots": len(records),
        "successful_model_calls": sum(record.get("status") == "ok" for record in records),
        "terminal_snapshots": len(terminals),
        "nonterminal_snapshots": len(records) - len(terminals),
        "advisories_sent": len(sends),
        "verdict_counts": dict(
            sorted(Counter((record.get("result") or {}).get("verdict") for record in records).items())
        ),
        "per_trial": {
            trial_id: {
                "snapshots": sum(record.get("trial_id") == trial_id for record in records),
                "advisories_sent": sum(
                    record.get("trial_id") == trial_id
                    and bool(((record.get("result") or {}).get("manager_advisory") or {}).get("send"))
                    for record in records
                ),
                "cutoffs_s": [
                    ((record.get("packet") or {}).get("window") or {}).get("cutoff_s")
                    for record in records
                    if record.get("trial_id") == trial_id
                ],
            }
            for trial_id in sorted({record.get("trial_id") for record in records})
        },
    }


def compact_result(policy: str, record: dict[str, Any]) -> dict[str, Any]:
    packet = record.get("packet") or {}
    window = packet.get("window") or {}
    result = record.get("result") or {}
    advisory = result.get("manager_advisory") or {}
    return {
        "policy": policy,
        "trial_id": record.get("trial_id"),
        "cutoff_s": window.get("cutoff_s"),
        "trigger_reason": window.get("trigger_reason"),
        "candidate_types": [
            candidate.get("type")
            for candidate in ((packet.get("trigger_context") or {}).get("candidate_signals") or [])
        ],
        "verdict": result.get("verdict"),
        "confidence": result.get("confidence"),
        "imbalance_types": result.get("imbalance_types") or [],
        "send": bool(advisory.get("send")),
        "priority": advisory.get("priority"),
        "advisory": advisory.get("message") or "",
    }


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "policy",
        "trial_id",
        "cutoff_s",
        "trigger_reason",
        "candidate_types",
        "verdict",
        "confidence",
        "imbalance_types",
        "send",
        "priority",
        "advisory",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            rendered = dict(row)
            rendered["candidate_types"] = ",".join(row["candidate_types"])
            rendered["imbalance_types"] = ",".join(row["imbalance_types"])
            writer.writerow(rendered)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-root", type=Path, default=DEFAULT_EVENT_ROOT)
    parser.add_argument("--fixed-root", type=Path, default=DEFAULT_FIXED_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    event_records = load_records(args.event_root)
    fixed_records = load_records(args.fixed_root)
    if not event_records or not fixed_records:
        raise ValueError("Both event and fixed result roots must contain records")
    selected_trials = {"trial_106", "trial_162"}
    event_records = [record for record in event_records if record.get("trial_id") in selected_trials]
    fixed_records = [record for record in fixed_records if record.get("trial_id") in selected_trials]
    all_records = event_records + fixed_records
    failed = [record.get("critic_id") for record in all_records if record.get("status") != "ok"]
    violations = [item for record in all_records for item in causal_violations(record)]
    rows = [compact_result("fixed_25_50_75", record) for record in fixed_records]
    rows += [compact_result("event_leases_v1", record) for record in event_records]
    rows.sort(key=lambda row: (row["trial_id"], row["cutoff_s"], row["policy"]))

    summary = {
        "schema_version": "event_lease_trigger_ab.v1",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "evaluation_trials": sorted(selected_trials),
        "failed_model_calls": failed,
        "causal_integrity": {
            "checked_snapshots": len(all_records),
            "violations": violations,
        },
        "policies": {
            "fixed_25_50_75": policy_summary(fixed_records),
            "event_leases_v1": policy_summary(event_records),
        },
        "results": rows,
        "interpretation_boundary": (
            "Model advisories are not accuracy labels. Trigger quality still requires human audit, "
            "and shadow replay cannot estimate intervention effects."
        ),
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_tsv(args.output_root / "model_comparison.tsv", rows)
    print(
        json.dumps(
            {
                "fixed": summary["policies"]["fixed_25_50_75"],
                "event": summary["policies"]["event_leases_v1"],
                "causal_violations": len(violations),
                "output_root": str(args.output_root),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
