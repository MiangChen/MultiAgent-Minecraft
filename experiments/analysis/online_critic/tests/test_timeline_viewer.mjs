#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';


const HERE = path.dirname(fileURLToPath(import.meta.url));
const VIEWER = path.resolve(HERE, '../timeline_viewer');

function loadData() {
    const context = { window: {} };
    vm.runInNewContext(
        fs.readFileSync(path.join(VIEWER, 'timeline_data.js'), 'utf8'),
        context,
    );
    return context.window.CRITIC_TIMELINE_DATA;
}

test('timeline viewer contains event-lease cases and fixed-policy controls', () => {
    const data = loadData();
    assert.equal(data.schemaVersion, 'critic_timeline_viewer.v3');
    assert.equal(data.defaultPolicy, 'event');
    assert.deepEqual(
        Array.from(data.trials, trial => trial.id),
        ['trial_106', 'trial_162'],
    );

    for (const trial of data.trials) {
        assert.equal(trial.criticsByPolicy.fixed.length, 3);
        assert.ok(trial.storyConclusion.length > 30);
        assert.ok(trial.fixedStoryConclusion.length > 30);
        assert.equal(trial.chapters[0].start, 0);
        assert.equal(trial.chapters.at(-1).end, trial.duration);
        assert.ok(trial.chapters.every((chapter, index) => (
            index === 0 || chapter.start === trial.chapters[index - 1].end
        )));
        assert.ok(trial.chapters.flatMap(chapter => chapter.eventIndexes)
            .every(index => trial.events[index]));
        assert.ok(trial.events.every(event => event.time >= 0 && event.time <= trial.duration));
        assert.ok(Object.values(trial.criticsByPolicy).flat().every(
            critic => critic.time > 0 && critic.time <= trial.duration,
        ));
        assert.ok(trial.progress.every(([time]) => time >= 0 && time <= trial.duration));
        assert.ok(fs.existsSync(path.resolve(VIEWER, trial.media.video)));
        assert.ok(fs.existsSync(path.resolve(VIEWER, trial.media.poster)));
        assert.ok(trial.media.frames.every(frame => fs.existsSync(path.resolve(VIEWER, frame.src))));
    }
});

test('trial 106 early snapshot preserves both overlapping long actions', () => {
    const data = loadData();
    const trial = data.trials.find(item => item.id === 'trial_106');
    const first = trial.criticsByPolicy.fixed[0];
    const acting = first.activeExecutions
        .filter(execution => execution.status === 'acting')
        .map(execution => execution.agent)
        .sort();
    assert.deepEqual(Array.from(acting), ['andy', 'bob']);
});

test('event leases avoid tactical interruption in trial 106', () => {
    const data = loadData();
    const trial = data.trials.find(item => item.id === 'trial_106');
    assert.equal(trial.criticsByPolicy.event.length, 1);
    assert.equal(trial.policySummary.event.tacticalEvaluations, 0);
    assert.equal(trial.policySummary.event.advisories, 0);
    assert.equal(trial.criticsByPolicy.event[0].triggerType, 'terminal_review');
    assert.equal(trial.chapters.length, 4);
});

test('trial 162 exposes the strongest handoff trigger and repeated episode', () => {
    const data = loadData();
    const trial = data.trials.find(item => item.id === 'trial_162');
    const critics = trial.criticsByPolicy.event;
    assert.equal(trial.chapters.length, 5);
    assert.equal(critics.length, 5);
    assert.equal(trial.policySummary.event.tacticalEvaluations, 4);
    assert.equal(trial.policySummary.event.advisories, 4);

    const handoff = critics.find(critic => critic.time === 263.956);
    assert.equal(handoff.triggerType, 'request_verification_still_unresolved');
    assert.equal(handoff.openWatches.coordination_requests[0].stage, 'verification_failed');

    const repeated = critics.filter(critic => [304.221, 380.108].includes(critic.time));
    assert.equal(repeated.length, 2);
    assert.ok(repeated.every(critic => critic.episode === 'E-02 资源交接'));
    assert.ok(repeated.every(critic => critic.episodeState === 'repeated'));

    const repeatedChapter = trial.chapters.find(chapter => chapter.id === 'repeated-episode');
    assert.ok(repeated.every(critic => (
        critic.time >= repeatedChapter.start && critic.time < repeatedChapter.end
    )));
});
