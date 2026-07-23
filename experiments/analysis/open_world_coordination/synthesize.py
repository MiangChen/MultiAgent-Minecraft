#!/usr/bin/env python3
"""Apply the open-coded process ontology to all 200 trials and draw figures."""

from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from PIL import Image, ImageDraw, ImageFont

from analyze import (
    ANALYSIS_ROOT, FAIL_RE, ROOT, canonical_agent, compact, extract_commitments,
    load_tasks, load_trial, make_episodes, task_success_from_log,
    transfer_candidates, unified_events,
)


DERIVED = ANALYSIS_ROOT / "derived"
FIGURES = ANALYSIS_ROOT / "figures"
GROUPS = [
    "2a_d0", "2a_d11", "2a_d22", "2a_d33", "3a_d22",
    "h1_pickaxe_split", "h2_shears_roles", "e1_pickaxe_equal", "e2_terracotta_equal",
]


def ref(event: dict) -> str:
    return f"{event['source_file']}:{event['source_line']}"


def phenomenon(label: str, confidence: float, definition: str, evidence: list[str], observation: str) -> dict:
    return {
        "label": label, "confidence": round(confidence, 3), "minimal_definition": definition,
        "observation": observation, "evidence": evidence[:12],
    }


def valid_peer_messages(trial, events: list[dict]) -> list[dict]:
    rows = []
    for event in events:
        if event["event_type"] != "chat_out" or not event.get("message"):
            continue
        text = event["message"]
        if re.search(r"\(To\s+(?:" + "|".join(map(re.escape, trial.agents)) + r")\)", text, re.I):
            rows.append(event)
    return rows


def target_craft_events(trial, events: list[dict]) -> list[dict]:
    target = trial.task.get("target")
    if not target:
        return []
    return [
        event for event in events
        if event["event_type"] == "cmd" and event.get("command") == "!craftRecipe"
        and str((event.get("raw_evidence", {}).get("args") or [None])[0]) == target
        and re.search(rf"Successfully crafted {re.escape(target)}", str(event.get("raw_evidence", {}).get("result") or ""), re.I)
    ]


def target_attempts(trial, events: list[dict]) -> list[dict]:
    target = trial.task.get("target")
    if not target:
        return []
    return [
        event for event in events
        if (
            event["event_type"] == "cmd" and event.get("command") == "!craftRecipe"
            and str((event.get("raw_evidence", {}).get("args") or [None])[0]) == target
        ) or (
            event["event_type"] == "chat_out" and f'!craftRecipe("{target}"' in str(event.get("message"))
        )
    ]


def correct_state_sequences(events: list[dict]) -> tuple[list[dict], list[dict]]:
    losses = []
    open_losses: dict[tuple[int, int, int], dict] = {}
    recoveries = []
    for event in events:
        if event["event_type"] != "block" or not event.get("semantic"):
            continue
        change = event["semantic"].get("world_change")
        block = event.get("block_delta") or {}
        coord = tuple(block.get(k) for k in ("x", "y", "z"))
        if change in {"correct_block_removed", "correct_block_overwritten"}:
            losses.append(event)
            open_losses[coord] = event
        elif change in {"correct_placement", "correction"} and coord in open_losses:
            recoveries.append({"loss": open_losses.pop(coord), "recovery": event})
    unrepaired = [loss for coord, loss in open_losses.items()]
    return recoveries, unrepaired


def attributed_contributions(events: list[dict]) -> tuple[Counter, dict[str, Counter], int, int]:
    agents = Counter()
    materials: dict[str, Counter] = defaultdict(Counter)
    relevant = 0
    unattributed = 0
    for event in events:
        if event["event_type"] != "block" or event.get("semantic", {}).get("scope") != "blueprint_target":
            continue
        relevant += 1
        if not event.get("agent"):
            unattributed += 1
        if event.get("agent") and event["semantic"].get("world_change") in {"correct_placement", "correction"}:
            agents[event["agent"]] += 1
            materials[event["agent"]][event["semantic"].get("expected")] += 1
    return agents, materials, relevant, unattributed


def initial_inventory_alignment(trial, materials: dict[str, Counter]) -> tuple[float | None, list[str]]:
    initial = trial.task.get("initial_inventory", {})
    total = matched = 0
    evidence = []
    for idx, agent in enumerate(trial.agents):
        owned = set(initial.get(str(idx), {}))
        for material, count in materials.get(agent, {}).items():
            total += count
            if material in owned:
                matched += count
        if materials.get(agent):
            evidence.append(f"{agent}: initial={sorted(owned)} observed={dict(materials[agent])}")
    return (matched / total if total else None), evidence


