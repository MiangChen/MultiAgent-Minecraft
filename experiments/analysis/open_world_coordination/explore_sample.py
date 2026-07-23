#!/usr/bin/env python3
"""Create a compact evidence dossier for the preregistered open-coding sample."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from analyze import (
    ROOT, compact, extract_commitments, load_tasks, load_trial, make_episodes,
    task_success_from_log, transfer_candidates, unified_events,
)


SAMPLE = [
    105, 112, 119, 130, 133, 140, 143, 151, 159, 164, 167, 176, 183, 185, 191,
    201, 210, 212, 234, 243, 247, 255, 259, 263, 276, 287, 300,
]
OUT = Path(__file__).resolve().parent / "derived" / "open_coding_evidence.md"


def short(text: object, limit: int = 360) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "..."


def main() -> None:
    tasks = load_tasks()
    lines = [
        "# Open-coding evidence dossier",
        "",
        "Fixed-seed stratified random sample: seed 20260720, three trials per group. This is an evidence aid, not a final codebook.",
        "",
    ]
    for number in SAMPLE:
        trial = load_trial(number, tasks)
        events, _ = unified_events(trial)
        commitments = extract_commitments(trial, events)
        transfers = transfer_candidates(trial, events)
        episodes = make_episodes(trial, events, commitments, transfers)
        scores = [e for e in events if e["event_type"] == "score" and e.get("score") is not None]
        blocks = [
            e for e in events if e["event_type"] == "block"
            and e.get("semantic", {}).get("scope") == "blueprint_target"
        ]
        changes = Counter(e["semantic"]["world_change"] for e in blocks)
        contributions = Counter(
            e["agent"] for e in blocks if e.get("agent")
            and e["semantic"]["world_change"] in {"correct_placement", "correction"}
        )
        lines += [
            f"## {trial.trial_id} | {trial.meta['group']}",
            "",
            f"Observed endpoint: log_success={task_success_from_log(trial)}; duration={(trial.end_ms-trial.start_ms)/1000:.1f}s; "
            f"final_score={(scores[-1]['score'] if scores else 'NA')}; peak_score={(max((e['score'] for e in scores), default='NA'))}; "
            f"target={trial.task.get('target', 'blueprint')}; target-gain={sum(max(0,(e.get('inventory_delta') or {}).get(trial.task.get('target'),0)) for e in events) if trial.task.get('target') else 'NA'}.",
            f"World summary: {compact(changes)}; conservatively attributed correct additions={compact(contributions)}; transfer candidates={len(transfers)}; episodes={len(episodes)}.",
            "",
            "### Candidate commitments",
            "",
        ]
        for c in commitments:
            lines.append(
                f"- t={c['declared_at_s']:.1f}s speaker={c['speaker']} actor={c['agent']} type={c['commitment_type']} "
                f"status={c['status']} follow={c['observable_follow_through']} conf={c['semantic_confidence']:.2f}: "
                f"“{short(c['declared_goal'])}” [{c['supporting_evidence'][0]}]"
            )
        lines += ["", "### Messages and commands", ""]
        shown = set()
        for e in events:
            if e["event_type"] == "chat_out" and e.get("message"):
                key = (e["agent"], e["message"])
                if key in shown:
                    continue
                shown.add(key)
                lines.append(
                    f"- t={e['relative_time_s']:.1f}s {e['agent']} chat: “{short(e['message'], 430)}” "
                    f"[{e['source_file']}:{e['source_line']}]"
                )
            elif e["event_type"] == "cmd" and e.get("command") in {
                "!newAction", "!givePlayer", "!craftRecipe", "!collectBlocks", "!placeHere", "!useOn",
                "!startConversation", "!goToPlayer", "!searchForBlock", "!getCraftingPlan",
            }:
                result = short(e["raw_evidence"].get("result"), 180)
                lines.append(
                    f"- t={e['relative_time_s']:.1f}s {e['agent']} cmd {e['command']} args={short(e['raw_evidence'].get('args'), 250)} "
                    f"ms={e['raw_evidence'].get('ms')} result={result} [{e['source_file']}:{e['source_line']}]"
                )
        lines += ["", "### Progress, state loss, and resource movement", ""]
        prior = None
        last_milestone = -10
        for e in scores:
            score = e["score"]
            delta = None if prior is None else score - prior
            if delta is not None and (delta < -0.3 or score >= last_milestone + 10 or score == 100):
                lines.append(
                    f"- t={e['relative_time_s']:.1f}s score={score:.3f} delta={delta:+.3f} "
                    f"[{e['source_file']}:{e['source_line']}]"
                )
                if score >= last_milestone + 10:
                    last_milestone = int(score // 10) * 10
            prior = score
        for e in blocks:
            change = e["semantic"]["world_change"]
            if change in {"correct_block_removed", "correct_block_overwritten", "correction"}:
                b = e["block_delta"]
                lines.append(
                    f"- t={e['relative_time_s']:.1f}s {change} at ({b['x']},{b['y']},{b['z']}) "
                    f"{b['from']} -> {b['to']}; attributed={e['agent']} conf={e['attribution']['confidence']:.2f} "
                    f"[{e['source_file']}:{e['source_line']}]"
                )
        for tr in transfers:
            lines.append(
                f"- t={(tr['t']-trial.start_ms)/1000:.1f}s transfer-candidate {tr['from']} -> {tr['to']}: "
                f"{tr['amount']} {tr['item']} conf={tr['confidence']:.2f} [{', '.join(tr['evidence'])}]"
            )
        target = trial.task.get("target")
        if target:
            for e in events:
                delta = e.get("inventory_delta") or {}
                if any(k in delta for k in (target, "oak_planks", "stick", "iron_ingot", "crafting_table", "terracotta", "cyan_dye")):
                    lines.append(
                        f"- t={e['relative_time_s']:.1f}s {e['agent']} inventory {compact(delta)} "
                        f"[{e['source_file']}:{e['source_line']}]"
                    )
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
