#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';


const baseUrl = process.env.CRITIC_GAME_URL
    || 'http://127.0.0.1:8765/experiments/analysis/online_critic/critic_game/';
const debugUrl = process.env.CHROME_DEBUG_URL || 'http://127.0.0.1:9223';
const screenshotDir = process.env.CRITIC_GAME_SCREENSHOT_DIR;
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

const target = await fetch(
    `${debugUrl}/json/new?${encodeURIComponent(`${baseUrl}#trial_162/stage-1`)}`,
    { method: 'PUT' },
).then(response => response.json());
const socket = new WebSocket(target.webSocketDebuggerUrl);

await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
});

let callId = 0;
const pending = new Map();
const exceptions = [];

socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') {
        exceptions.push(message.params.exceptionDetails.text);
    }
    if (!message.id || !pending.has(message.id)) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) request.reject(new Error(JSON.stringify(message.error)));
    else request.resolve(message.result);
});

function send(method, params = {}) {
    const id = ++callId;
    socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression) {
    const result = await send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true,
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
}

async function click(selector) {
    const clicked = await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        if (!element) return false;
        element.click();
        return true;
    })()`);
    assert.equal(clicked, true, `missing selector: ${selector}`);
    await delay(80);
}

async function capture(name) {
    if (!screenshotDir) return;
    const result = await send('Page.captureScreenshot', {
        format: 'png',
        fromSurface: true,
        captureBeyondViewport: false,
    });
    fs.writeFileSync(`${screenshotDir}/${name}.png`, Buffer.from(result.data, 'base64'));
}

try {
    await send('Runtime.enable');
    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', {
        width: 1440,
        height: 1000,
        deviceScaleFactor: 1,
        mobile: false,
    });
    await delay(900);
    await evaluate(`sessionStorage.clear(); location.reload()`);
    await delay(900);

    const initial = await evaluate(`({
        hash: location.hash,
        scenario: document.querySelector('[data-scenario][aria-current="page"]').dataset.scenario,
        stages: document.querySelectorAll('[data-progress-step]').length,
        score: document.querySelector('#score-value').innerText,
        mediaReady: document.querySelector('#scene-image').complete
            && document.querySelector('#scene-image').naturalWidth > 0,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth
    })`);
    assert.deepEqual(initial, {
        hash: '#trial_162/stage-1',
        scenario: 'trial_162',
        stages: 5,
        score: '0 / 10',
        mediaReady: true,
        horizontalOverflow: false,
    });
    await capture('critic-game-initial-desktop');

    await click('[data-choice="observe"]');
    const firstReveal = await evaluate(`({
        score: document.querySelector('#score-value').innerText,
        revealVisible: !document.querySelector('#reveal-panel').hidden,
        chainNodes: document.querySelectorAll('.chain-node').length,
        nextEnabled: !document.querySelector('#next-button').disabled,
        grade: document.querySelector('#decision-status').innerText
    })`);
    assert.deepEqual(firstReveal, {
        score: '2 / 10',
        revealVisible: true,
        chainNodes: 3,
        nextEnabled: true,
        grade: '证据稳健 · +2',
    });

    await click('#next-button');
    await click('[data-choice="blame-bob"]');
    assert.equal(await evaluate(`document.querySelector('#decision-status').innerText`), '需要复核 · +0');
    assert.equal(await evaluate(`document.querySelectorAll('.choice-button.is-recommended').length`), 1);

    await click('[data-progress-step="0"]');
    assert.equal(await evaluate(`document.querySelectorAll('.choice-button:disabled').length`), 3);
    assert.equal(await evaluate(`document.querySelector('#reveal-panel').hidden`), false);

    await click('[data-scenario="trial_106"]');
    const switched = await evaluate(`({
        hash: location.hash,
        stages: document.querySelectorAll('[data-progress-step]').length,
        score: document.querySelector('#score-value').innerText
    })`);
    assert.deepEqual(switched, {
        hash: '#trial_106/stage-1',
        stages: 4,
        score: '0 / 8',
    });

    await click('[data-scenario="trial_162"]');
    await click('[data-progress-step="1"]');
    await click('#next-button');
    await click('[data-choice="require-action"]');
    await click('#next-button');
    await click('[data-choice="update-and-wait"]');
    const contested = await evaluate(`({
        hash: location.hash,
        headline: document.querySelector('.critic-reveal h3').innerText,
        mode: document.querySelector('.critic-reveal').classList.contains('contested'),
        score: document.querySelector('#score-value').innerText
    })`);
    assert.deepEqual(contested, {
        hash: '#trial_162/stage-4',
        headline: 'Critic 实际再次建议介入，但复盘认为这次偏早。',
        mode: true,
        score: '6 / 10',
    });
    await evaluate(`document.querySelector('#reveal-panel').scrollIntoView({ block: 'start' })`);
    await delay(100);
    await capture('critic-game-contested-desktop');

    await click('#replay-button');
    assert.equal(await evaluate(`document.querySelector('#scene-video').hidden`), false);
    assert.equal(await evaluate(`document.querySelector('#scene-image').hidden`), true);
    await click('#replay-button');

    await send('Emulation.setDeviceMetricsOverride', {
        width: 390,
        height: 844,
        deviceScaleFactor: 1,
        mobile: true,
    });
    await delay(200);
    const mobile = await evaluate(`({
        width: innerWidth,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        choicesFit: Array.from(document.querySelectorAll('.choice-button'))
            .every(choice => choice.getBoundingClientRect().right <= innerWidth),
        textFits: Array.from(document.querySelectorAll('.choice-copy'))
            .every(copy => copy.scrollWidth <= copy.clientWidth),
        revealFits: document.querySelector('#reveal-panel').getBoundingClientRect().right <= innerWidth
    })`);
    assert.deepEqual(mobile, {
        width: 390,
        horizontalOverflow: false,
        choicesFit: true,
        textFits: true,
        revealFits: true,
    });
    await evaluate(`document.querySelector('#reveal-panel').scrollIntoView({ block: 'start' })`);
    await delay(100);
    await capture('critic-game-contested-mobile');

    await click('#next-button');
    await click('[data-choice="close-record"]');
    await click('#next-button');
    const debrief = await evaluate(`({
        hash: location.hash,
        visible: !document.querySelector('#debrief').hidden,
        stageDisplay: getComputedStyle(document.querySelector('#game-stage')).display,
        debriefDisplay: getComputedStyle(document.querySelector('#debrief')).display,
        rows: document.querySelectorAll('.debrief-row').length,
        score: document.querySelector('.final-score strong').innerText,
        auditLink: document.querySelector('.debrief-actions a').getAttribute('href')
    })`);
    assert.deepEqual(debrief, {
        hash: '#trial_162/debrief',
        visible: true,
        stageDisplay: 'none',
        debriefDisplay: 'block',
        rows: 5,
        score: '8 / 10',
        auditLink: '../timeline_viewer/#trial_162/audit/event',
    });
    await evaluate(`scrollTo(0, 0)`);
    await delay(100);
    await capture('critic-game-debrief-mobile');

    assert.deepEqual(exceptions, []);
    process.stdout.write(`${JSON.stringify({ initial, firstReveal, switched, contested, mobile, debrief })}\n`);
} finally {
    socket.close();
    await fetch(`${debugUrl}/json/close/${target.id}`);
}