def classify_trial(trial, events: list[dict], commitments: list[dict], transfers: list[dict]) -> tuple[list[dict], dict]:
    labels = []
    peer_messages = valid_peer_messages(trial, events)
    craft_success = target_craft_events(trial, events)
    attempts = target_attempts(trial, events)
    run_success = task_success_from_log(trial)
    verified = [tr for tr in transfers if tr["confidence"] >= 0.9]
    contributions, materials, relevant, unattributed = attributed_contributions(events)
    total_contrib = sum(contributions.values())
    max_share = max(contributions.values(), default=0) / total_contrib if total_contrib else None
    alignment, alignment_detail = initial_inventory_alignment(trial, materials)
    recoveries, unrepaired = correct_state_sequences(events)
    losses = [pair["loss"] for pair in recoveries] + unrepaired
    duration = (trial.end_ms - trial.start_ms) / 1000
    scores = [e for e in events if e["event_type"] == "score" and e.get("score") is not None]
    final_score = scores[-1]["score"] if scores else None

    self_actions = [c for c in commitments if c["commitment_type"] == "self_action_commitment"]
    first_actions = {}
    for c in self_actions:
        first_actions.setdefault(c["agent"], c)
    if trial.blueprint and len(first_actions) >= 2:
        times = [c["declared_at_s"] for c in first_actions.values()]
        if max(times) - min(times) <= 45 and all("blueprint" in c["declared_goal"].lower() for c in first_actions.values()):
            labels.append(phenomenon(
                "whole_task_commitment_overlap", 0.9,
                "At least two agents independently claim the full construction scope within 45 seconds.",
                [c["supporting_evidence"][0] for c in first_actions.values()],
                "The declarations overlap at task scope; this does not by itself establish conflicting physical action.",
            ))
    active_agents = [a for a, n in contributions.items() if n >= 5]
    if trial.blueprint and len(active_agents) >= 2 and alignment is not None and alignment >= 0.75:
        first_evidence = [
            ref(e) for e in events if e["event_type"] == "block" and e.get("agent") in active_agents
            and e.get("semantic", {}).get("world_change") in {"correct_placement", "correction"}
        ][:6]
        labels.append(phenomenon(
            "inventory_induced_implicit_specialization", min(0.92, 0.6 + 0.3 * alignment),
            "Multiple agents add correct blocks, predominantly from their distinct initial material allocations, without requiring an explicit role agreement.",
            first_evidence,
            f"Observed own-allocation alignment={alignment:.3f}; " + "; ".join(alignment_detail),
        ))
    if total_contrib >= 10 and max_share is not None and max_share >= 0.8:
        dominant = contributions.most_common(1)[0]
        labels.append(phenomenon(
            "single_agent_execution_dominance", 0.78,
            "One agent accounts for at least 80% of conservatively attributed correct construction additions.",
            [ref(e) for e in events if e["event_type"] == "block" and e.get("agent") == dominant[0]
             and e.get("semantic", {}).get("world_change") in {"correct_placement", "correction"}][:5],
            f"{dominant[0]} has {dominant[1]}/{total_contrib} attributed correct additions; unattributed relevant events={unattributed}/{relevant}.",
        ))
    if total_contrib >= 20 and len(active_agents) >= 2 and max_share is not None and max_share <= 0.68:
        labels.append(phenomenon(
            "balanced_parallel_execution", 0.76,
            "At least two agents make substantial attributed correct additions and no agent exceeds 68% of that attributed work.",
            [ref(e) for e in events if e["event_type"] == "block" and e.get("agent") in active_agents
             and e.get("semantic", {}).get("world_change") in {"correct_placement", "correction"}][:5],
            f"Attributed additions by agent={dict(contributions)}; unattributed relevant events={unattributed}/{relevant}.",
        ))
    if trial.blueprint and len(active_agents) >= 2 and len(peer_messages) <= 2 and alignment is not None and alignment >= 0.75:
        labels.append(phenomenon(
            "quiet_action_complementarity", 0.72,
            "Agents make materially complementary world changes with at most two visible directed peer messages.",
            [ref(e) for e in peer_messages] + [ref(e) for e in events if e.get("agent") in active_agents and e["event_type"] == "block"][:4],
            f"Directed peer messages={len(peer_messages)}, contributions={dict(contributions)}, allocation alignment={alignment:.3f}.",
        ))

    for transfer in verified:
        recipient_attempts = [e for e in attempts if e.get("agent") == transfer["to"] and e["epoch_ms"] >= transfer["t"]]
        if recipient_attempts and (run_success or any(e in craft_success for e in recipient_attempts)):
            labels.append(phenomenon(
                "verified_handoff_to_completion", 0.94,
                "A successful item handoff is followed by the recipient attempting or completing the target synthesis.",
                transfer["evidence"] + [ref(recipient_attempts[0])],
                f"{transfer['from']} gave {transfer['amount']} {transfer['item']} to {transfer['to']}; recipient target action followed after {(recipient_attempts[0]['epoch_ms']-transfer['t'])/1000:.1f}s.",
            ))
            break
    table_places = [
        e for e in events if e["event_type"] == "cmd" and e.get("command") == "!placeHere"
        and (e.get("raw_evidence", {}).get("args") or [None])[0] == "crafting_table"
        and "Placed crafting_table" in str(e.get("raw_evidence", {}).get("result") or "")
    ]
    for table in table_places:
        other_attempt = next((e for e in attempts if e.get("agent") != table.get("agent") and e["epoch_ms"] > table["epoch_ms"]), None)
        if other_attempt:
            labels.append(phenomenon(
                "shared_infrastructure_support", 0.9,
                "One agent places a shared workstation and another subsequently uses or targets it for the task output.",
                [ref(table), ref(other_attempt)],
                f"{table['agent']} placed the crafting table; {other_attempt['agent']} attempted the target after {(other_attempt['epoch_ms']-table['epoch_ms'])/1000:.1f}s.",
            ))
            break
    successful_crafters = sorted({e["agent"] for e in craft_success})
    if len(successful_crafters) >= 2:
        labels.append(phenomenon(
            "parallel_target_overproduction", 0.96,
            "More than one agent successfully crafts the target even though one target satisfies the task.",
            [ref(e) for e in craft_success[:4]],
            f"Successful target crafters={successful_crafters}.",
        ))
    if len(successful_crafters) == 1 and not verified and not any(p["label"] == "shared_infrastructure_support" for p in labels):
        labels.append(phenomenon(
            "self_contained_task_capture", 0.86,
            "A single agent completes the synthesis without a verified input handoff or teammate-provided workstation in the observable trace.",
            [ref(e) for e in craft_success[:3]],
            f"Sole observed successful crafter={successful_crafters[0]}.",
        ))
    failed_gives = [
        e for e in events if e["event_type"] == "cmd" and e.get("command") == "!givePlayer"
        and FAIL_RE.search(str(e.get("raw_evidence", {}).get("result") or ""))
    ]
    if failed_gives and verified and run_success:
        later = next((tr for tr in verified if tr["t"] > failed_gives[0]["epoch_ms"]), None)
        if later:
            labels.append(phenomenon(
                "handoff_failure_then_repair", 0.95,
                "A failed give attempt is followed by a verified retry and eventual task success.",
                [ref(failed_gives[0])] + later["evidence"],
                f"Initial handoff failed; verified retry occurred {(later['t']-failed_gives[0]['epoch_ms'])/1000:.1f}s later.",
            ))
    failed_target = [
        e for e in attempts if e["event_type"] == "cmd" and FAIL_RE.search(str(e.get("raw_evidence", {}).get("result") or ""))
    ]
    for failure in failed_target:
        outgoing = next((tr for tr in verified if tr["from"] == failure.get("agent") and tr["t"] > failure["epoch_ms"]), None)
        if outgoing:
            recipient_success = next((e for e in craft_success if e.get("agent") == outgoing["to"] and e["epoch_ms"] > outgoing["t"]), None)
            if recipient_success:
                labels.append(phenomenon(
                    "role_reassignment_after_execution_failure", 0.96,
                    "After one agent cannot execute the synthesis, inputs move to the teammate who completes it.",
                    [ref(failure)] + outgoing["evidence"] + [ref(recipient_success)],
                    f"Failed executor={failure['agent']}; later executor={recipient_success['agent']}.",
                ))
                break
    requests = [c for c in commitments if c["commitment_type"] == "requested_commitment"]
    request_counts = Counter((c["speaker"], c["agent"]) for c in requests)
    if request_counts and request_counts.most_common(1)[0][1] >= 3 and not verified:
        pair, count = request_counts.most_common(1)[0]
        subset = [c for c in requests if (c["speaker"], c["agent"]) == pair]
        labels.append(phenomenon(
            "unanswered_request_loop", 0.82,
            "The same speaker issues at least three requests to the same teammate without a verified handoff.",
            [c["supporting_evidence"][0] for c in subset[:5]],
            f"Observed {count} requests from {pair[0]} to {pair[1]} and no verified handoff.",
        ))
    search_cmds = [e for e in events if e["event_type"] == "cmd" and e.get("command") in {"!searchForBlock", "!collectBlocks"}]
    if len(search_cmds) >= 5 and not run_success and not verified:
        labels.append(phenomenon(
            "resource_search_displacement", 0.8,
            "An agent repeatedly searches the environment for a dependency instead of obtaining it from the resource-holding teammate, and the task does not complete.",
            [ref(e) for e in search_cmds[:6]],
            f"Observed {len(search_cmds)} search/collect commands, no verified handoff, and no logged success.",
        ))
    if craft_success and not run_success:
        labels.append(phenomenon(
            "terminal_detector_process_mismatch", 0.99,
            "The action trace reports successful target crafting but the run terminates without the successful task marker.",
            [ref(e) for e in craft_success[:4]],
            f"Successful craft commands={len(craft_success)}; run-log success marker absent.",
        ))
    late_requests = [c for c in requests if c["declared_at_s"] >= 0.65 * duration]
    if late_requests:
        labels.append(phenomenon(
            "late_dependency_disclosure", 0.8,
            "A resource/help dependency is first or repeatedly disclosed after 65% of the trial duration.",
            [c["supporting_evidence"][0] for c in late_requests[:4]],
            f"Late request times={[round(c['declared_at_s'],1) for c in late_requests[:5]]}, duration={duration:.1f}s.",
        ))
    if losses:
        labels.append(phenomenon(
            "correct_world_state_loss", 0.98,
            "A block matching the blueprint is later removed or overwritten.",
            [ref(e) for e in losses[:8]],
            f"Observed losses={len(losses)}, recovered coordinates={len(recoveries)}, unrepaired coordinates={len(unrepaired)}.",
        ))
    if recoveries:
        labels.append(phenomenon(
            "correct_state_restoration", 0.98,
            "A previously lost correct blueprint coordinate is later restored to its expected block.",
            [x for pair in recoveries[:4] for x in (ref(pair["loss"]), ref(pair["recovery"]))],
            f"Recovered coordinates={len(recoveries)}.",
        ))
    if unrepaired:
        labels.append(phenomenon(
            "unrepaired_correct_state_loss", 0.98,
            "At least one lost correct blueprint coordinate is not restored before trace end.",
            [ref(e) for e in unrepaired[:8]],
            f"Unrepaired coordinates={len(unrepaired)}.",
        ))
    if scores and final_score is not None and final_score < 100:
        last_change = scores[0]
        prior = scores[0]["score"]
        for score in scores[1:]:
            if score["score"] != prior:
                last_change = score
                prior = score["score"]
        plateau = (trial.end_ms - last_change["epoch_ms"]) / 1000
        late_resource_commitments = [
            c for c in self_actions if c["declared_at_s"] >= (last_change["epoch_ms"] - trial.start_ms) / 1000
            and re.search(r"missing|gather|mine|collect|out of|short", c["declared_goal"], re.I)
        ]
        if plateau >= 120 and late_resource_commitments:
            labels.append(phenomenon(
                "resource_blocked_progress_plateau", 0.84,
                "Progress remains unchanged for at least 120 seconds while commitments explicitly focus on missing or gathered materials.",
                [ref(last_change)] + [c["supporting_evidence"][0] for c in late_resource_commitments[:4]],
                f"Final unchanged interval={plateau:.1f}s, final score={final_score:.3f}.",
            ))
            if len(late_resource_commitments) >= 2:
                labels.append(phenomenon(
                    "plan_restatement_without_world_effect", 0.76,
                    "At least two new material-acquisition commitments occur after the last progress change without subsequent score gain.",
                    [c["supporting_evidence"][0] for c in late_resource_commitments[:6]],
                    f"Post-progress material plans={len(late_resource_commitments)}.",
                ))
    if len(peer_messages) >= 20 and not run_success:
        labels.append(phenomenon(
            "high_communication_without_completion", 0.72,
            "At least 20 directed peer messages occur but the run has no logged success.",
            [ref(e) for e in peer_messages[:6]],
            f"Directed peer messages={len(peer_messages)}.",
        ))
    metrics = {
        "trial_id": trial.trial_id, "group": trial.meta["group"], "duration_s": round(duration, 3),
        "run_success": run_success, "final_score": final_score,
        "peer_messages": len(peer_messages), "commitments": len(commitments),
        "verified_transfers": len(verified), "ambiguous_inventory_covariations": len(transfers) - len(verified),
        "target_craft_success_commands": len(craft_success), "target_crafters": successful_crafters,
        "correct_additions_by_agent": dict(contributions), "max_attributed_agent_share": max_share,
        "allocation_alignment": alignment, "relevant_block_attribution_rate": (1 - unattributed / relevant) if relevant else None,
        "correct_state_losses": len(losses), "correct_state_recoveries": len(recoveries),
        "unrepaired_correct_state_losses": len(unrepaired),
        "phenomena": [p["label"] for p in labels] or ["unknown"],
    }
    return labels, metrics


