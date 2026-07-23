#!/usr/bin/env python3
"""Validate and summarize a replay critic batch into machine and human audit tables."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
OFFLINE_DIR = HERE.parent / "offline_critic"
DEFAULT_MANIFEST = HERE / "batch_24_manifest.json"
DEFAULT_RESULTS = HERE / "derived" / "batch_24_v1" / "results"
RUNNER_PATH = OFFLINE_DIR / "run_critic.py"
SCHEMA_PATH = OFFLINE_DIR / "critic_output.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_module("batch_summary_runner", RUNNER_PATH)


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_root = args.output_root or args.results_root.parent
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for trial in manifest["trials"]:
        records = read_records(args.results_root / f"{trial['trial_id']}.jsonl")
        by_id = {record.get("critic_id"): record for record in records}
        for snapshot in trial["snapshots"]:
            expected_id = (
                f"{trial['trial_id']}_online_t{round(float(snapshot['cutoff_s']) * 1000):09d}"
            )
            record = by_id.get(expected_id)
            if not record:
                errors.append({"critic_id": expected_id, "error": "missing"})
                continue
            if record.get("status") != "ok":
                errors.append({"critic_id": expected_id, "error": record.get("error", record.get("status"))})
                continue
            try:
                RUNNER.validate_identity(record["result"], record["packet"], schema)
            except Exception as exc:
                errors.append({"critic_id": expected_id, "error": str(exc)})
                continue
            result = record["result"]
            packet = record["packet"]
            rows.append(
                {
                    "critic_id": expected_id,
                    "trial_id": trial["trial_id"],
                    "domain": trial["domain"],
                    "group": trial["group"],
                    "selection_stratum": trial["selection_stratum"],
                    "run_success": trial["run_success"],
                    "snapshot_fraction": snapshot["fraction"],
                    "cutoff_s": snapshot["cutoff_s"],
                    "verdict": result["verdict"],
                    "confidence": result["confidence"],
                    "imbalance_types": ",".join(result["imbalance_types"]),
                    "advisory_send": result["manager_advisory"]["send"],
                    "advisory_priority": result["manager_advisory"]["priority"],
                    "advisory_message": result["manager_advisory"]["message"],
                    "acting_agents": ",".join(
                        agent["agent"] for agent in packet["agents"]
                        if agent["current_execution"]["status"] == "acting"
                    ),
                    "unknown_load_agents": ",".join(
                        assessment["agent"] for assessment in result["agent_assessments"]
                        if assessment["load_state"] == "unknown"
                    ),
                    "score_change": packet["team_observations"]["score"]["change_in_window"],
                    "elapsed_s": record.get("elapsed_s"),
                    "packet": packet,
                }
            )

    tabular_rows = [
        {key: value for key, value in row.items() if key != "packet"}
        for row in rows
    ]
    model_path = output_root / "model_results.tsv"
    with model_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(tabular_rows[0]) if tabular_rows else [],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(tabular_rows)

    blind_packet_path = output_root / "blind_packets.jsonl"
    with blind_packet_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    {
                        "critic_id": row["critic_id"],
                        "trial_id": row["trial_id"],
                        "domain": row["domain"],
                        "snapshot_fraction": row["snapshot_fraction"],
                        "cutoff_s": row["cutoff_s"],
                        "packet": row["packet"],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )

    audit_fields = [
        "critic_id",
        "trial_id",
        "domain",
        "snapshot_fraction",
        "cutoff_s",
        "human_execution_state_correct",
        "human_imbalance",
        "human_imbalance_types",
        "human_send_advice",
        "human_advice_quality",
        "human_evidence_grade",
        "human_notes",
    ]
    audit_path = output_root / "human_audit_blind.tsv"
    with audit_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit_fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "critic_id": row["critic_id"],
                    "trial_id": row["trial_id"],
                    "domain": row["domain"],
                    "snapshot_fraction": row["snapshot_fraction"],
                    "cutoff_s": row["cutoff_s"],
                    "human_execution_state_correct": "",
                    "human_imbalance": "",
                    "human_imbalance_types": "",
                    "human_send_advice": "",
                    "human_advice_quality": "",
                    "human_evidence_grade": "",
                    "human_notes": "",
                }
            )

    by_domain: dict[str, Counter] = defaultdict(Counter)
    by_domain_fraction: dict[str, Counter] = defaultdict(Counter)
    by_domain_outcome: dict[str, Counter] = defaultdict(Counter)
    by_active_execution: dict[str, Counter] = defaultdict(Counter)
    trial_sequences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[row["domain"]][row["verdict"]] += 1
        by_domain_fraction[
            f"{row['domain']}|{row['snapshot_fraction']}"
        ][row["verdict"]] += 1
        by_domain_outcome[
            f"{row['domain']}|success={row['run_success']}"
        ][row["verdict"]] += 1
        by_active_execution[
            f"{row['domain']}|active={bool(row['acting_agents'])}"
        ][row["verdict"]] += 1
        trial_sequences[row["trial_id"]].append(
            {
                "fraction": row["snapshot_fraction"],
                "verdict": row["verdict"],
                "confidence": row["confidence"],
                "imbalance_types": row["imbalance_types"].split(",") if row["imbalance_types"] else [],
            }
        )
    summary = {
        "batch_id": manifest["batch_id"],
        "expected_snapshots": len(manifest["trials"]) * 3,
        "validated_snapshots": len(rows),
        "errors": errors,
        "verdicts": dict(Counter(row["verdict"] for row in rows)),
        "advisories_sent": sum(bool(row["advisory_send"]) for row in rows),
        "snapshots_with_active_execution": sum(bool(row["acting_agents"]) for row in rows),
        "by_domain": {domain: dict(counts) for domain, counts in sorted(by_domain.items())},
        "by_domain_fraction": {
            key: dict(counts) for key, counts in sorted(by_domain_fraction.items())
        },
        "by_domain_outcome": {
            key: dict(counts) for key, counts in sorted(by_domain_outcome.items())
        },
        "by_active_execution": {
            key: dict(counts) for key, counts in sorted(by_active_execution.items())
        },
        "advisory_priorities": dict(Counter(row["advisory_priority"] for row in rows)),
        "imbalance_types": dict(
            Counter(
                label
                for row in rows
                for label in row["imbalance_types"].split(",")
                if label
            )
        ),
        "mean_confidence": (
            round(sum(float(row["confidence"]) for row in rows) / len(rows), 4)
            if rows else None
        ),
        "mean_confidence_by_verdict": {
            verdict: round(
                sum(float(row["confidence"]) for row in rows if row["verdict"] == verdict)
                / sum(row["verdict"] == verdict for row in rows),
                4,
            )
            for verdict in sorted({row["verdict"] for row in rows})
        },
        "trial_sequences": {
            trial_id: sorted(sequence, key=lambda item: item["fraction"])
            for trial_id, sequence in sorted(trial_sequences.items())
        },
        "model_results_table": str(model_path),
        "blind_packets": str(blind_packet_path),
        "human_audit_table": str(audit_path),
    }
    (output_root / "batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
