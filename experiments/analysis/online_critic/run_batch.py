#!/usr/bin/env python3
"""Run fixed-cutoff online replay critic snapshots from a batch manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "batch_24_manifest.json"
DEFAULT_OUTPUT_ROOT = HERE / "derived" / "batch_24_v1" / "results"
REPLAY_PATH = ROOT / "experiments" / "scripts" / "replay.mjs"
PRINT_LOCK = threading.Lock()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def critic_id(trial_id: str, cutoff_s: float) -> str:
    return f"{trial_id}_online_t{round(cutoff_s * 1000):09d}"


def completed_ids(path: Path, accepted_status: str) -> set[str]:
    if not path.exists():
        return set()
    completed: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") == accepted_status and isinstance(row.get("critic_id"), str):
                completed.add(row["critic_id"])
    return completed


def run_trial(
    trial: dict[str, Any],
    output_root: Path,
    dry_run: bool,
    resume: bool,
    speed: float,
    critic_timeout_s: float,
) -> dict[str, Any]:
    trial_id = trial["trial_id"]
    output = output_root / f"{trial_id}.jsonl"
    accepted_status = "dry_run" if dry_run else "ok"
    done = completed_ids(output, accepted_status) if resume else set()
    expected_ids = {
        critic_id(trial_id, float(snapshot["cutoff_s"]))
        for snapshot in trial["snapshots"]
    }
    if output.exists() and not resume:
        raise FileExistsError(f"Refusing to append without --resume: {output}")

    calls = 0
    skipped = 0
    failures: list[dict[str, Any]] = []
    started = time.monotonic()
    for snapshot in trial["snapshots"]:
        cutoff_s = float(snapshot["cutoff_s"])
        expected_id = critic_id(trial_id, cutoff_s)
        if expected_id in done:
            skipped += 1
            continue
        margin_s = min(0.05, cutoff_s / 2)
        from_s = max(0.0, cutoff_s - margin_s)
        to_s = min(float(trial["replay_end_s"]), cutoff_s + margin_s)
        command = [
            "node",
            str(REPLAY_PATH),
            "--trace",
            str(ROOT / "experiments" / "out" / trial_id / "trace"),
            "--from",
            str(from_s),
            "--to",
            str(to_s),
            "--speed",
            str(speed),
            "--critic-only",
            "--critic-time-interval",
            str(cutoff_s),
            "--critic-message-count",
            "999999",
            "--critic-timeout",
            str(critic_timeout_s),
            "--critic-output",
            str(output),
        ]
        if dry_run:
            command.append("--critic-dry-run")
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=critic_timeout_s + 90,
            check=False,
        )
        calls += 1
        if completed.returncode != 0:
            failures.append(
                {
                    "critic_id": expected_id,
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-1200:],
                    "stderr_tail": completed.stderr[-1200:],
                }
            )
        with PRINT_LOCK:
            print(
                compact(
                    {
                        "trial_id": trial_id,
                        "critic_id": expected_id,
                        "call": calls,
                        "status": "failed" if failures and failures[-1]["critic_id"] == expected_id else "finished",
                    }
                ),
                flush=True,
            )

    final_done = completed_ids(output, accepted_status)
    missing = sorted(expected_ids - final_done)
    return {
        "trial_id": trial_id,
        "domain": trial["domain"],
        "calls": calls,
        "skipped": skipped,
        "completed": len(expected_ids & final_done),
        "missing": missing,
        "failures": failures,
        "elapsed_s": round(time.monotonic() - started, 3),
        "output": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--trial", action="append", default=[], help="Repeatable trial filter")
    parser.add_argument("--max-trials", type=int)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--speed", type=float, default=100000.0)
    parser.add_argument("--critic-timeout-s", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers <= 0 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    if args.max_trials is not None and args.max_trials <= 0:
        parser.error("--max-trials must be positive")
    if args.speed <= 0:
        parser.error("--speed must be positive")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = [
        trial for trial in manifest["trials"]
        if not args.trial or trial["trial_id"] in set(args.trial)
    ]
    if args.max_trials is not None:
        selected = selected[: args.max_trials]
    args.output_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="critic-batch") as executor:
        futures = {
            executor.submit(
                run_trial,
                trial,
                args.output_root,
                args.dry_run,
                args.resume,
                args.speed,
                args.critic_timeout_s,
            ): trial["trial_id"]
            for trial in selected
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "trial_id": futures[future],
                        "completed": 0,
                        "missing": ["trial_failed"],
                        "failures": [{"error": str(exc)}],
                    }
                )

    results.sort(key=lambda row: int(row["trial_id"].split("_")[-1]))
    summary = {
        "batch_id": manifest["batch_id"],
        "dry_run": args.dry_run,
        "resume": args.resume,
        "workers": args.workers,
        "selected_trials": len(selected),
        "expected_snapshots": len(selected) * 3,
        "completed_snapshots": sum(row.get("completed", 0) for row in results),
        "failed_trials": sum(bool(row.get("failures")) for row in results),
        "elapsed_s": round(time.monotonic() - started, 3),
        "results": results,
    }
    summary_path = args.output_root / "batch_run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(compact({key: value for key, value in summary.items() if key != "results"}), flush=True)
    if summary["completed_snapshots"] != summary["expected_snapshots"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