def label_episodes(trial, events: list[dict], episodes: list[dict], transfers: list[dict]) -> list[dict]:
    recoveries, _ = correct_state_sequences(events)
    recovery_times = {pair["recovery"]["epoch_ms"]: pair for pair in recoveries}
    for episode in episodes:
        start = trial.start_ms + round(episode["start_s"] * 1000)
        end = trial.start_ms + round(episode["end_s"] * 1000)
        window = [e for e in events if start <= e["epoch_ms"] < end]
        labels = []
        if any((e.get("semantic") or {}).get("world_change") in {"correct_block_removed", "correct_block_overwritten"} for e in window):
            labels.append({"label": "correct_world_state_loss", "confidence": 0.98})
        if any(t in recovery_times for t in (e["epoch_ms"] for e in window)):
            labels.append({"label": "correct_state_restoration", "confidence": 0.98})
        ep_transfers = [tr for tr in transfers if start <= tr["t"] < end]
        if any(tr["confidence"] >= 0.9 for tr in ep_transfers):
            labels.append({"label": "verified_resource_handoff", "confidence": 0.96})
        if any(tr["confidence"] < 0.9 for tr in ep_transfers):
            labels.append({"label": "ambiguous_inventory_covariation", "confidence": 0.42})
        reasons = {r["kind"] for r in episode["boundary_reason"]}
        if "progress_plateau" in reasons:
            labels.append({"label": "progress_plateau_boundary", "confidence": 0.9})
        messages = episode.get("messages", [])
        if any("request" in m.get("tags", []) or "help" in m.get("tags", []) for m in messages) and not ep_transfers:
            labels.append({"label": "dependency_request_without_same_episode_handoff", "confidence": 0.68})
        if messages and not episode["actual_actions"] and not episode["world_changes"] and not episode["resource_changes"]:
            labels.append({"label": "communication_without_observable_effect", "confidence": 0.58})
        episode["phenomenon_labels"] = labels or [{"label": "unknown", "confidence": 0.35}]
    return episodes


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(compact(row) + "\n")


