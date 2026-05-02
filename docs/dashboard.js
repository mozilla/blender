// BLEnder Mission Control Dashboard
// No authentication required — GitHub public API (60 req/hr)
// Budget: cache history in localStorage, use ETags for conditional polls

const REPO = 'mozilla/blender';
const API = `https://api.github.com/repos/${REPO}/actions/runs`;
const POLL_INTERVAL = 60_000; // 60s
const CACHE_KEY = 'blender-dashboard-cache';
const CACHE_MAX_AGE = 30 * 60_000; // 30 min — re-fetch full history after this
const IDLE_DESK = 2; // center desk — idle robot sits here

// Merge counter: count actual merged PRs, not workflow runs.
// BLEnder leaves a review containing "BLEnder auto-merge" on every PR it merges.
// GitHub Search API (10 req/min, separate from REST budget).
const MERGE_SEARCH_API = 'https://api.github.com/search/issues';
const MERGE_SEARCH_QUERY = 'is:pr is:merged "BLEnder auto-merge" in:comments';

// Workflow file → type mapping
// "mergecheck" = automerge workflow runs (distinct from "merge" = actual merged PRs)
const WORKFLOW_MAP = {
  'scheduled-sweep.yml': 'sweep',
  'chore-automerge-dependabot-prs.yml': 'mergecheck',
  'chore-review-major-dependabot-update.yml': 'review',
  'fix-dependabot-pr.yml': 'fix',
};

// Counter targets for beam animation (% positions in scene)
const COUNTER_TARGETS = {
  sweep:      { left: 19.5, top: 36 },
  review:     { left: 43, top: 43 },
  mergecheck: { left: 66.5, top: 37 },
  merge:      { left: 66.5, top: 51 },
  fix:        { left: 82.5, top: 43 },
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
const counters = { sweep: 0, mergecheck: 0, merge: 0, review: 0, fix: 0, fail: 0 };
let totalRuns = 0;
const desks = [null, null, null, null, null];
const runQueue = [];
let pollEtag = null;
let mergeTarget = 0; // Search API count we're animating toward (prevents duplicate celebrations)

// DOM refs
const beamLayer = document.getElementById('beam-layer');
const statusText = document.getElementById('status-text');
const statusTime = document.getElementById('status-time');

// ── DOM helpers ──

function getCounterEl(type) {
  return document.querySelector(`.counter-value[data-type="${type}"]`);
}

function getDeskSlot(index) {
  return document.querySelector(`.desk-slot[data-desk="${index}"]`);
}

function createSpinner() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('class', 'run-spinner');
  svg.innerHTML =
    '<path stroke="#dbab0a" stroke-width="2" ' +
    'd="M3.05 3.05a7 7 0 1 1 9.9 9.9 7 7 0 0 1-9.9-9.9Z" opacity=".5"/>' +
    '<path fill="#dbab0a" fill-rule="evenodd" ' +
    'd="M8 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" clip-rule="evenodd"/>' +
    '<path fill="#dbab0a" d="M14 8a6 6 0 0 0-6-6V0a8 8 0 0 1 8 8h-2Z"/>';
  return svg;
}

// ── Helpers ──

function workflowType(run) {
  const path = run.path ? run.path.split('/').pop() : '';
  return WORKFLOW_MAP[path] || null;
}

function runLabel(run) {
  return run.display_title || run.name || '';
}

function updateCounter(type, value) {
  const el = getCounterEl(type);
  if (!el) return;
  el.classList.remove('loading');
  el.textContent = value;
  el.classList.add('pulse');
  setTimeout(() => el.classList.remove('pulse'), 200);
}

function renderCounters() {
  for (const [type, val] of Object.entries(counters)) {
    const el = getCounterEl(type);
    if (el) {
      el.textContent = val;
      el.classList.remove('loading');
    }
  }
}

function renderFailRate() {
  const el = getCounterEl('failrate');
  if (!el) return;
  el.classList.remove('loading');
  if (totalRuns === 0) { el.textContent = '\u2014'; return; }
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
  return desks.indexOf(null);
}

function restoreIdleRobot() {
  const slot = getDeskSlot(IDLE_DESK);
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
  const slot = getDeskSlot(idx);
  if (slot) slot.innerHTML = '';
  desks[idx] = null;
  if (idx === IDLE_DESK) restoreIdleRobot();
  processQueue();
}

