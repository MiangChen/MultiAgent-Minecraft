#!/usr/bin/env python3
"""Run the offline critic through the same model adapter as Andy and Bob."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "derived" / "critic_windows.jsonl"
DEFAULT_OUTPUT = HERE / "derived" / "critic_results.jsonl"
PROMPT_PATH = HERE / "critic_prompt.md"
SCHEMA_PATH = HERE / "critic_output.schema.json"
MODEL_PROFILE_PATH = HERE / "critic_model_profile.json"
MODEL_BRIDGE_PATH = HERE / "model_bridge.mjs"
MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "high"


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def iter_packets(
    path: Path, trials: set[str], critic_ids: set[str]
) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                packet = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            trial_selected = not trials or packet.get("trial_id") in trials
            window_selected = not critic_ids or packet.get("critic_id") in critic_ids
            if trial_selected and window_selected:
                yield packet


def load_completed(path: Path) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            critic_id = row.get("critic_id")
            if isinstance(critic_id, str) and row.get("status") == "ok":
                completed.add(critic_id)
    return completed


def build_prompt(
    template: str, packet: dict[str, Any], output_schema: dict[str, Any]
) -> str:
    replacements = {
        "{{OUTPUT_SCHEMA}}": json.dumps(output_schema, ensure_ascii=False, indent=2),
        "{{EVIDENCE_PACKET}}": json.dumps(packet, ensure_ascii=False, indent=2),
    }
    for marker in replacements:
        if template.count(marker) != 1:
            raise ValueError(f"Prompt must contain exactly one {marker} marker")
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ValueError(f"Unsupported schema type: {expected}")


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the JSON Schema subset used by critic_output.schema.json."""
    expected_type = schema.get("type")
    if expected_type:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(value, item) for item in allowed):
            raise ValueError(f"{path} must have type {expected_type}; got {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}; got {value!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"{path} is missing required keys: {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ValueError(f"{path} has additional keys: {extras}")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], f"{path}.{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ValueError(f"{path} has fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"{path} has more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            rendered = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(rendered) != len(set(rendered)):
                raise ValueError(f"{path} contains duplicate items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema(item, item_schema, f"{path}[{index}]")

    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        raise ValueError(f"{path} exceeds maxLength={schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} is below minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} is above maximum={schema['maximum']}")


def model_command() -> list[str]:
    return ["node", str(MODEL_BRIDGE_PATH), str(MODEL_PROFILE_PATH)]


def load_model_profile() -> dict[str, Any]:
    profile = json.loads(MODEL_PROFILE_PATH.read_text(encoding="utf-8"))
    actual_model = profile.get("model")
    actual_effort = ((profile.get("params") or {}).get("reasoning") or {}).get("effort")
    if actual_model != MODEL or actual_effort != REASONING_EFFORT:
        raise ValueError(
            f"Critic profile must use {MODEL}/{REASONING_EFFORT}; "
            f"got {actual_model}/{actual_effort}"
        )
    if profile.get("api") != "openai" or not profile.get("url"):
        raise ValueError("Critic profile must use the repository's custom-URL openai adapter")
    return profile


def validate_identity(
    result: dict[str, Any], packet: dict[str, Any], output_schema: dict[str, Any]
) -> None:
    validate_schema(result, output_schema)
    expected = {
        "critic_id": packet["critic_id"],
        "trial_id": packet["trial_id"],
        "window_end_s": packet["window"]["end_s"],
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise ValueError(f"Critic returned {key}={result.get(key)!r}; expected {value!r}")
    advisory = result.get("manager_advisory") or {}
    if advisory.get("send"):
        if advisory.get("priority") == "none":
            raise ValueError("manager_advisory.priority must be actionable when send=true")
        if not advisory.get("message", "").strip():
            raise ValueError("manager_advisory.message must be non-empty when send=true")
    else:
        if advisory.get("priority") != "none":
            raise ValueError("manager_advisory.priority must be none when send=false")
        if advisory.get("message"):
            raise ValueError("manager_advisory.message must be empty when send=false")


def run_one(prompt: str, timeout_s: float) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    completed = subprocess.run(
        model_command(),
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        cwd=ROOT,
        check=False,
    )
    elapsed_s = time.monotonic() - started
    if completed.returncode != 0:
        stderr = completed.stderr[-2000:]
        raise RuntimeError(f"Model bridge exited {completed.returncode}: {stderr}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        excerpt = completed.stdout[:1000]
        raise ValueError(f"Model result is not JSON: {exc}; excerpt={excerpt!r}") from exc
    return result, elapsed_s


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(compact(record) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trial", action="append", default=[], help="Repeatable trial id filter")
    parser.add_argument(
        "--critic-id", action="append", default=[], help="Repeatable exact window filter"
    )
    parser.add_argument("--max-windows", type=int, help="Required unless --all is set")
    parser.add_argument("--all", action="store_true", help="Allow every selected window to run")
    parser.add_argument("--resume", action="store_true", help="Skip successful critic_ids in output")
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true", help="Validate selection and print the first invocation")
    args = parser.parse_args()
    if not args.all and args.max_windows is None:
        parser.error("Set --max-windows for a bounded pilot or explicitly pass --all")
    if args.max_windows is not None and args.max_windows <= 0:
        parser.error("--max-windows must be positive")

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    output_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    load_model_profile()
    selected = iter_packets(args.input, set(args.trial), set(args.critic_id))
    completed_ids = load_completed(args.output) if args.resume else set()
    packets = (packet for packet in selected if packet.get("critic_id") not in completed_ids)
    limit = None if args.all else args.max_windows

    processed = 0
    failures = 0
    for packet in packets:
        if limit is not None and processed >= limit:
            break
        prompt = build_prompt(prompt_template, packet, output_schema)
        if args.dry_run:
            print(
                compact(
                    {
                        "critic_id": packet["critic_id"],
                        "model": MODEL,
                        "reasoning_effort": REASONING_EFFORT,
                        "command": model_command(),
                        "prompt_characters": len(prompt),
                    }
                )
            )
            return

        record = {
            "critic_id": packet["critic_id"],
            "trial_id": packet["trial_id"],
            "window_end_s": packet["window"]["end_s"],
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
        }
        try:
            result, elapsed_s = run_one(prompt, args.timeout_s)
            validate_identity(result, packet, output_schema)
            record.update({"status": "ok", "elapsed_s": round(elapsed_s, 3), "result": result})
        except Exception as exc:  # Keep batch failures auditable and resumable.
            record.update({"status": "error", "error": str(exc)})
            failures += 1
        append_record(args.output, record)
        print(compact({key: record[key] for key in record if key != "result"}))
        processed += 1

    if processed == 0:
        print(compact({"status": "no_windows_selected"}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