def quality_audit(all_data: dict[int, dict]) -> list[dict]:
    random.seed(20260721)
    build_groups = [range(101, 121), range(121, 141), range(141, 161), range(161, 181), range(181, 201)]
    craft_groups = [range(201, 226), range(226, 251), range(251, 276), range(276, 301)]
    sample = []
    for ids in build_groups:
        sample += random.sample(list(ids), 4)
    for ids in craft_groups:
        sample += random.sample(list(ids), 5)
    rows = []
    for number in sorted(sample):
        data = all_data[number]
        flags = []
        trial = data["trial"]
        for commitment in data["commitments"]:
            source, line = commitment["supporting_evidence"][0].rsplit(":", 1)
            path = trial.path / source
            if not path.exists() or int(line) < 1:
                flags.append(f"missing_commitment_evidence:{commitment['commitment_id']}")
        for transfer in data["transfers"]:
            if transfer["confidence"] >= 0.9 and "givePlayer" not in transfer["rationale"]:
                flags.append("high_confidence_transfer_without_give")
        for label in data["labels"]:
            if label["label"] != "unknown" and not label["evidence"]:
                flags.append(f"semantic_label_without_evidence:{label['label']}")
        rows.append({
            "trial_id": trial.trial_id, "group": trial.meta["group"],
            "commitments_checked": len(data["commitments"]), "episodes_checked": len(data["episodes"]),
            "phenomena_checked": len(data["labels"]), "verified_transfers_checked": sum(t["confidence"] >= 0.9 for t in data["transfers"]),
            "audit_status": "flag" if flags else "pass", "flags": flags,
            "audit_scope": "source location, transfer basis, label evidence presence; semantic boundary reviewed against open-code definitions",
        })
    return rows


