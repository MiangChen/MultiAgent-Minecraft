(function () {
  'use strict';

  const gameData = window.CRITIC_GAME_DATA;
  const timelineData = window.CRITIC_TIMELINE_DATA;
  if (!gameData || !timelineData) {
    document.body.innerHTML = '<p class="load-error">游戏数据未生成。</p>';
    return;
  }

  const dom = {
    tabs: document.querySelector('#scenario-tabs'),
    score: document.querySelector('#score-value'),
    scenarioId: document.querySelector('#scenario-id'),
    scenarioName: document.querySelector('#scenario-name'),
    mission: document.querySelector('#scenario-mission'),
    progress: document.querySelector('#stage-progress'),
    gameStage: document.querySelector('#game-stage'),
    sceneFrame: document.querySelector('#scene-frame'),
    sceneImage: document.querySelector('#scene-image'),
    sceneVideo: document.querySelector('#scene-video'),
    replayButton: document.querySelector('#replay-button'),
    sceneTime: document.querySelector('#scene-time'),
    sceneTitle: document.querySelector('#scene-title'),
    worldScore: document.querySelector('#world-score'),
    worldState: document.querySelector('#world-state'),
    andyState: document.querySelector('#andy-state'),
    andyDetail: document.querySelector('#andy-detail'),
    bobState: document.querySelector('#bob-state'),
    bobDetail: document.querySelector('#bob-detail'),
    stageLabel: document.querySelector('#stage-label'),
    question: document.querySelector('#stage-question'),
    facts: document.querySelector('#fact-list'),
    choices: document.querySelector('#choice-list'),
    reveal: document.querySelector('#reveal-panel'),
    back: document.querySelector('#back-button'),
    next: document.querySelector('#next-button'),
    decisionStatus: document.querySelector('#decision-status'),
    debrief: document.querySelector('#debrief'),
  };

  const storageKey = 'critic-coordination-game.v1';
  const scenarios = new Map(gameData.scenarios.map(scenario => [scenario.id, scenario]));
  const hashParts = window.location.hash.replace(/^#/, '').split('/');
  const initialScenario = scenarios.get(hashParts[0]) || scenarios.get(gameData.defaultScenario);

  function freshSessions() {
    return Object.fromEntries(gameData.scenarios.map(scenario => [scenario.id, {
      stepIndex: 0,
      answers: {},
      debrief: false,
    }]));
  }

  function loadSessions() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey));
      const sessions = freshSessions();
      for (const scenario of gameData.scenarios) {
        if (!saved?.[scenario.id]) continue;
        sessions[scenario.id].stepIndex = Math.max(0, Math.min(
          scenario.steps.length - 1,
          Number(saved[scenario.id].stepIndex) || 0,
        ));
        sessions[scenario.id].answers = saved[scenario.id].answers || {};
        sessions[scenario.id].debrief = Boolean(saved[scenario.id].debrief);
      }
      return sessions;
    } catch {
      return freshSessions();
    }
  }

  const state = {
    scenarioId: initialScenario.id,
    sessions: loadSessions(),
    videoToken: 0,
  };

  const requestedStage = /^stage-(\d+)$/.exec(hashParts[1] || '');
  if (requestedStage) {
    state.sessions[state.scenarioId].stepIndex = Math.min(
      initialScenario.steps.length - 1,
      Math.max(0, Number(requestedStage[1]) - 1),
    );
    state.sessions[state.scenarioId].debrief = false;
  } else if (hashParts[1] === 'debrief') {
    state.sessions[state.scenarioId].debrief = true;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function formatTime(seconds) {
    const safe = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(safe / 60);
    const remainder = Math.floor(safe % 60);
    return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  }

  function scenario() {
    return scenarios.get(state.scenarioId);
  }

  function session() {
    return state.sessions[state.scenarioId];
  }

  function timelineTrial() {
    return timelineData.trials.find(trial => trial.id === state.scenarioId);
  }

  function currentStep() {
    return scenario().steps[session().stepIndex];
  }

  function selectedChoice(step = currentStep()) {
    const choiceId = session().answers[step.id];
    return step.choices.find(choice => choice.id === choiceId) || null;
  }

  function save() {
    sessionStorage.setItem(storageKey, JSON.stringify(state.sessions));
  }

  function updateHash() {
    const suffix = session().debrief ? 'debrief' : `stage-${session().stepIndex + 1}`;
    const next = `#${state.scenarioId}/${suffix}`;
    if (window.location.hash !== next) history.replaceState(null, '', next);
  }

  function scoreSummary() {
    const currentScenario = scenario();
    const earned = currentScenario.steps.reduce((sum, step) => {
      const answerId = session().answers[step.id];
      const choice = step.choices.find(item => item.id === answerId);
      return sum + (choice?.points || 0);
    }, 0);
    return { earned, maximum: currentScenario.steps.length * 2 };
  }

  function evidenceLink(ref) {
    const trace = /^trace\/(.+?)(?::(\d+))?$/.exec(ref);
    if (trace) {
      const line = trace[2] ? `#L${trace[2]}` : '';
      return `../../../out/${state.scenarioId}/trace/${trace[1]}${line}`;
    }
    if (ref.startsWith('derived/')) return `../${ref}`;
    return null;
  }

  function renderEvidence(refs) {
    return refs.map(ref => {
      const href = evidenceLink(ref);
      return href
        ? `<li><a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(ref)}</a></li>`
        : `<li><code>${escapeHtml(ref)}</code></li>`;
    }).join('');
  }

  function grade(choice) {
    if (!choice) return { label: '等待判断', className: 'pending' };
    if (choice.points === 2) return { label: '证据稳健 · +2', className: 'strong' };
    if (choice.points === 1) return { label: '方向接近 · +1', className: 'close' };
    return { label: '需要复核 · +0', className: 'review' };
  }

  function renderTabs() {
    dom.tabs.innerHTML = gameData.scenarios.map(item => (
      `<button type="button" data-scenario="${escapeHtml(item.id)}" aria-current="${item.id === state.scenarioId ? 'page' : 'false'}">
        <span>${escapeHtml(item.id)}</span>
        <strong>${escapeHtml(item.name)}</strong>
      </button>`
    )).join('');
    dom.tabs.querySelectorAll('[data-scenario]').forEach(button => {
      button.addEventListener('click', () => switchScenario(button.dataset.scenario));
    });
  }

  function renderMission() {
    const currentScenario = scenario();
    const currentSession = session();
    const maxUnlocked = Math.min(
      currentScenario.steps.length - 1,
      Object.keys(currentSession.answers).length,
    );
    dom.scenarioId.textContent = currentScenario.id;
    dom.scenarioName.textContent = currentScenario.name;
    dom.mission.textContent = currentScenario.mission;
    dom.progress.innerHTML = currentScenario.steps.map((step, index) => {
      const answered = Boolean(currentSession.answers[step.id]);
      const current = !currentSession.debrief && index === currentSession.stepIndex;
      const disabled = index > maxUnlocked;
      return `<button type="button" data-progress-step="${index}" class="${answered ? 'is-complete' : ''} ${current ? 'is-current' : ''}" ${disabled ? 'disabled' : ''} aria-label="第 ${index + 1} 幕：${escapeHtml(step.title)}">
        <span>${answered ? '✓' : index + 1}</span>
        <strong>${escapeHtml(step.title)}</strong>
      </button>`;
    }).join('');
    dom.progress.querySelectorAll('[data-progress-step]').forEach(button => {
      button.addEventListener('click', () => goToStep(Number(button.dataset.progressStep)));
    });
  }

  function resetSceneMedia() {
    state.videoToken += 1;
    dom.sceneVideo.pause();
    dom.sceneVideo.hidden = true;
    dom.sceneImage.hidden = false;
    dom.replayButton.textContent = '▶';
    dom.replayButton.setAttribute('aria-label', '回放这个时刻');
    dom.replayButton.title = '回放这个时刻';
  }

  function renderScene(step) {
    const trial = timelineTrial();
    const frame = trial.media.frames[step.frameIndex];
    resetSceneMedia();
    dom.sceneImage.src = frame.src;
    dom.sceneImage.alt = `${state.scenarioId}：${step.title}`;
    dom.sceneVideo.src = trial.media.video;
    dom.sceneTime.textContent = `${formatTime(step.time)} · ${step.world.score}`;
    dom.sceneTitle.textContent = step.title;
    dom.worldScore.textContent = step.world.score;
    dom.worldState.textContent = step.world.state;
    dom.andyState.textContent = step.actors.andy.state;
    dom.andyDetail.textContent = step.actors.andy.detail;
    dom.bobState.textContent = step.actors.bob.state;
    dom.bobDetail.textContent = step.actors.bob.detail;
  }

  function renderFacts(step) {
    dom.facts.innerHTML = step.facts.map(fact => (
      `<div class="fact-row ${escapeHtml(fact.certainty.toLowerCase())}">
        <span>${escapeHtml(fact.certainty)}</span>
        <p>${escapeHtml(fact.text)}</p>
      </div>`
    )).join('');
  }

  function renderChoices(step, answer) {
    dom.choices.innerHTML = step.choices.map((choice, index) => {
      const selected = answer?.id === choice.id;
      const recommended = Boolean(answer) && choice.id === step.recommendedChoice;
      const classNames = [selected ? 'is-selected' : '', recommended ? 'is-recommended' : ''].filter(Boolean).join(' ');
      return `<button type="button" class="choice-button ${classNames}" data-choice="${escapeHtml(choice.id)}" ${answer ? 'disabled' : ''}>
        <span class="choice-key">${String.fromCharCode(65 + index)}</span>
        <span class="choice-copy">
          <strong>${escapeHtml(choice.label)}</strong>
          <span>${escapeHtml(choice.detail)}</span>
        </span>
        ${recommended ? '<span class="recommended-mark">证据更稳健</span>' : ''}
      </button>`;
    }).join('');
    dom.choices.querySelectorAll('[data-choice]').forEach(button => {
      button.addEventListener('click', () => choose(button.dataset.choice));
    });
  }

  function revealHtml(step, answer) {
    const result = grade(answer);
    const chain = step.chain.map((item, index) => (
      `${index ? '<span class="chain-arrow" aria-hidden="true">→</span>' : ''}<span class="chain-node" style="--chain-index:${index}">${escapeHtml(item)}</span>`
    )).join('');
    const modeLabels = {
      silent: '保持观察',
      triggered: '建议介入',
      contested: 'Critic 也需要复核',
      terminal: '关闭 episode',
    };
    return `<div class="choice-feedback ${escapeHtml(result.className)}">
      <strong>${escapeHtml(result.label)}</strong>
      <p>${escapeHtml(answer.feedback)}</p>
    </div>
    <div class="causal-reveal">
      <span>当时的因果链</span>
      <div class="cause-chain">${chain}</div>
    </div>
    <div class="critic-reveal ${escapeHtml(step.reveal.mode)}">
      <div class="critic-reveal-heading">
        <span>CRITIC · ${escapeHtml(modeLabels[step.reveal.mode])}</span>
        <strong>${escapeHtml(step.reveal.episode)}</strong>
        ${step.reveal.criticTime ? `<time>${Number(step.reveal.criticTime).toFixed(3)}s</time>` : ''}
      </div>
      <h3>${escapeHtml(step.reveal.headline)}</h3>
      <p>${escapeHtml(step.reveal.explanation)}</p>
      <div class="critic-advice"><span>给上级 Agent</span><p>${escapeHtml(step.reveal.advice)}</p></div>
    </div>
    <div class="outcome-reveal">
      <div>
        <span>${escapeHtml(step.reveal.posthocLabel)}</span>
        <p>${escapeHtml(step.reveal.posthoc)}</p>
      </div>
      <div>
        <span>后来发生</span>
        <p>${escapeHtml(step.reveal.later)}</p>
      </div>
    </div>
    <details class="evidence-drawer">
      <summary>证据档案 · ${step.evidence.length} 项</summary>
      <ul>${renderEvidence(step.evidence)}</ul>
      <p>影子回放中的建议没有发送给执行 Agent，后验结果不能证明真实干预效果。</p>
    </details>`;
  }

  function renderStage() {
    const currentScenario = scenario();
    const currentSession = session();
    const step = currentStep();
    const answer = selectedChoice(step);
    const result = grade(answer);
    dom.gameStage.hidden = false;
    dom.debrief.hidden = true;
    dom.stageLabel.textContent = `第 ${currentSession.stepIndex + 1} 幕 / 共 ${currentScenario.steps.length} 幕`;
    dom.question.textContent = step.question;
    renderScene(step);
    renderFacts(step);
    renderChoices(step, answer);
    dom.reveal.hidden = !answer;
    dom.reveal.innerHTML = answer ? revealHtml(step, answer) : '';
    dom.decisionStatus.textContent = result.label;
    dom.decisionStatus.className = result.className;
    dom.back.disabled = currentSession.stepIndex === 0;
    dom.next.disabled = !answer;
    dom.next.innerHTML = currentSession.stepIndex === currentScenario.steps.length - 1
      ? '查看结案 <span aria-hidden="true">→</span>'
      : '继续 <span aria-hidden="true">→</span>';
  }

  function debriefGrade(earned, maximum) {
    const ratio = maximum ? earned / maximum : 0;
    if (ratio >= 0.85) return {
      title: '你的判断紧贴证据链',
      text: '你能区分语言承诺、真实执行和世界结果，也能在 Critic 过早重复提醒时保持审慎。',
    };
    if (ratio >= 0.6) return {
      title: '你抓住了主线，但有几处容易过早介入',
      text: '回看标记为“方向接近”或“需要复核”的步骤，重点检查当时是否已经出现结果验证。',
    };
    return {
      title: '你的判断更依赖表面忙碌或语言承诺',
      text: '建议重新走一遍，把每一步都推进到“行动是否开始、世界是否改变、结果是否验证”。',
    };
  }

  function renderDebrief() {
    resetSceneMedia();
    const currentScenario = scenario();
    const summary = scoreSummary();
    const result = debriefGrade(summary.earned, summary.maximum);
    const rows = currentScenario.steps.map((step, index) => {
      const answerId = session().answers[step.id];
      const answer = step.choices.find(choice => choice.id === answerId);
      const recommended = step.choices.find(choice => choice.id === step.recommendedChoice);
      return `<div class="debrief-row">
        <span>${index + 1}</span>
        <div><strong>${escapeHtml(step.title)}</strong><p>你的动作：${escapeHtml(answer?.label || '未作答')}</p></div>
        <div class="${answer?.id === recommended.id ? 'matched' : ''}"><strong>证据更稳健</strong><p>${escapeHtml(recommended.label)}</p></div>
      </div>`;
    }).join('');
    dom.gameStage.hidden = true;
    dom.debrief.hidden = false;
    dom.debrief.innerHTML = `<div class="debrief-heading">
      <div class="final-score"><span>本轮审计判断</span><strong>${summary.earned} / ${summary.maximum}</strong></div>
      <div><span>${escapeHtml(currentScenario.id)} · ${escapeHtml(currentScenario.name)}</span><h2>${escapeHtml(result.title)}</h2><p>${escapeHtml(result.text)}</p></div>
    </div>
    <div class="debrief-table">${rows}</div>
    <div class="debrief-actions">
      <button type="button" id="restart-button">↻ 重新推演</button>
      <a href="../timeline_viewer/#${escapeHtml(currentScenario.id)}/audit/event">打开完整证据审计台 <span aria-hidden="true">→</span></a>
    </div>
    <p class="debrief-boundary">这是只读 shadow replay。你的选择和 Critic 建议都没有改变原始实验轨迹。</p>`;
    dom.debrief.querySelector('#restart-button').addEventListener('click', restartScenario);
  }

  function renderScore() {
    const summary = scoreSummary();
    dom.score.textContent = `${summary.earned} / ${summary.maximum}`;
  }

  function render() {
    renderTabs();
    renderMission();
    renderScore();
    if (session().debrief) renderDebrief();
    else renderStage();
    updateHash();
  }

  function choose(choiceId) {
    const step = currentStep();
    if (session().answers[step.id]) return;
    const choice = step.choices.find(item => item.id === choiceId);
    if (!choice) return;
    session().answers[step.id] = choiceId;
    save();
    render();
  }

  function goToStep(index) {
    const maxUnlocked = Math.min(
      scenario().steps.length - 1,
      Object.keys(session().answers).length,
    );
    if (!Number.isInteger(index) || index < 0 || index > maxUnlocked) return;
    session().stepIndex = index;
    session().debrief = false;
    save();
    render();
  }

  function next() {
    if (!selectedChoice()) return;
    if (session().stepIndex === scenario().steps.length - 1) {
      session().debrief = true;
    } else {
      session().stepIndex += 1;
    }
    save();
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function back() {
    if (session().stepIndex === 0) return;
    session().stepIndex -= 1;
    session().debrief = false;
    save();
    render();
  }

  function switchScenario(scenarioId) {
    if (!scenarios.has(scenarioId) || scenarioId === state.scenarioId) return;
    state.scenarioId = scenarioId;
    save();
    render();
  }

  function restartScenario() {
    state.sessions[state.scenarioId] = { stepIndex: 0, answers: {}, debrief: false };
    save();
    render();
  }

  function toggleReplay() {
    if (!dom.sceneVideo.hidden) {
      resetSceneMedia();
      return;
    }
    const token = ++state.videoToken;
    const trial = timelineTrial();
    const targetTime = currentStep().time / trial.media.playbackRate;
    dom.sceneImage.hidden = true;
    dom.sceneVideo.hidden = false;
    dom.replayButton.textContent = '■';
    dom.replayButton.setAttribute('aria-label', '停止回放');
    dom.replayButton.title = '停止回放';
    const startPlayback = () => {
      if (token !== state.videoToken) return;
      dom.sceneVideo.currentTime = Math.min(targetTime, dom.sceneVideo.duration || targetTime);
      dom.sceneVideo.play().catch(() => {});
    };
    if (dom.sceneVideo.readyState >= 1) startPlayback();
    else dom.sceneVideo.addEventListener('loadedmetadata', startPlayback, { once: true });
  }

  dom.back.addEventListener('click', back);
  dom.next.addEventListener('click', next);
  dom.replayButton.addEventListener('click', toggleReplay);

  render();
}());
