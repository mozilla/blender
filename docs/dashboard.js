// BLEnder Mission Control Dashboard
// No authentication required — GitHub public API (60 req/hr)
// Budget: cache history in localStorage, use ETags for conditional polls

const REPO = 'mozilla/blender';
const API = `https://api.github.com/repos/${REPO}/actions/runs`;
const POLL_INTERVAL = 60_000; // 60s
const CACHE_KEY = 'blender-dashboard-cache';
const CACHE_MAX_AGE = 30 * 60_000; // 30 min — re-fetch full history after this
const IDLE_DESK = 2; // center desk — idle robot sits here

// Workflow file → type mapping
const WORKFLOW_MAP = {
  'scheduled-sweep.yml': 'sweep',
  'chore-automerge-dependabot-prs.yml': 'merge',
  'chore-review-major-dependabot-update.yml': 'review',
  'fix-dependabot-pr.yml': 'fix',
};

// Counter targets for beam animation (% positions in scene)
const COUNTER_TARGETS = {
  sweep:  { left: 19.5, top: 36 },
  merge:  { left: 43, top: 43 },
  review: { left: 66.5, top: 37 },
  fix:    { left: 82.5, top: 43 },
  fail:   { left: 66.5, top: 51 },
};

// Desk positions (% of scene)
const DESK_POSITIONS = [
  { left: 11.5, top: 67 },
  { left: 27.5, top: 67 },
  { left: 49.5, top: 67 },
  { left: 67.5, top: 67 },
  { left: 85.5, top: 67 },
];

// State
const seenRunIds = new Set();
const counters = { sweep: 0, merge: 0, review: 0, fix: 0, fail: 0 };
let totalRuns = 0;
const desks = [null, null, null, null, null]; // null = free, object = occupied
const runQueue = [];
let pollEtag = null; // ETag from last poll response

// DOM refs
const scene = document.getElementById('scene');
const beamLayer = document.getElementById('beam-layer');
const statusText = document.getElementById('status-text');
const statusTime = document.getElementById('status-time');

// ── Helpers ──

function workflowType(run) {
  const path = run.path ? run.path.split('/').pop() : '';
  return WORKFLOW_MAP[path] || null;
}

function runLabel(run) {
  return run.display_title || run.name || '';
}

function updateCounter(type, value) {
  const el = document.querySelector(`.counter-value[data-type="${type}"]`);
  if (!el) return;
  el.textContent = value;
  el.classList.add('pulse');
  setTimeout(() => el.classList.remove('pulse'), 200);
}

function renderCounters() {
  for (const [type, val] of Object.entries(counters)) {
    const el = document.querySelector(`.counter-value[data-type="${type}"]`);
    if (el) el.textContent = val;
  }
}

function renderFailRate() {
  const el = document.querySelector('.counter-value[data-type="failrate"]');
  if (!el) return;
  if (totalRuns === 0) { el.textContent = '—'; return; }
  el.textContent = `${Math.round((counters.fail / totalRuns) * 100)}%`;
}

function setStatus(msg, isError) {
  statusText.textContent = msg;
  statusText.className = isError ? 'error' : '';
  statusTime.textContent = new Date().toLocaleTimeString();
}

// ── LocalStorage cache ──

function saveCache(runs) {
  try {
    const data = { ts: Date.now(), runs };
    localStorage.setItem(CACHE_KEY, JSON.stringify(data));
  } catch { /* full storage — ignore */ }
}

function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (Date.now() - data.ts > CACHE_MAX_AGE) return null;
    return data.runs;
  } catch {
    return null;
  }
}

// ── Desk management ──

function claimDesk() {
  const idx = desks.indexOf(null);
  return idx;
}

function restoreIdleRobot() {
  const slot = document.querySelector(`.desk-slot[data-desk="${IDLE_DESK}"]`);
  if (!slot) return;
  if (desks[IDLE_DESK] !== null) return;
  const robot = document.createElement('img');
  robot.id = 'idle-robot';
  robot.className = 'robot active';
  robot.src = 'assets/robot.png';
  robot.alt = 'BLEnder';
  slot.appendChild(robot);
}

function freeDesk(idx) {
  const slot = document.querySelector(`.desk-slot[data-desk="${idx}"]`);
  if (slot) slot.innerHTML = '';
  desks[idx] = null;
  if (idx === IDLE_DESK) restoreIdleRobot();
  processQueue();
}