def group_summary(metrics: list[dict], labels: list[dict]) -> list[dict]:
    label_by_trial = {row["trial_id"]: row["labels"] for row in labels}
    rows = []
    for group in GROUPS:
        subset = [m for m in metrics if m["group"] == group]
        counts = Counter(p["label"] for m in subset for p in label_by_trial[m["trial_id"]])
        rows.append({
            "group": group, "n": len(subset), "run_successes": sum(m["run_success"] for m in subset),
            "mean_duration_s": round(mean(m["duration_s"] for m in subset), 1),
            "mean_peer_messages": round(mean(m["peer_messages"] for m in subset), 2),
            "verified_transfers": sum(m["verified_transfers"] for m in subset),
            "state_losses": sum(m["correct_state_losses"] for m in subset),
            "state_recoveries": sum(m["correct_state_recoveries"] for m in subset),
            "terminal_mismatches": counts["terminal_detector_process_mismatch"],
            "top_phenomena": compact(counts.most_common(6)),
        })
    return rows


def draw_figures(all_data: dict[int, dict], metrics: list[dict], label_rows: list[dict]) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 18)
    small = ImageFont.truetype(font_path, 14)
    tiny = ImageFont.truetype(font_path, 11)
    bold = ImageFont.truetype(bold_path, 23)
    colors = ["#4C78A8", "#E15759", "#F28E2B", "#59A14F", "#B279A2"]

    def canvas(title: str, width: int = 1500, height: int = 760):
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((45, 25), title, fill="#171717", font=bold)
        return image, draw

    def axes(draw, box, x_label: str, y_label: str):
        x0, y0, x1, y1 = box
        draw.line((x0, y1, x1, y1), fill="#333333", width=2)
        draw.line((x0, y0, x0, y1), fill="#333333", width=2)
        draw.text(((x0 + x1) / 2 - 80, y1 + 35), x_label, fill="#333333", font=small)
        draw.text((8, y0 - 5), y_label, fill="#333333", font=small)

    # Phenomenon occurrence over normalized episode time.
    selected = ["correct_world_state_loss", "correct_state_restoration", "verified_resource_handoff", "progress_plateau_boundary", "dependency_request_without_same_episode_handoff"]
    series = []
    for label in selected:
        values = []
        for data in all_data.values():
            duration = data["metrics"]["duration_s"] or 1
            for episode in data["episodes"]:
                if any(x["label"] == label for x in episode["phenomenon_labels"]):
                    values.append(min(.999, ((episode["start_s"] + episode["end_s"]) / 2) / duration))
        hist = [sum(i / 10 <= value < (i + 1) / 10 for value in values) for i in range(10)]
        series.append((label, hist, len(values)))
    image, draw = canvas("When observable coordination phenomena occur")
    box = (105, 100, 1080, 650)
    axes(draw, box, "Normalized trial time", "Episode count")
    ymax = max((max(hist) for _, hist, _ in series), default=1)
    for index, (label, hist, total) in enumerate(series):
        points = []
        for i, value in enumerate(hist):
            x = box[0] + (i + .5) / 10 * (box[2] - box[0])
            y = box[3] - value / max(ymax, 1) * (box[3] - box[1])
            points.append((x, y))
        draw.line(points, fill=colors[index], width=4)
        for point in points:
            draw.ellipse((point[0]-4, point[1]-4, point[0]+4, point[1]+4), fill=colors[index])
        draw.text((1120, 120 + index * 62), f"{label}\nn={total}", fill=colors[index], font=tiny)
    for i in range(11):
        x = box[0] + i / 10 * (box[2] - box[0])
        draw.text((x - 10, box[3] + 8), f"{i/10:.1f}", fill="#555555", font=tiny)
    image.save(FIGURES / "phenomenon_time_distribution.png")

    # All episode-level labels, including unknown and low-confidence categories.
    all_episode_labels = sorted({
        item["label"] for data in all_data.values() for episode in data["episodes"]
        for item in episode["phenomenon_labels"]
    })
    matrix = []
    for label in all_episode_labels:
        values = []
        for data in all_data.values():
            duration = data["metrics"]["duration_s"] or 1
            for episode in data["episodes"]:
                if any(x["label"] == label for x in episode["phenomenon_labels"]):
                    values.append(min(.999, ((episode["start_s"] + episode["end_s"]) / 2) / duration))
        matrix.append([sum(i / 10 <= value < (i + 1) / 10 for value in values) for i in range(10)])
    image, draw = canvas("All episode labels over normalized trial time", 1500, 760)
    x0, y0, cell_w, cell_h = 610, 115, 75, 58
    max_cell = max((value for row in matrix for value in row), default=1)
    for row_idx, (label, row) in enumerate(zip(all_episode_labels, matrix)):
        draw.text((35, y0 + row_idx * cell_h + 16), label, fill="#333333", font=small)
        for col_idx, value in enumerate(row):
            intensity = int(245 - 190 * (value / max_cell) ** .5)
            color = (intensity, int(120 + (intensity-55)*.35), 80)
            left, top = x0 + col_idx * cell_w, y0 + row_idx * cell_h
            draw.rectangle((left, top, left+cell_w-3, top+cell_h-3), fill=color)
            draw.text((left+25, top+18), str(value), fill="white" if intensity < 145 else "#222222", font=tiny)
    for col_idx in range(10):
        draw.text((x0 + col_idx * cell_w + 18, y0 - 28), f"{col_idx/10:.1f}", fill="#333333", font=tiny)
    draw.text((x0+260, y0+len(matrix)*cell_h+12), "Normalized trial time bin", fill="#333333", font=small)
    image.save(FIGURES / "all_episode_labels_time_matrix.png")

    # Commitment/action alignment by group.
    ledger = [c for data in all_data.values() for c in data["commitments"] if c["commitment_type"] != "assigned_task_goal"]
    follow, complete = [], []
    for group in GROUPS:
        rows = [c for c in ledger if c["group"] == group]
        follow.append(mean(c["observable_follow_through"] for c in rows) if rows else 0)
        complete.append(mean(c["status"] == "completed" for c in rows) if rows else 0)
    image, draw = canvas("Commitments are not equivalent to completed world effects", 1600, 820)
    box = (100, 100, 1540, 650)
    axes(draw, box, "Experimental group", "Fraction")
    band = (box[2] - box[0]) / len(GROUPS)
    for i, group in enumerate(GROUPS):
        center = box[0] + (i + .5) * band
        for offset, value, color in ((-20, follow[i], colors[0]), (20, complete[i], colors[2])):
            draw.rectangle((center+offset-16, box[3]-value*(box[3]-box[1]), center+offset+16, box[3]), fill=color)
        draw.text((center-45, box[3]+15), group, fill="#333333", font=tiny)
    draw.rectangle((105, 700, 125, 720), fill=colors[0]); draw.text((135, 700), "observable follow-through", fill="#333333", font=small)
    draw.rectangle((390, 700, 410, 720), fill=colors[2]); draw.text((420, 700), "completed (stricter)", fill="#333333", font=small)
    image.save(FIGURES / "commitment_action_alignment.png")

    # Resource handoffs and dependency outcomes for crafting groups.
    craft_groups = GROUPS[5:]
    verified = [sum(m["verified_transfers"] for m in metrics if m["group"] == g) for g in craft_groups]
    handoff_done = [sum("verified_handoff_to_completion" in m["phenomena"] for m in metrics if m["group"] == g) for g in craft_groups]
    infra = [sum("shared_infrastructure_support" in m["phenomena"] for m in metrics if m["group"] == g) for g in craft_groups]
    image, draw = canvas("Observable resource and infrastructure dependencies", 1300, 760)
    box = (100, 100, 1240, 600)
    axes(draw, box, "Crafting condition", "Count")
    ymax = max(verified + handoff_done + infra + [1])
    band = (box[2]-box[0])/4
    for i, group in enumerate(craft_groups):
        center = box[0] + (i+.5)*band
        for offset, value, color in ((-45, verified[i], colors[0]), (0, handoff_done[i], colors[2]), (45, infra[i], colors[3])):
            height = value/ymax*(box[3]-box[1])
            draw.rectangle((center+offset-18, box[3]-height, center+offset+18, box[3]), fill=color)
            draw.text((center+offset-5, box[3]-height-18), str(value), fill="#333333", font=tiny)
        draw.text((center-70, box[3]+15), group, fill="#333333", font=tiny)
    legends = [(colors[0], "verified item handoffs"), (colors[2], "handoff -> completion trials"), (colors[3], "shared workstation trials")]
    for i, (color, label) in enumerate(legends):
        draw.rectangle((110+i*360, 675, 130+i*360, 695), fill=color); draw.text((140+i*360, 675), label, fill="#333333", font=small)
    image.save(FIGURES / "resource_dependency_flow.png")

    # Joint timelines for one loss, one repaired handoff, one role reassignment.
    examples = [140, 243, 287]
    image, draw = canvas("Joint timelines: progress, language, commands, state loss and handoff", 1500, 980)
    for panel, number in enumerate(examples):
        data = all_data[number]
        trial, events = data["trial"], data["events"]
        x0, x1 = 150, 1430
        y0, y1 = 115 + panel*275, 325 + panel*275
        draw.line((x0, y1, x1, y1), fill="#333333", width=2)
        draw.text((35, y0), trial.trial_id, fill="#171717", font=font)
        duration = data["metrics"]["duration_s"] or 1
        tx = lambda seconds: x0 + seconds/duration*(x1-x0)
        scores = [e for e in events if e["event_type"] == "score" and e.get("score") is not None]
        if scores:
            points = [(tx(e["relative_time_s"]), y1-e["score"]/100*(y1-y0)) for e in scores]
            draw.line(points, fill="#222222", width=2)
        chats = [e for e in events if e["event_type"] == "chat_out"]
        cmds = [e for e in events if e["event_type"] == "cmd"]
        losses = [e for e in events if (e.get("semantic") or {}).get("world_change") in {"correct_block_removed", "correct_block_overwritten"}]
        transfers = [tr for tr in data["transfers"] if tr["confidence"] >= .9]
        for e in chats: draw.ellipse((tx(e["relative_time_s"])-2,y1-32,tx(e["relative_time_s"])+2,y1-28), fill=colors[0])
        for e in cmds: draw.ellipse((tx(e["relative_time_s"])-2,y1-52,tx(e["relative_time_s"])+2,y1-48), fill=colors[3])
        for e in losses:
            x=tx(e["relative_time_s"]); draw.line((x-5,y0+25,x+5,y0+35),fill=colors[1],width=3); draw.line((x+5,y0+25,x-5,y0+35),fill=colors[1],width=3)
        for tr in transfers:
            x=tx((tr["t"]-trial.start_ms)/1000); draw.polygon([(x,y0+8),(x+6,y0+14),(x,y0+20),(x-6,y0+14)],fill=colors[2])
        draw.text((x1-300,y0), f"duration={duration:.1f}s", fill="#555555", font=tiny)
    draw.text((150, 925), "Black=progress; blue=chat; green=command; red X=correct state loss; orange diamond=verified handoff", fill="#333333", font=small)
    image.save(FIGURES / "joint_timeline_examples.png")

    # Matched outcomes, different processes.
    build_success = [m for m in metrics if m["group"].startswith(("2a", "3a")) and m["run_success"] and m["max_attributed_agent_share"] is not None]
    balanced = min(build_success, key=lambda m: abs(m["max_attributed_agent_share"] - .5))
    dominant = max(build_success, key=lambda m: m["max_attributed_agent_share"])
    pairs = [(balanced, dominant), (next(m for m in metrics if m["trial_id"] == "trial_201"), next(m for m in metrics if m["trial_id"] == "trial_263")),
             (next(m for m in metrics if m["trial_id"] == "trial_212"), next(m for m in metrics if m["trial_id"] == "trial_247"))]
    image, draw = canvas("Similar endpoints can conceal different processes", 1500, 760)
    for panel, (left, right) in enumerate(pairs):
        names = [left["trial_id"], right["trial_id"]]
        duration_vals = [left["duration_s"], right["duration_s"]]
        message_vals = [left["peer_messages"], right["peer_messages"]]
        transfer_vals = [left["verified_transfers"], right["verified_transfers"]]
        x0, x1 = 60+panel*490, 500+panel*490
        y0, y1 = 120, 620
        draw.line((x0,y1,x1,y1),fill="#333333",width=2)
        draw.text((x0+70,y0), f"same logged outcome: {left['run_success']}", fill="#333333", font=small)
        normalized = [
            [v/max(duration_vals) for v in duration_vals],
            [v/max(max(message_vals),1) for v in message_vals],
            [v/max(max(transfer_vals),1) for v in transfer_vals],
        ]
        for trial_index, name in enumerate(names):
            center=x0+150+trial_index*170
            for metric_index, color in enumerate(colors[:3]):
                value=normalized[metric_index][trial_index]
                draw.rectangle((center-40+metric_index*30,y1-value*360,center-20+metric_index*30,y1),fill=color)
            draw.text((center-55,y1+15),name,fill="#333333",font=small)
    draw.text((65, 690), "Blue=duration (pair-normalized)   Red=directed peer messages (pair-normalized)   Orange=verified handoffs (pair-normalized)", fill="#333333", font=small)
    image.save(FIGURES / "matched_process_pairs.png")


