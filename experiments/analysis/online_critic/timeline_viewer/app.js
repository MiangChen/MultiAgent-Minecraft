(function () {
  'use strict';

  const data = window.CRITIC_TIMELINE_DATA;
  if (!data || !Array.isArray(data.trials) || data.trials.length === 0) {
    document.body.innerHTML = '<p class="load-error">时间线数据未生成，请先运行 build_timeline_data.mjs。</p>';
    return;
  }

  const labelNames = {
    workload_concentration: '工作集中',
    duplicated_scope: '范围重复',
    idle_while_peer_overloaded: '闲置 / 同伴过载',
    blocked_dependency: '依赖阻塞',
    failed_handoff: '交接失败',
    role_action_mismatch: '角色行动不匹配',
    conflicting_world_actions: '世界行动冲突',
  };

  const typeNames = {
    action: '执行',
    check: '检查',
    goal: '目标',
    system: '系统',
    message: '消息',
    strategy: '策略改变',
    progress: '进度',
    plateau: '平台',
    anomaly: '状态损失',
    repair: '修复',
    success: '完成',
  };

  const triggerNames = {
    action_closed_without_verified_progress: '行动结束，无可验证进展',
    request_verification_still_unresolved: '求助后的验证仍未解除阻塞',
    score_regression: '世界得分回退',
    terminal_review: '终局复盘',
    time_interval: '固定时间截点',
  };

  const dom = {
    tabs: document.querySelector('#trial-tabs'),
    modeButtons: Array.from(document.querySelectorAll('[data-mode]')),
    caseId: document.querySelector('#case-id'),
    title: document.querySelector('#case-title'),
    subtitle: document.querySelector('#case-subtitle'),
    synopsis: document.querySelector('#case-synopsis'),
    metrics: document.querySelector('#metric-row'),
    boundary: document.querySelector('#boundary-note'),
    video: document.querySelector('#case-video'),
    frames: document.querySelector('#frame-strip'),
    policySwitch: document.querySelector('#policy-switch'),
    policyName: document.querySelector('#policy-name'),
    policyDescription: document.querySelector('#policy-description'),
    policyStats: document.querySelector('#policy-stats'),
    scrubber: document.querySelector('#time-scrubber'),
    cursorTime: document.querySelector('#cursor-time'),
    cursorScore: document.querySelector('#cursor-score'),
    duration: document.querySelector('#duration-time'),
    phaseRail: document.querySelector('#phase-rail'),
    storyView: document.querySelector('#story-view'),
    storyOverview: document.querySelector('#story-overview'),
    storyFeed: document.querySelector('#story-feed'),
    auditView: document.querySelector('#audit-view'),
    timeline: document.querySelector('#timeline-canvas'),
    timelineScroll: document.querySelector('#timeline-scroll'),
    keyFilter: document.querySelector('#key-filter'),
    inspector: document.querySelector('#inspector'),
  };

  const initialHash = window.location.hash.replace(/^#/, '').split('/');
  const initialTrial = data.trials.find(trial => trial.id === initialHash[0]) || data.trials[0];
  const state = {
    trial: initialTrial,
    mode: initialHash[1] === 'audit' ? 'audit' : 'story',
    policy: initialHash[2] === 'fixed' ? 'fixed' : data.defaultPolicy,
    cursor: 0,
    selected: null,
    videoSyncing: false,
  };

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

  function formatPreciseTime(seconds) {
    return `${Number(seconds).toFixed(Number(seconds) < 10 ? 3 : 1)}s`;
  }

  function scoreAt(trial, time) {
    let score = trial.progress[0][1];
    for (const point of trial.progress) {
      if (point[0] > time) break;
      score = point[1];
    }
    return score;
  }

  function currentCritics() {
    return state.trial.criticsByPolicy[state.policy] || [];
  }

  function evidenceLink(ref, trial) {
    const trace = /^trace\/(.+?)(?::(\d+))?$/.exec(ref);
    if (trace) {
      const line = trace[2] ? `#L${trace[2]}` : '';
      return `../../../out/${trial.id}/trace/${trace[1]}${line}`;
    }
    if (ref.startsWith('derived/')) return `../${ref}`;
    return null;
  }

  function renderEvidence(refs, trial) {
    return (refs || []).map(ref => {
      const href = evidenceLink(ref, trial);
      const label = escapeHtml(ref);
      return href
        ? `<li><a href="${escapeHtml(href)}">${label}</a></li>`
        : `<li><code>${label}</code></li>`;
    }).join('');
  }

  function renderTabs() {
    dom.tabs.innerHTML = data.trials.map(trial => (
      `<button type="button" role="tab" data-trial="${escapeHtml(trial.id)}" aria-selected="${trial.id === state.trial.id}">${escapeHtml(trial.id)}</button>`
    )).join('');
    dom.tabs.querySelectorAll('[data-trial]').forEach(button => {
      button.addEventListener('click', () => switchTrial(button.dataset.trial));
    });
  }

  function switchTrial(trialId) {
    const next = data.trials.find(trial => trial.id === trialId);
    if (!next || next.id === state.trial.id) return;
    state.trial = next;
    state.cursor = 0;
    state.selected = null;
    render();
  }

  function switchPolicy(policy) {
    if (!data.policies[policy] || policy === state.policy) return;
    state.policy = policy;
    state.selected = null;
    renderPolicy();
    renderStory();
    renderAudit();
    renderInspector();
    updateCursor();
    updateHash();
  }

  function setMode(mode) {
    state.mode = mode;
    dom.modeButtons.forEach(button => {
      button.setAttribute('aria-selected', String(button.dataset.mode === mode));
    });
    dom.storyView.hidden = mode !== 'story';
    dom.auditView.hidden = mode !== 'audit';
    updateHash();
  }

  function updateHash() {
    const next = `#${state.trial.id}/${state.mode}/${state.policy}`;
    if (window.location.hash !== next) history.replaceState(null, '', next);
  }

  function renderOverview() {
    const trial = state.trial;
    dom.caseId.textContent = `${trial.id} · ${trial.condition}`;
    dom.title.textContent = trial.title;
    dom.subtitle.textContent = trial.subtitle;
    dom.synopsis.textContent = trial.synopsis;
    dom.metrics.innerHTML = trial.metrics.map(metric => (
      `<div class="metric"><dt>${escapeHtml(metric.label)}</dt><dd>${escapeHtml(metric.value)}</dd></div>`
    )).join('');
    dom.boundary.textContent = data.evidenceBoundary;

    dom.video.pause();
    dom.video.src = trial.media.video;
    dom.video.poster = trial.media.poster;
    dom.video.load();
    dom.frames.innerHTML = trial.media.frames.map((frame, index) => (
      `<button type="button" class="frame-button" data-frame-index="${index}" data-time="${frame.time}">
        <img src="${escapeHtml(frame.src)}" alt="${escapeHtml(trial.id)}：${escapeHtml(frame.label)}">
        <span>${formatTime(frame.time)} · ${escapeHtml(frame.label)}</span>
      </button>`
    )).join('');
    dom.frames.querySelectorAll('[data-time]').forEach(button => {
      button.addEventListener('click', () => seekTo(Number(button.dataset.time), true));
    });

    dom.scrubber.max = String(trial.duration);
    dom.scrubber.value = String(state.cursor);
    dom.duration.textContent = formatTime(trial.duration);
  }

  function renderPolicy() {
    const policy = data.policies[state.policy];
    const summary = state.trial.policySummary[state.policy];
    dom.policySwitch.innerHTML = Object.entries(data.policies).map(([key, item]) => (
      `<button type="button" role="tab" data-policy="${escapeHtml(key)}" aria-selected="${key === state.policy}">${escapeHtml(item.shortLabel)}</button>`
    )).join('');
    dom.policySwitch.querySelectorAll('[data-policy]').forEach(button => {
      button.addEventListener('click', () => switchPolicy(button.dataset.policy));
    });
    dom.policyName.textContent = policy.label;
    dom.policyDescription.textContent = policy.description;
    dom.policyStats.innerHTML = `
      <span><strong>${summary.evaluations}</strong> 次评估</span>
      <span><strong>${summary.tacticalEvaluations}</strong> 次过程检查</span>
      <span><strong>${summary.advisories}</strong> 条上级建议</span>`;
  }

  function renderPhases() {
    dom.phaseRail.style.setProperty('--chapter-count', state.trial.chapters.length);
    dom.phaseRail.innerHTML = state.trial.chapters.map((chapter, index) => (
      `<button type="button" class="phase-step" data-phase="${index}" data-time="${chapter.start}">
        <span>第 ${index + 1} 幕 · ${formatTime(chapter.start)}</span>
        <strong>${escapeHtml(chapter.title)}</strong>
      </button>`
    )).join('');
    dom.phaseRail.querySelectorAll('[data-phase]').forEach(button => {
      button.addEventListener('click', () => {
        seekTo(Number(button.dataset.time), true);
        document.querySelector(`[data-chapter-index="${button.dataset.phase}"]`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  function criticsForChapter(chapter, index) {
    const isLast = index === state.trial.chapters.length - 1;
    return currentCritics().filter(critic => (
      critic.time >= chapter.start && (critic.time < chapter.end || (isLast && critic.time <= chapter.end))
    ));
  }

  function criticMomentHtml(critic) {
    const alert = critic.verdict === 'imbalance_detected';
    return `<button type="button" class="critic-moment" data-select="critic:${escapeHtml(critic.id)}">
      <span class="critic-moment-meta">
        <strong>${formatPreciseTime(critic.time)}</strong>
        <span>${escapeHtml(critic.triggerLabel)}</span>
        <span class="verdict-badge ${alert ? 'alert' : 'quiet'}">${alert ? '建议介入' : '继续观察'}</span>
        <span>置信度 ${critic.confidence.toFixed(2)}</span>
      </span>
      <span class="critic-moment-summary">${escapeHtml(critic.summaryZh)}</span>
      <span class="critic-moment-advice"><strong>给上级 Agent：</strong>${escapeHtml(critic.adviceZh || '不发送建议，继续观察。')}</span>
      <span class="critic-moment-posthoc">
        <span class="posthoc-badge ${escapeHtml(critic.posthoc.status)}">${escapeHtml(critic.posthoc.label)}</span>
        <span>${escapeHtml(critic.posthoc.summary)}</span>
      </span>
    </button>`;
  }

  function chapterCriticsHtml(chapter, chapterIndex) {
    const critics = criticsForChapter(chapter, chapterIndex);
    if (critics.length === 0) {
      const message = state.policy === 'event'
        ? '本章没有事件触发正式审计；Critic 保持观察。'
        : '本章没有落入预设的固定检查时点。';
      return `<div class="critic-silence">
        <span class="speaker critic">CRITIC</span>
        <strong>${escapeHtml(message)}</strong>
      </div>`;
    }
    const groups = new Map();
    critics.forEach(critic => {
      const episodeKey = critic.episode || critic.id;
      if (!groups.has(episodeKey)) groups.set(episodeKey, []);
      groups.get(episodeKey).push(critic);
    });
    return [...groups.entries()].map(([episode, group]) => {
      const states = new Set(group.map(critic => critic.episodeState).filter(Boolean));
      const stateClass = states.has('repeated') ? 'repeated' : [...states][0] || '';
      const episodeLabel = group[0].episode || '单次审计';
      const threadSummary = group.length > 1
        ? `同一协作问题在本章被检查 ${group.length} 次；这些是证据更新，不是 ${group.length} 个独立问题。`
        : group[0].triggerDetailZh || group[0].triggerLabel;
      return `<aside class="chapter-critic">
        <div class="chapter-critic-heading">
          <span class="speaker critic">CRITIC</span>
          <span class="episode-badge ${escapeHtml(stateClass)}">${escapeHtml(episodeLabel)}</span>
          <strong>${escapeHtml(threadSummary)}</strong>
        </div>
        <div class="critic-moment-list">${group.map(criticMomentHtml).join('')}</div>
      </aside>`;
    }).join('');
  }

  function chapterEventHtml(eventIndex) {
    const event = state.trial.events[eventIndex];
    if (!event) return '';
    return `<button type="button" data-select="event:${state.trial.id}-event-${eventIndex}">
      <span>${formatPreciseTime(event.time)}</span>
      <strong>${escapeHtml(event.title)}</strong>
    </button>`;
  }

  function storyChapterHtml(chapter, index) {
    const evidenceCount = chapter.evidence.length;
    return `<article class="story-chapter" data-chapter-index="${index}" data-chapter-start="${chapter.start}" data-chapter-end="${chapter.end}">
      <header class="chapter-heading">
        <div class="chapter-number">
          <span>第 ${index + 1} 幕</span>
          <strong>${formatTime(chapter.start)}–${formatTime(chapter.end)}</strong>
        </div>
        <div>
          <h2>${escapeHtml(chapter.title)}</h2>
          <p>${escapeHtml(chapter.narrative)}</p>
        </div>
      </header>

      <div class="process-board">
        <section class="actor-panel andy">
          <div class="actor-label"><span class="speaker andy">ANDY</span><span class="certainty-badge">O</span></div>
          <h3>${escapeHtml(chapter.andy.headline)}</h3>
          <p>${escapeHtml(chapter.andy.detail)}</p>
        </section>
        <section class="relation-panel ${escapeHtml(chapter.relation.kind)}">
          <span class="relation-symbol" aria-hidden="true">${escapeHtml(chapter.relation.symbol)}</span>
          <div>
            <span class="certainty-badge">${escapeHtml(chapter.relation.certainty)}</span>
            <h3>${escapeHtml(chapter.relation.label)}</h3>
            <p>${escapeHtml(chapter.relation.detail)}</p>
          </div>
        </section>
        <section class="actor-panel bob">
          <div class="actor-label"><span class="speaker bob">BOB</span><span class="certainty-badge">O</span></div>
          <h3>${escapeHtml(chapter.bob.headline)}</h3>
          <p>${escapeHtml(chapter.bob.detail)}</p>
        </section>
      </div>

      <div class="world-result">
        <div class="world-score">
          <span class="speaker world">世界</span>
          <strong>${escapeHtml(chapter.world.score)}</strong>
        </div>
        <div>
          <span class="certainty-badge">O</span>
          <h3>${escapeHtml(chapter.world.headline)}</h3>
          <p>${escapeHtml(chapter.world.detail)}</p>
        </div>
        <div class="manager-meaning">
          <span>管理含义 · I</span>
          <p>${escapeHtml(chapter.managerMeaning)}</p>
        </div>
      </div>

      ${chapterCriticsHtml(chapter, index)}

      <div class="chapter-evidence-row">
        <div class="chapter-events">
          <span>关键现场</span>
          <div>${chapter.eventIndexes.map(chapterEventHtml).join('')}</div>
        </div>
        <details class="chapter-evidence">
          <summary>${evidenceCount} 项可复核证据</summary>
          <ul>${renderEvidence(chapter.evidence, state.trial)}</ul>
        </details>
      </div>
    </article>`;
  }

  function renderStory() {
    const trial = state.trial;
    const policy = data.policies[state.policy];
    const storyConclusion = state.policy === 'fixed' ? trial.fixedStoryConclusion : trial.storyConclusion;
    dom.storyOverview.innerHTML = `<p class="story-kicker">一轮协作，一条主线</p>
      <h2>${escapeHtml(storyConclusion)}</h2>
      <div class="story-evidence-key">
        <span><strong>O</strong> 可复核事实</span>
        <span><strong>I</strong> 过程解释</span>
        <span><strong>${escapeHtml(policy.shortLabel)}</strong> 当前 Critic 策略</span>
      </div>`;
    dom.storyFeed.innerHTML = trial.chapters.map(storyChapterHtml).join('');
    dom.storyFeed.querySelectorAll('[data-select]').forEach(button => {
      button.addEventListener('click', () => selectItem(button.dataset.select, true));
    });
  }

  function timelinePercent(time) {
    return Math.max(0, Math.min(100, (time / state.trial.duration) * 100));
  }

  function timelineNode(event, index) {
    if (event.compact && dom.keyFilter.checked) return '';
    const left = timelinePercent(event.time);
    const hasDuration = Number.isFinite(event.end) && event.end > event.time;
    const width = hasDuration ? Math.max(1.4, timelinePercent(event.end) - left) : null;
    const style = hasDuration
      ? `left:${left}%;width:${width}%`
      : `left:calc(${left}% - 9px)`;
    return `<button type="button" class="timeline-node ${escapeHtml(event.lane)} ${hasDuration ? 'is-duration' : 'is-point'}" style="${style}" title="${escapeHtml(event.title)}" data-select="event:${state.trial.id}-event-${index}">
      ${hasDuration ? `<strong>${escapeHtml(event.title)}</strong><span>${formatTime(event.time)}–${formatTime(event.end)}</span>` : ''}
    </button>`;
  }

  function criticTimelineNode(critic, index) {
    const alert = critic.verdict === 'imbalance_detected';
    const left = timelinePercent(critic.time);
    const horizontal = left > 94
      ? 'right:4px;width:120px'
      : left < 6
        ? 'left:4px;width:120px'
        : `left:calc(${left}% - 60px);width:120px`;
    const vertical = index % 2 === 0 ? 8 : 47;
    return `<div class="critic-guide" style="left:${left}%"></div>
      <button type="button" class="timeline-node critic critic-node ${alert ? '' : 'quiet'}" style="${horizontal};top:${vertical}px" data-select="critic:${escapeHtml(critic.id)}">
        <strong>${escapeHtml(critic.triggerLabel)}</strong>
        <span>${formatTime(critic.time)} · ${alert ? '介入' : '观察'} · ${critic.confidence.toFixed(2)}</span>
      </button>`;
  }

  function scoreSvg(trial) {
    const points = trial.progress.map(([time, score]) => {
      const x = (time / trial.duration) * 1000;
      const y = 110 - score;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
    const area = `0,110 ${points} 1000,110`;
    return `<svg class="score-chart" viewBox="0 0 1000 120" preserveAspectRatio="none" aria-label="得分进度曲线">
      <line class="score-grid" x1="0" y1="10" x2="1000" y2="10"></line>
      <line class="score-grid" x1="0" y1="60" x2="1000" y2="60"></line>
      <line class="score-grid" x1="0" y1="110" x2="1000" y2="110"></line>
      <polygon class="score-area" points="${area}"></polygon>
      <polyline class="score-line" points="${points}"></polyline>
    </svg>`;
  }

  function renderAudit() {
    const trial = state.trial;
    const ticks = [];
    for (let time = 0; time < trial.duration; time += 60) ticks.push(time);
    if (ticks[ticks.length - 1] !== trial.duration) ticks.push(trial.duration);
    const tickHtml = ticks.map(time => {
      const left = timelinePercent(time);
      return `<div class="tick-line" style="left:${left}%"></div><span class="tick-label" style="left:${left}%">${formatTime(time)}</span>`;
    }).join('');
    const phases = trial.phases.map(phase => (
      `<div class="phase-block" style="left:${timelinePercent(phase.start)}%;width:${timelinePercent(phase.end) - timelinePercent(phase.start)}%" title="${escapeHtml(phase.summary)}">${escapeHtml(phase.title)}</div>`
    )).join('');
    const lanes = ['andy', 'bob', 'world'].map(lane => {
      const nodes = trial.events.map((item, index) => item.lane === lane ? timelineNode(item, index) : '').join('');
      return `<div class="timeline-lane ${lane}">${nodes}</div>`;
    }).join('');
    const criticNodes = currentCritics().map(criticTimelineNode).join('');
    dom.timeline.innerHTML = `${tickHtml}
      <div class="axis-row"></div>
      <div class="phase-row">${phases}</div>
      ${lanes}
      <div class="timeline-lane critic">${criticNodes}</div>
      <div class="score-row">${scoreSvg(trial)}</div>
      <div class="cursor-guide" id="cursor-guide"></div>`;
    dom.timeline.querySelectorAll('[data-select]').forEach(button => {
      button.addEventListener('click', () => selectItem(button.dataset.select, true));
    });
  }

  function findSelection(token) {
    const [kind, id] = token.split(':');
    if (kind === 'critic') {
      const critic = currentCritics().find(item => item.id === id);
      return critic ? { kind, id, payload: critic } : null;
    }
    const prefix = `${state.trial.id}-event-`;
    const index = Number(id.replace(prefix, ''));
    const payload = state.trial.events[index];
    return payload ? { kind: 'event', id, payload } : null;
  }

  function selectItem(token, scroll) {
    const selection = findSelection(token);
    if (!selection) return;
    state.selected = selection;
    seekTo(selection.payload.time, false);
    renderInspector();
    document.querySelectorAll('[data-select]').forEach(element => {
      element.classList.toggle('is-selected', element.dataset.select === token);
    });
    if (scroll) dom.inspector.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function renderInspector() {
    if (!state.selected) {
      dom.inspector.innerHTML = '';
      return;
    }
    const item = state.selected.payload;
    if (state.selected.kind === 'critic') {
      renderCriticInspector(item);
      return;
    }
    const duration = item.end ? `<span>${formatTime(item.time)}–${formatTime(item.end)}</span>` : `<span>${formatPreciseTime(item.time)}</span>`;
    dom.inspector.innerHTML = `<div>
      <div class="inspector-meta">
        <span class="speaker ${escapeHtml(item.lane)}">${escapeHtml(item.lane === 'world' ? '世界' : item.lane)}</span>
        <span class="certainty-badge">${escapeHtml(item.certainty)}</span>
        ${duration}
        <span>${escapeHtml(typeNames[item.type] || item.type)}</span>
      </div>
      <h2>${escapeHtml(item.title)}</h2>
      <p>${escapeHtml(item.text)}</p>
    </div>
    <div>
      <h3>可复核证据</h3>
      <ul>${renderEvidence(item.evidence, state.trial)}</ul>
    </div>`;
  }

  function renderCriticInspector(critic) {
    const alert = critic.verdict === 'imbalance_detected';
    const policy = data.policies[critic.policy];
    const labels = critic.labels.map(label => `<span class="label-chip">${escapeHtml(labelNames[label] || label)}</span>`).join('');
    const observations = critic.observations.map(observation => (
      `<li><strong>${escapeHtml(observation.certainty)}</strong> · ${escapeHtml(observation.claim)}<ul>${renderEvidence(observation.evidence, state.trial)}</ul></li>`
    )).join('');
    const executions = critic.activeExecutions.map(execution => {
      if (execution.status !== 'acting') return `${execution.agent}: 未观察到活动命令`;
      return `${execution.agent}: ${execution.command} 已执行 ${execution.elapsed_s}s`;
    }).join('；');
    const episode = critic.episode
      ? `<span class="episode-badge ${escapeHtml(critic.episodeState || '')}">${escapeHtml(critic.episode)}</span>`
      : '';
    const triggerDetail = critic.triggerDetailZh || policy.description;
    const triggerCandidates = (critic.triggerCandidates || []).map(candidate => {
      const evidence = [
        candidate.evidence,
        candidate.command_evidence,
        candidate.result_evidence,
        candidate.request_evidence,
        candidate.ack_evidence,
        candidate.claimed_attempt_evidence,
        candidate.actual_attempt_evidence,
        candidate.verification_evidence,
      ].filter(Boolean);
      const details = [];
      if (candidate.agent) details.push(`执行者 ${candidate.agent}`);
      if (Number.isFinite(candidate.elapsed_s)) details.push(`持续 ${candidate.elapsed_s.toFixed(1)} 秒`);
      if (candidate.requester || candidate.recipient) details.push(`${candidate.requester || '未知'} → ${candidate.recipient || '未知'}`);
      if (Number.isFinite(candidate.before_score) && Number.isFinite(candidate.after_score)) {
        details.push(`得分 ${candidate.before_score.toFixed(2)}% → ${candidate.after_score.toFixed(2)}%`);
      }
      if (candidate.attribution === 'unknown') details.push('执行者归因未知');
      if (candidate.detail) details.push(candidate.detail);
      return `<li>
        <strong>${escapeHtml(triggerNames[candidate.type] || critic.triggerLabel)}</strong>
        ${details.length ? `<span>${escapeHtml(details.join(' · '))}</span>` : ''}
        ${evidence.length ? `<ul>${renderEvidence(evidence, state.trial)}</ul>` : ''}
      </li>`;
    }).join('');
    const actionWatches = (critic.openWatches?.task_actions || []).map(watch => (
      `<li><strong>${escapeHtml(watch.agent)}</strong> 的行动观察自 ${formatPreciseTime(watch.opened_at_s)} 开放${Number.isFinite(watch.deadline_s) ? `，租约至 ${formatPreciseTime(watch.deadline_s)}` : ''}</li>`
    )).join('');
    const requestWatches = (critic.openWatches?.coordination_requests || []).map(watch => (
      `<li><strong>${escapeHtml(watch.requester)} → ${escapeHtml(watch.recipient)}</strong> · ${escapeHtml(watch.stage || '待验证')}<br>${escapeHtml(watch.request_text || '')}</li>`
    )).join('');
    const openWatches = actionWatches || requestWatches
      ? `<ul>${actionWatches}${requestWatches}</ul>`
      : '<p>当前没有开放的行动或协作请求观察。</p>';
    dom.inspector.innerHTML = `<div>
      <div class="inspector-meta">
        <span class="speaker critic">CRITIC</span>
        <span>${formatPreciseTime(critic.time)}</span>
        <span class="policy-badge">${escapeHtml(policy.label)}</span>
        <span class="trigger-badge">${escapeHtml(critic.triggerLabel)}</span>
        ${episode}
        <span class="verdict-badge ${alert ? 'alert' : 'quiet'}">${alert ? '建议介入' : '暂不介入'}</span>
        <span>置信度 ${critic.confidence.toFixed(2)}</span>
      </div>
      <h2>${escapeHtml(critic.summaryZh)}</h2>
      <div class="label-list">${labels}</div>
      <div class="trigger-explanation">
        <h3>本次为何被叫醒</h3>
        <p>${escapeHtml(triggerDetail)}</p>
      </div>
      <p><strong>执行状态：</strong>${escapeHtml(executions)}</p>
      <p><strong>给上级 Agent：</strong>${escapeHtml(critic.adviceZh || '不发送建议，继续观察。')}</p>
      <div class="posthoc-line">
        <span class="posthoc-badge ${escapeHtml(critic.posthoc.status)}">${escapeHtml(critic.posthoc.label)}</span>
        <span>${escapeHtml(critic.posthoc.summary)}</span>
      </div>
    </div>
    <div>
      <h3>触发信号</h3>
      ${triggerCandidates ? `<ol class="trigger-list">${triggerCandidates}</ol>` : '<p>固定策略按预定时间截点唤醒，没有额外事件信号。</p>'}
      <h3 class="inspector-section">当时仍在观察的事项</h3>
      ${openWatches}
      <h3 class="inspector-section">模型观察原文与证据</h3>
      <ol>${observations}</ol>
      <details class="raw-observation">
        <summary>证据限制</summary>
        <ul>${critic.limitations.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
      </details>
      <p><a href="${escapeHtml(evidenceLink(critic.resultEvidence, state.trial))}">打开完整 critic JSONL</a></p>
    </div>`;
  }

  function seekTo(time, syncVideo) {
    const clamped = Math.max(0, Math.min(state.trial.duration, Number(time) || 0));
    state.cursor = clamped;
    dom.scrubber.value = String(clamped);
    if (syncVideo && Number.isFinite(dom.video.duration)) {
      state.videoSyncing = true;
      dom.video.currentTime = clamped / state.trial.media.playbackRate;
      state.videoSyncing = false;
    }
    updateCursor();
  }

  function updateCursor() {
    const trial = state.trial;
    dom.cursorTime.textContent = formatTime(state.cursor);
    dom.cursorScore.textContent = `进度 ${scoreAt(trial, state.cursor).toFixed(2).replace(/\.00$/, '')}%`;
    const guide = document.querySelector('#cursor-guide');
    if (guide) guide.style.left = `${timelinePercent(state.cursor)}%`;

    dom.phaseRail.querySelectorAll('[data-phase]').forEach((button, index) => {
      const chapter = trial.chapters[index];
      const isLast = index === trial.chapters.length - 1;
      button.classList.toggle('is-current', state.cursor >= chapter.start && (state.cursor < chapter.end || (isLast && state.cursor <= chapter.end)));
    });
    dom.frames.querySelectorAll('[data-frame-index]').forEach((button, index) => {
      const frame = trial.media.frames[index];
      const next = trial.media.frames[index + 1];
      button.classList.toggle('is-current', state.cursor >= frame.time && (!next || state.cursor < next.time));
    });
    dom.storyFeed.querySelectorAll('[data-chapter-index]').forEach((chapter, index) => {
      const dataChapter = trial.chapters[index];
      const isLast = index === trial.chapters.length - 1;
      chapter.classList.toggle('is-current', state.cursor >= dataChapter.start && (state.cursor < dataChapter.end || (isLast && state.cursor <= dataChapter.end)));
    });
  }

  function render() {
    renderTabs();
    renderOverview();
    renderPolicy();
    renderPhases();
    renderStory();
    renderAudit();
    renderInspector();
    setMode(state.mode);
    updateCursor();
  }

  dom.modeButtons.forEach(button => {
    button.addEventListener('click', () => setMode(button.dataset.mode));
  });
  dom.scrubber.addEventListener('input', () => seekTo(Number(dom.scrubber.value), true));
  dom.keyFilter.addEventListener('change', renderAudit);
  dom.video.addEventListener('timeupdate', () => {
    if (state.videoSyncing) return;
    seekTo(dom.video.currentTime * state.trial.media.playbackRate, false);
  });
  dom.video.addEventListener('seeked', () => {
    if (state.videoSyncing) return;
    seekTo(dom.video.currentTime * state.trial.media.playbackRate, false);
  });

  render();
}());