function populateDesk(idx, run, type) {
  const slot = document.querySelector(`.desk-slot[data-desk="${idx}"]`);
  if (!slot) return;

  slot.innerHTML = '';

  // Robot
  const robot = document.createElement('img');
  robot.src = 'assets/robot.png';
  robot.className = 'robot';
  slot.appendChild(robot);
  requestAnimationFrame(() => robot.classList.add('active'));

  // Activity icon
  const icon = document.createElement('div');
  icon.className = `activity-icon ${type}`;
  slot.appendChild(icon);

  // Run label link with spinner
  const link = document.createElement('a');
  link.className = 'repo-link';
  link.href = run.html_url;
  link.target = '_blank';
  link.rel = 'noopener';

  const spinner = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  spinner.setAttribute('viewBox', '0 0 16 16');
  spinner.setAttribute('width', '16');
  spinner.setAttribute('height', '16');
  spinner.setAttribute('fill', 'none');
  spinner.setAttribute('class', 'run-spinner');
  spinner.innerHTML =
    '<path stroke="#dbab0a" stroke-width="2" d="M3.05 3.05a7 7 0 1 1 9.9 9.9 7 7 0 0 1-9.9-9.9Z" opacity=".5"/>' +
    '<path fill="#dbab0a" fill-rule="evenodd" d="M8 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" clip-rule="evenodd"/>' +
    '<path fill="#dbab0a" d="M14 8a6 6 0 0 0-6-6V0a8 8 0 0 1 8 8h-2Z"/>';
  link.appendChild(spinner);

  link.append(runLabel(run));
  slot.appendChild(link);

  desks[idx] = { run, type };
}

function processQueue() {
  while (runQueue.length > 0) {
    const idx = claimDesk();
    if (idx === -1) break;
    const { run, type, duration } = runQueue.shift();
    startWork(idx, run, type, duration);
  }
}

// ── Work lifecycle ──

function startWork(deskIdx, run, type, duration) {
  populateDesk(deskIdx, run, type);

  const timerId = setTimeout(() => {
    completeWork(deskIdx, run, type);
  }, duration);

  // Store timer so poll can cancel it
  if (desks[deskIdx]) desks[deskIdx].timerId = timerId;
}

function completeWork(deskIdx, run, type) {
  // Guard: only complete if this run still owns the desk
  if (!desks[deskIdx] || desks[deskIdx].run.id !== run.id) return;

  // Cancel the timeout if triggered by poll
  if (desks[deskIdx].timerId) {
    clearTimeout(desks[deskIdx].timerId);
  }

  const slot = document.querySelector(`.desk-slot[data-desk="${deskIdx}"]`);
  const robot = slot?.querySelector('.robot');
  if (robot) {
    robot.classList.remove('active');
    robot.classList.add('fading');
  }

  // Determine counter target
  const isFailed = run.conclusion === 'failure';
  const counterType = isFailed ? 'fail' : type;

  fireBeam(deskIdx, type, counterType);

  setTimeout(() => freeDesk(deskIdx), 600);
}

function fireBeam(deskIdx, iconType, counterType) {
  const deskPos = DESK_POSITIONS[deskIdx];
  const targetPos = COUNTER_TARGETS[counterType];

  const beam = document.createElement('div');
  beam.className = `beam ${iconType}`;
  beam.style.left = `${deskPos.left}%`;
  beam.style.top = `${deskPos.top}%`;
  beamLayer.appendChild(beam);

  // Double rAF: forces browser to register start position before animating to target
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      beam.style.left = `${targetPos.left}%`;
      beam.style.top = `${targetPos.top}%`;
    });
  });

  beam.addEventListener('transitionend', () => {
    counters[counterType]++;
    totalRuns++;
    updateCounter(counterType, counters[counterType]);
    renderFailRate();
    beam.style.opacity = '0';
    setTimeout(() => beam.remove(), 300);
  }, { once: true });
}

// ── Assign run to desk or queue ──

function assignRun(run, type, duration) {
  const idx = claimDesk();
  if (idx === -1) {
    runQueue.push({ run, type, duration });
  } else {
    startWork(idx, run, type, duration);
  }
}

// ── Data fetching ──

async function fetchRuns(perPage = 100, page = 1) {
  const url = `${API}?per_page=${perPage}&page=${page}`;
  const res = await fetch(url);
  if (!res.ok) {
    const limit = res.headers.get('x-ratelimit-remaining');
    throw new Error(`API ${res.status} (remaining: ${limit})`);
  }
  const data = await res.json();
  return data.workflow_runs || [];
}

async function fetchAllHistory() {
  // Fetch all 5 pages in parallel
  const pages = await Promise.all(
    [1, 2, 3, 4, 5].map(p => fetchRuns(100, p).catch(() => []))
  );
  return pages.flat();
}

// ── Conditional poll (ETag) ──
// 304 Not Modified does NOT count against the rate limit.

async function fetchRunsConditional(perPage = 30) {
  const url = `${API}?per_page=${perPage}`;
  const headers = {};
  if (pollEtag) {
    headers['If-None-Match'] = pollEtag;
  }
  const res = await fetch(url, { headers });

  if (res.status === 304) {
    return null; // no change — free request
  }

  const etag = res.headers.get('etag');
  if (etag) pollEtag = etag;

  if (!res.ok) {
    const limit = res.headers.get('x-ratelimit-remaining');
    throw new Error(`API ${res.status} (remaining: ${limit})`);
  }
  const data = await res.json();
  return data.workflow_runs || [];
}

// ── Initial load ──

