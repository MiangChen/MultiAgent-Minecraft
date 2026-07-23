#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';


const EVENT_PRIORITY = {
    trace_start: 0,
    chat_out: 10,
    cmd_start: 20,
    inv: 30,
    pose: 30,
    block: 30,
    chat: 30,
    whisper: 30,
    score: 30,
    cmd_end: 40,
    trace_end: 50,
};

function readJsonl(filePath) {
    if (!fs.existsSync(filePath)) return [];
    return fs.readFileSync(filePath, 'utf8')
        .split('\n')
        .map((line, index) => ({ line, sourceLine: index + 1 }))
        .filter(row => row.line.trim())
        .map(row => ({ ...JSON.parse(row.line), sourceLine: row.sourceLine }));
}

function normalizeWorldEvent(event) {
    const agent = event.name || event.from || null;
    return {
        t: event.t,
        event_type: event.type,
        agent,
        source_file: 'trace/world_events.jsonl',
        source_line: event.sourceLine,
        raw_evidence: Object.fromEntries(
            Object.entries(event).filter(([key]) => key !== 'sourceLine')
        ),
    };
}

function normalizeAgentEvents(traceDir) {
    const rows = [];
    const files = fs.readdirSync(traceDir)
        .filter(name => name.endsWith('.trace.jsonl'))
        .sort();

    for (const fileName of files) {
        const agent = fileName.slice(0, -'.trace.jsonl'.length);
        const sourceFile = `trace/${fileName}`;
        for (const event of readJsonl(path.join(traceDir, fileName))) {
            const commandId = `${sourceFile}:${event.sourceLine}`;
            const base = {
                agent,
                source_file: sourceFile,
                source_line: event.sourceLine,
            };
            if (event.type === 'cmd') {
                const durationMs = Number.isFinite(event.ms) ? Math.max(0, event.ms) : 0;
                rows.push({
                    ...base,
                    t: event.t - durationMs,
                    event_type: 'cmd_start',
                    command: event.cmd,
                    arguments: event.args || [],
                    command_id: commandId,
                    reconstructed_from: commandId,
                    reconstruction_note: 'Start time reconstructed as recorded cmd end timestamp minus recorded duration_ms.',
                });
                rows.push({
                    ...base,
                    t: event.t,
                    event_type: 'cmd_end',
                    command: event.cmd,
                    arguments: event.args || [],
                    command_id: commandId,
                    duration_ms: durationMs,
                    result: event.result ?? null,
                });
            } else if (event.type === 'chat_out') {
                rows.push({
                    ...base,
                    t: event.t,
                    event_type: 'chat_out',
                    message: event.text || '',
                    recipient: event.to || null,
                });
            } else if (event.type === 'inv') {
                rows.push({
                    ...base,
                    t: event.t,
                    event_type: 'inv',
                    items: event.items || {},
                });
            } else if (event.type === 'trace_start' || event.type === 'trace_end') {
                rows.push({ ...base, t: event.t, event_type: event.type });
            }
        }
    }
    return rows;
}

function normalizeScores(traceDir) {
    const scorePath = path.join(traceDir, 'scores.tsv');
    if (!fs.existsSync(scorePath)) return [];
    const rows = [];
    const lines = fs.readFileSync(scorePath, 'utf8').split('\n');
    for (let index = 0; index < lines.length; index++) {
        const line = lines[index].trim();
        if (!line || line.startsWith('#')) continue;
        const [timestamp, value] = line.split('\t');
        const t = Number(timestamp);
        const score = Number(value);
        if (!Number.isFinite(t) || !Number.isFinite(score)) continue;
        rows.push({
            t,
            event_type: 'score',
            agent: null,
            score,
            source_file: 'trace/scores.tsv',
            source_line: index + 1,
        });
    }
    return rows;
}

export function loadCriticReplayStream(traceDir, t0 = null) {
    const worldPath = path.join(traceDir, 'world_events.jsonl');
    const world = readJsonl(worldPath);
    if (!world.length) throw new Error(`No world events at ${worldPath}`);
    const agentEvents = normalizeAgentEvents(traceDir);
    const traceStarts = agentEvents
        .filter(event => event.event_type === 'trace_start')
        .map(event => event.t);
    const origin = t0
        ?? (traceStarts.length ? Math.min(...traceStarts) : null)
        ?? world.find(event => event.type !== 'meta')?.t
        ?? world[0].t;
    const events = [
        ...world.filter(event => event.type !== 'meta').map(normalizeWorldEvent),
        ...agentEvents,
        ...normalizeScores(traceDir),
    ].filter(event => Number.isFinite(event.t));

    events.sort((left, right) => {
        if (left.t !== right.t) return left.t - right.t;
        const leftPriority = EVENT_PRIORITY[left.event_type] ?? 30;
        const rightPriority = EVENT_PRIORITY[right.event_type] ?? 30;
        if (leftPriority !== rightPriority) return leftPriority - rightPriority;
        return String(left.source_file).localeCompare(String(right.source_file));
    });

    const agents = [...new Set(
        events
            .filter(event => event.source_file?.endsWith('.trace.jsonl'))
            .map(event => event.agent)
            .filter(Boolean)
    )].sort();
    const normalized = events.map(event => ({
        ...event,
        relative_time_s: Number(((event.t - origin) / 1000).toFixed(3)),
    }));
    const trialEndS = Math.max(...normalized.map(event => event.relative_time_s));
    return { events: normalized, agents, t0: origin, trial_end_s: trialEndS };
}

function arg(name, fallback) {
    const index = process.argv.indexOf(`--${name}`);
    return index > 0 ? process.argv[index + 1] : fallback;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
    const traceDir = arg('trace', null);
    if (!traceDir) {
        console.error('Usage: node replay_stream.mjs --trace <trace-dir>');
        process.exit(2);
    }
    const stream = loadCriticReplayStream(traceDir);
    const counts = {};
    for (const event of stream.events) {
        counts[event.event_type] = (counts[event.event_type] || 0) + 1;
    }
    process.stdout.write(JSON.stringify({
        agents: stream.agents,
        t0: stream.t0,
        trial_end_s: stream.trial_end_s,
        events: stream.events.length,
        event_counts: counts,
    }) + '\n');
}
