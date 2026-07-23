#!/usr/bin/env node

import { readFile } from 'fs/promises';
import { createModel, selectAPI } from '../../../src/models/_model_map.js';


const profilePath = process.argv[2];
if (!profilePath) {
    console.error('Usage: node model_bridge.mjs <model-profile.json>');
    process.exit(2);
}

let prompt = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) {
    prompt += chunk;
}
if (!prompt.trim()) {
    console.error('Critic prompt is empty.');
    process.exit(2);
}

const profile = JSON.parse(await readFile(profilePath, 'utf8'));

// The shared GPT adapter logs progress through console.log. Keep stdout reserved
// for the model response so the Python runner can parse it as JSON.
console.log = (...args) => {
    const safe = args.map(value => {
        if (typeof value === 'string') return value;
        return value?.message || value?.code || value?.name || typeof value;
    });
    console.error(...safe);
};

const model = createModel(selectAPI(profile));
const response = await model.sendRequest([], prompt);
if (typeof response !== 'string' || response === 'My brain disconnected, try again.') {
    console.error('The shared model adapter did not return a model response.');
    process.exit(1);
}
process.stdout.write(response.trim());