function processHistory(allRuns) {
  const completedByType = { sweep: [], merge: [], review: [], fix: [] };

  for (const run of allRuns) {
    seenRunIds.add(run.id);
    const type = workflowType(run);
    if (!type) continue;

    if (run.status === 'completed') {
      if (run.conclusion === 'success') {
        counters[type]++;
        totalRuns++;
      } else if (run.conclusion === 'failure') {
        counters.fail++;
        totalRuns++;
      }
      completedByType[type].push(run);
    }
  }

  return completedByType;
}

async function initialLoad() {
  setStatus('Loading history...', false);

  try {
    // Try cache first — zero API calls
    let allRuns = loadCache();
    let fromCache = !!allRuns;

    if (!allRuns) {
      allRuns = await fetchAllHistory();
      saveCache(allRuns);
    }

    const completedByType = processHistory(allRuns);

    // Find last 4 completed runs per type for replay (excludes cancelled)
    const replayRuns = [];
    for (const [type, runs] of Object.entries(completedByType)) {
      const recent = runs.filter(r =>
        r.conclusion === 'success' || r.conclusion === 'failure'
      ).slice(0, 4);
      for (const run of recent) {
        replayRuns.push({ run, type });
        // Subtract from counters (will be re-added via beam)
        totalRuns--;
        if (run.conclusion === 'failure') {
          counters.fail--;
        } else {
          counters[type]--;
        }
      }
    }

    renderCounters();
    renderFailRate();
    scheduleReplay(replayRuns);

    setStatus(fromCache ? 'Live (cached)' : 'Live', false);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

// ── Replay system ──

function scheduleReplay(replayRuns) {
  // Stagger: 1.5s apart
  replayRuns.forEach((item, i) => {
    const { run, type } = item;
    const created = new Date(run.created_at);
    const updated = new Date(run.updated_at);
    const realDuration = updated - created;
    // Half real duration
    const replayDuration = realDuration / 2;

    setTimeout(() => {
      assignRun(run, type, replayDuration);
    }, 800 + i * 1500);
  });
}

// ── Poll loop ──

async function poll() {
  try {
    const runs = await fetchRunsConditional(30);

    if (runs === null) {
      // 304 — nothing changed, free request
      setStatus('Live', false);
      return;
    }

    for (const run of runs) {
      const type = workflowType(run);
      if (!type) continue;

      if (run.status === 'in_progress' || run.status === 'queued') {
        if (!seenRunIds.has(run.id)) {
          seenRunIds.add(run.id);
          assignRun(run, type, 300_000); // 5 min max, will be cut short
        }
      } else if (run.status === 'completed' && seenRunIds.has(run.id)) {
        // Was active, now complete — find its desk and complete it
        for (let d = 0; d < desks.length; d++) {
          if (desks[d] && desks[d].run.id === run.id) {
            completeWork(d, run, type);
            break;
          }
        }
      } else if (run.status === 'completed' && !seenRunIds.has(run.id)) {
        // Never seen, already completed — count directly
        seenRunIds.add(run.id);
        if (run.conclusion === 'failure') {
          counters.fail++;
          totalRuns++;
          updateCounter('fail', counters.fail);
        } else if (run.conclusion === 'success') {
          counters[type]++;
          totalRuns++;
          updateCounter(type, counters[type]);
        }
        renderFailRate();
      }
    }

    setStatus('Live', false);
  } catch (err) {
    setStatus(`Poll error: ${err.message}`, true);
  }
}

// ── Debug overlay ──

function showDebug() {
  // Desk slots
  DESK_POSITIONS.forEach((pos, i) => {
    const box = document.createElement('div');
    box.className = 'debug-box';
    box.dataset.label = `desk-${i}`;
    box.style.left = `${pos.left - 3}%`;
    box.style.top = `${pos.top - 9}%`;
    box.style.width = '7%';
    box.style.height = '18%';
    scene.appendChild(box);
  });

  // Counter targets
  for (const [type, pos] of Object.entries(COUNTER_TARGETS)) {
    const box = document.createElement('div');
    box.className = 'debug-box';
    box.dataset.label = type;
    box.style.left = `${pos.left - 2}%`;
    box.style.top = `${pos.top - 4}%`;
    box.style.width = '5%';
    box.style.height = '8%';
    box.style.borderColor = 'cyan';
    box.style.background = 'rgba(0,255,255,0.1)';
    scene.appendChild(box);
  }

  // Counter panels
  document.querySelectorAll('.counter-panel').forEach(panel => {
    panel.style.border = '1px solid yellow';
    panel.style.background = 'rgba(255,255,0,0.1)';
  });
}

// ── Mission clock ──

const launchTime = Date.now();
const missionClock = document.getElementById('mission-clock');

function updateMissionClock() {
  const elapsed = Math.floor((Date.now() - launchTime) / 1000);
  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  missionClock.textContent = `T+ ${h}:${m}:${s}`;
}

// ── Init ──

if (new URLSearchParams(window.location.search).has('debug')) {
  showDebug();
}

setInterval(updateMissionClock, 1000);
initialLoad();
setInterval(poll, POLL_INTERVAL);