function populateDesk(idx, run, type, beamTarget) {
  const slot = getDeskSlot(idx);
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

  link.appendChild(createSpinner());

  const label = runLabel(run);
  const textSpan = document.createElement('span');
  textSpan.className = 'link-text';
  textSpan.textContent = label;
  link.appendChild(textSpan);
  link.title = label;
  slot.appendChild(link);

  desks[idx] = { run, type, beamTarget };
}

function processQueue() {
  while (runQueue.length > 0) {
    const idx = claimDesk();
    if (idx === -1) break;
    const { run, type, duration, beamTarget } = runQueue.shift();
    startWork(idx, run, type, duration, beamTarget);
  }
}

// ── Work lifecycle ──

function startWork(deskIdx, run, type, duration, beamTarget) {
  populateDesk(deskIdx, run, type, beamTarget);

  const timerId = setTimeout(() => {
    completeWork(deskIdx, run, type);
  }, duration);

  if (desks[deskIdx]) desks[deskIdx].timerId = timerId;
}

function completeWork(deskIdx, run, type) {
  if (!desks[deskIdx] || desks[deskIdx].run.id !== run.id) return;

  if (desks[deskIdx].timerId) {
    clearTimeout(desks[deskIdx].timerId);
  }

  const slot = getDeskSlot(deskIdx);
  const robot = slot?.querySelector('.robot');
  if (robot) {
    robot.classList.remove('active');
    robot.classList.add('fading');
  }

  const isFailed = run.conclusion === 'failure';
  const target = desks[deskIdx].beamTarget || type;
  if (isFailed) {
    // Track for fail rate — no beam (FAILED counter removed)
    counters.fail++;
    totalRuns++;
    renderFailRate();
  } else {
    fireBeam(deskIdx, type, target);
  }

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

  // Double rAF technique: the first requestAnimationFrame callback runs before
  // the next paint, but the browser may not have committed the element's start
  // position yet. The second rAF fires after the browser has painted the start
  // position. Setting the target position here triggers the CSS transition from
  // the painted start to the new end — without this, the element snaps to the
  // end position with no visible animation.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      beam.style.left = `${targetPos.left}%`;
      beam.style.top = `${targetPos.top}%`;
    });
  });

  beam.addEventListener('transitionend', () => {
    counters[counterType]++;
    // Merge celebrations come from the Search API, not workflow runs —
    // don't count them toward totalRuns (avoids inflating the fail rate)
    if (counterType !== 'merge') totalRuns++;
    updateCounter(counterType, counters[counterType]);
    renderFailRate();
    beam.style.opacity = '0';
    setTimeout(() => beam.remove(), 300);
  }, { once: true });
}

// ── Assign run to desk or queue ──

function assignRun(run, type, duration, beamTarget) {
  const idx = claimDesk();
  if (idx === -1) {
    runQueue.push({ run, type, duration, beamTarget });
  } else {
    startWork(idx, run, type, duration, beamTarget);
  }
}

// ── Merge celebrations ──
// When the Search API reports new merges, queue robots that fire beams to the
// MERGES counter. Each robot uses the mergecheck sprite but targets "merge".

function celebrateMerges(delta) {
  const cap = Math.min(delta, 5);
  for (let i = 0; i < cap; i++) {
    setTimeout(() => {
      const run = {
        id: `merge-celebrate-${Date.now()}-${i}`,
        html_url: `https://github.com/search?q=${encodeURIComponent(MERGE_SEARCH_QUERY)}&type=pullrequests`,
        display_title: 'Auto-merged PR',
        conclusion: 'success',
      };
      assignRun(run, 'mergecheck', 3000, 'merge');
    }, i * 1500);
  }
  // If delta exceeds the visual cap, set the remainder directly
  if (delta > cap) {
    counters.merge += (delta - cap);
    updateCounter('merge', counters.merge);
  }
}

// ── Data fetching ──

// Shared fetch helper: checks response status, surfaces rate-limit info on
// errors, and returns null for 304 Not Modified (ETag cache hit).
async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 304) return null;
  if (!res.ok) {
    const remaining = res.headers.get('x-ratelimit-remaining');
    throw new Error(`API ${res.status} (remaining: ${remaining})`);
  }
  return res;
}

async function fetchRuns(perPage = 100, page = 1) {
  const res = await apiFetch(`${API}?per_page=${perPage}&page=${page}`);
  const data = await res.json();
  return data.workflow_runs || [];
}

async function fetchAllHistory() {
  const pages = await Promise.all(
    [1, 2, 3, 4, 5].map(p => fetchRuns(100, p).catch(() => []))
  );
  return pages.flat();
}

