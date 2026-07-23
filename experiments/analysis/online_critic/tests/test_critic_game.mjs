#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';


const HERE = path.dirname(fileURLToPath(import.meta.url));
const GAME = path.resolve(HERE, '../critic_game');
const VIEWER = path.resolve(HERE, '../timeline_viewer');

function loadBrowserData(filePath, property) {
    const context = { window: {} };
    vm.runInNewContext(fs.readFileSync(filePath, 'utf8'), context);
    return context.window[property];
}

const gameData = loadBrowserData(
    path.join(GAME, 'game_data.js'),
    'CRITIC_GAME_DATA',
);
const timelineData = loadBrowserData(
    path.join(VIEWER, 'timeline_data.js'),
    'CRITIC_TIMELINE_DATA',
);

test('guided game has two evidence-bounded scenarios', () => {
    assert.equal(gameData.schemaVersion, 'critic_coordination_game.v1');
    assert.equal(gameData.defaultScenario, 'trial_162');
    assert.deepEqual(
        Array.from(gameData.scenarios, scenario => scenario.id),
        ['trial_162', 'trial_106'],
    );

    for (const scenario of gameData.scenarios) {
        const trial = timelineData.trials.find(item => item.id === scenario.id);
        assert.ok(trial);
        assert.ok(scenario.steps.length >= 4);
        assert.equal(scenario.steps.at(-1).reveal.mode, 'terminal');
        assert.ok(scenario.steps.every((step, index) => (
            step.time > 0
            && step.time <= trial.duration
            && (index === 0 || step.time > scenario.steps[index - 1].time)
        )));
        assert.ok(scenario.steps.every(step => trial.media.frames[step.frameIndex]));
        assert.ok(scenario.steps.every(step => step.evidence.length >= 3));
        assert.ok(scenario.steps.every(step => step.facts.every(fact => ['O', 'I'].includes(fact.certainty))));
        assert.ok(scenario.steps.every(step => {
            const ids = new Set(step.choices.map(choice => choice.id));
            const recommended = step.choices.find(choice => choice.id === step.recommendedChoice);
            return ids.size === step.choices.length
                && step.choices.length === 3
                && recommended?.points === 2;
        }));
    }
});

test('trial 162 makes the handoff strong point and early repeat explicit', () => {
    const scenario = gameData.scenarios.find(item => item.id === 'trial_162');
    const handoff = scenario.steps.find(step => step.time === 263.956);
    assert.equal(handoff.reveal.episode, 'E-02 资源交接');
    assert.match(handoff.reveal.headline, /证据最完整/);
    assert.deepEqual(
        Array.from(handoff.chain),
        ['定向请求', 'Bob 确认', '行动声明', '没有命令开始', '验证仍失败'],
    );

    const repeat = scenario.steps.find(step => step.time === 380.108);
    assert.equal(repeat.reveal.mode, 'contested');
    assert.match(repeat.reveal.headline, /偏早/);
    assert.equal(repeat.recommendedChoice, 'update-and-wait');
});

test('trial 106 is a non-interruption lesson', () => {
    const scenario = gameData.scenarios.find(item => item.id === 'trial_106');
    assert.ok(scenario.steps.slice(0, -1).every(step => step.reveal.mode === 'silent'));
    assert.ok(scenario.steps.every(step => step.recommendedChoice !== 'stop-conflict'));
    assert.match(scenario.steps.at(-1).reveal.posthoc, /没有在顺利并行阶段插入战术检查/);
});
