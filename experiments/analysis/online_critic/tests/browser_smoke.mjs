#!/usr/bin/env node

import assert from 'node:assert/strict';


const baseUrl = process.env.CRITIC_VIEWER_URL
    || 'http://127.0.0.1:8765/experiments/analysis/online_critic/timeline_viewer/';
const debugUrl = process.env.CHROME_DEBUG_URL || 'http://127.0.0.1:9223';
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

const target = await fetch(
    `${debugUrl}/json/new?${encodeURIComponent(`${baseUrl}#trial_106/story/event`)}`,
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

    const initial = await evaluate(`({
        hash: location.hash,
        policy: document.querySelector('[data-policy][aria-selected="true"]').dataset.policy,
        trial: document.querySelector('[data-trial][aria-selected="true"]').dataset.trial,
        chapters: document.querySelectorAll('.story-chapter').length,
        hasStoryConclusion: document.querySelector('#story-overview').innerText.includes('没有通过聊天完成明确分工'),
        mediaReady: Array.from(document.images).every(image => image.complete && image.naturalWidth > 0),
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth
    })`);
    assert.deepEqual(initial, {
        hash: '#trial_106/story/event',
        policy: 'event',
        trial: 'trial_106',
        chapters: 4,
        hasStoryConclusion: true,
        mediaReady: true,
        horizontalOverflow: false,
    });

    await evaluate(`document.querySelector('[data-trial="trial_162"]').click()`);
    await evaluate(`document.querySelector('[data-policy="fixed"]').click()`);
    const fixed = await evaluate(`({
        hash: location.hash,
        stats: document.querySelector('#policy-stats').innerText,
        usesFixedConclusion: document.querySelector('#story-overview').innerText.includes('固定策略')
    })`);
    assert.equal(fixed.hash, '#trial_162/story/fixed');
    assert.match(fixed.stats, /3 次评估/);
    assert.match(fixed.stats, /1 条上级建议/);
    assert.equal(fixed.usesFixedConclusion, true);

    await evaluate(`document.querySelector('[data-policy="event"]').click()`);
    await evaluate(`document.querySelector('[data-mode="audit"]').click()`);
    await evaluate(`document.querySelector('[data-select="critic:trial_162_online_t000263956"]').click()`);
    const eventAudit = await evaluate(`(() => {
        const nodes = Array.from(document.querySelectorAll('.critic-node'))
            .map(node => node.getBoundingClientRect());
        let overlaps = 0;
        for (let first = 0; first < nodes.length; first += 1) {
            for (let second = first + 1; second < nodes.length; second += 1) {
                const separated = nodes[first].right <= nodes[second].left
                    || nodes[second].right <= nodes[first].left
                    || nodes[first].bottom <= nodes[second].top
                    || nodes[second].bottom <= nodes[first].top;
                if (!separated) overlaps += 1;
            }
        }
        const inspector = document.querySelector('#inspector').innerText;
        return {
            hash: location.hash,
            criticNodes: nodes.length,
            criticNodeOverlaps: overlaps,
            hasStrongTrigger: inspector.includes('求助后的验证仍未解除阻塞'),
            hasEpisode: inspector.includes('E-02 资源交接'),
            hasFailedWatch: inspector.includes('verification_failed'),
            hasManagerAdvice: inspector.includes('给上级 Agent'),
            horizontalOverflow: document.documentElement.scrollWidth > innerWidth
        };
    })()`);
    assert.deepEqual(eventAudit, {
        hash: '#trial_162/audit/event',
        criticNodes: 5,
        criticNodeOverlaps: 0,
        hasStrongTrigger: true,
        hasEpisode: true,
        hasFailedWatch: true,
        hasManagerAdvice: true,
        horizontalOverflow: false,
    });

    await send('Emulation.setDeviceMetricsOverride', {
        width: 390,
        height: 844,
        deviceScaleFactor: 1,
        mobile: true,
    });
    await send('Page.navigate', { url: `${baseUrl}#trial_162/story/event` });
    await delay(900);
    const mobile = await evaluate(`({
        hash: location.hash,
        width: innerWidth,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        policyButtonsFit: Array.from(document.querySelectorAll('[data-policy]'))
            .every(button => button.scrollWidth <= button.clientWidth),
        storyChaptersFit: Array.from(document.querySelectorAll('.story-chapter'))
            .every(chapter => chapter.getBoundingClientRect().right <= innerWidth),
        processPanelsFit: Array.from(document.querySelectorAll('.process-board > *'))
            .every(panel => panel.scrollWidth <= panel.clientWidth),
        repeatedEpisodeGroups: Array.from(document.querySelectorAll('.chapter-critic'))
            .filter(group => group.innerText.includes('E-02 资源交接') && group.innerText.includes('检查 2 次')).length,
        mediaReady: Array.from(document.images).every(image => image.complete && image.naturalWidth > 0)
    })`);
    assert.deepEqual(mobile, {
        hash: '#trial_162/story/event',
        width: 390,
        horizontalOverflow: false,
        policyButtonsFit: true,
        storyChaptersFit: true,
        processPanelsFit: true,
        repeatedEpisodeGroups: 1,
        mediaReady: true,
    });

    assert.deepEqual(exceptions, []);
    process.stdout.write(`${JSON.stringify({ initial, fixed, eventAudit, mobile })}\n`);
} finally {
    socket.close();
    await fetch(`${debugUrl}/json/close/${target.id}`);
}