// ── Conditional poll (ETag) ──
// 304 Not Modified does NOT count against the rate limit.

async function fetchRunsConditional(perPage = 30) {
  const headers = {};
  if (pollEtag) headers['If-None-Match'] = pollEtag;

  const res = await apiFetch(`${API}?per_page=${perPage}`, { headers });
  if (!res) return null; // 304

  const etag = res.headers.get('etag');
  if (etag) pollEtag = etag;

  const data = await res.json();
  return data.workflow_runs || [];
}

// ── Merge count (Search API) ──

async function fetchMergeCount() {
  try {
    const res = await apiFetch(
      `${MERGE_SEARCH_API}?q=${encodeURIComponent(MERGE_SEARCH_QUERY)}`
    );
    if (!res) return null;
    const data = await res.json();
    return data.total_count ?? null;
  } catch {
    return null; // Search API failures shouldn't crash the dashboard
  }
}

// ── Initial load ──

function processHistory(allRuns) {
  const completedByType = { sweep: [], mergecheck: [], review: [], fix: [] };

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
    let allRuns = loadCache();
    let fromCache = !!allRuns;

    if (!allRuns) {
      allRuns = await fetchAllHistory();
      saveCache(allRuns);
    }

    const completedByType = processHistory(allRuns);

    // Build replay list — 1 of each type first for variety, then extras
    const replayRuns = [];
    const usedIds = new Set();
    const types = Object.keys(completedByType);

    // Guarantee at least 1 of each workflow type in the opening scene
    for (const type of types) {
      const run = completedByType[type].find(r =>
        r.conclusion === 'success' || r.conclusion === 'failure'
      );
      if (run) {
        replayRuns.push({ run, type });
        usedIds.add(run.id);
      }
    }

    // Fill remaining replay slots (up to 2 extra per type)
    for (const [type, runs] of Object.entries(completedByType)) {
      const extras = runs.filter(r =>
        !usedIds.has(r.id) &&
        (r.conclusion === 'success' || r.conclusion === 'failure')
      ).slice(0, 2);
      for (const run of extras) {
        replayRuns.push({ run, type });
        usedIds.add(run.id);
      }
    }

    // Subtract replayed runs from counters (beams will re-add them)
    for (const { run, type } of replayRuns) {
      totalRuns--;
      if (run.conclusion === 'failure') {
        counters.fail--;
      } else {
        counters[type]--;
      }
    }

    // Fetch actual merge count from Search API (set directly on initial load)
    const mergeCount = await fetchMergeCount();
    if (mergeCount !== null) {
      counters.merge = mergeCount;
      mergeTarget = mergeCount;
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
  // Stagger: 1.5s apart, quarter real duration
  replayRuns.forEach((item, i) => {
    const { run, type } = item;
    const created = new Date(run.created_at);
    const updated = new Date(run.updated_at);
    const realDuration = updated - created;
    const replayDuration = realDuration / 4;

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
          renderFailRate();
        } else if (run.conclusion === 'success') {
          counters[type]++;
          totalRuns++;
          updateCounter(type, counters[type]);
          renderFailRate();
        }
      }
    }

    // Refresh actual merge count — animate new merges with desk robots
    const mergeCount = await fetchMergeCount();
    if (mergeCount !== null && mergeCount > mergeTarget) {
      celebrateMerges(mergeCount - mergeTarget);
      mergeTarget = mergeCount;
    } else if (mergeCount !== null && mergeCount < mergeTarget) {
      // Rare: count decreased (reverted PR) — correct directly
      counters.merge = mergeCount;
      mergeTarget = mergeCount;
      updateCounter('merge', counters.merge);
    }

    setStatus('Live', false);
  } catch (err) {
    setStatus(`Poll error: ${err.message}`, true);
  }
}

// ── Mission clock ──

const launchTime = Date.now();
const missionClock = document.getElementById('mission-clock');

function updateClocks() {
  const elapsed = Math.floor((Date.now() - launchTime) / 1000);
  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  missionClock.textContent = `T+ ${h}:${m}:${s}`;

  if (!statusText.classList.contains('error')) {
    statusTime.textContent = new Date().toLocaleTimeString();
  }
}

// ── Init ──

// Mark all counter values as loading (spinning ↻)
document.querySelectorAll('.counter-value').forEach(el => el.classList.add('loading'));

setInterval(updateClocks, 1000);
initPlayer();
initialLoad();
setInterval(poll, POLL_INTERVAL);