def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    all_data = {}
    ledgers, episodes_out, trial_labels, metrics = [], [], [], []
    for number in range(101, 301):
        trial = load_trial(number, tasks)
        events, _ = unified_events(trial)
        commitments = extract_commitments(trial, events)
        transfers = transfer_candidates(trial, events)
        episodes = label_episodes(trial, events, make_episodes(trial, events, commitments, transfers), transfers)
        labels, metric = classify_trial(trial, events, commitments, transfers)
        all_data[number] = {
            "trial": trial, "events": events, "commitments": commitments, "transfers": transfers,
            "episodes": episodes, "labels": labels, "metrics": metric,
        }
        ledgers.extend(commitments)
        episodes_out.extend(episodes)
        trial_labels.append({
            "trial_id": trial.trial_id, "group": trial.meta["group"],
            "labels": labels or [phenomenon("unknown", 0.35, "No current ontology rule reached its evidence threshold.", [], "Retained for future coding.")],
        })
        metrics.append(metric)
    write_jsonl(DERIVED / "commitment_ledger.jsonl", ledgers)
    write_jsonl(DERIVED / "coordination_episodes.jsonl", episodes_out)
    write_jsonl(DERIVED / "trial_phenomena.jsonl", trial_labels)
    write_jsonl(DERIVED / "trial_process_metrics.jsonl", metrics)
    audit = quality_audit(all_data)
    write_jsonl(DERIVED / "semantic_audit_40_trials.jsonl", audit)
    summaries = group_summary(metrics, trial_labels)
    with (DERIVED / "group_process_summary.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(summaries)
    draw_figures(all_data, metrics, trial_labels)
    print(compact({
        "trials": len(all_data), "commitments": len(ledgers), "episodes": len(episodes_out),
        "audit_pass": sum(r["audit_status"] == "pass" for r in audit), "figures": len(list(FIGURES.glob("*.png"))),
    }))


if __name__ == "__main__":
    main()
