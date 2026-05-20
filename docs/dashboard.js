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

// Sec alerts counter: count actual PRs created by security investigations.
// npm-bump.sh includes "BLEnder investigation" in the PR body.
const SECALERT_SEARCH_QUERY = 'is:pr "BLEnder investigation" in:body org:mozilla';

// Fixes counter: count actual PRs where BLEnder picked up a failing PR.
const FIX_SEARCH_QUERY = 'is:pr "BLEnder picked up this PR" in:comments org:mozilla';

// Needs Review counter: open PRs the bot has touched that need human attention.
const NEEDSREVIEW_SEARCH_QUERY = 'is:pr is:open involves:mozilla-blender[bot] org:mozilla';

// Workflow file → type mapping
const WORKFLOW_MAP = {
  'chore-review-major-dependabot-update.yml': 'review',
};

// Counter targets for beam animation (% positions in scene)
const COUNTER_TARGETS = {
  secalert:    { left: 19.5, top: 36 },
  needsreview: { left: 43, top: 43 },
  review:      { left: 66.5, top: 51 },
  merge:       { left: 66.5, top: 37 },
  fix:         { left: 82.5, top: 43 },
};

// Desk positions (% of scene)
const DESK_POSITIONS = [
  { left: 11.5, top: 67 },
  { left: 27.5, top: 67 },
  { left: 49.5, top: 67 },
  { left: 67.5, top: 67 },
  { left: 85.5, top: 67 },
];

// SVG icons (GitHub octicons, fill="currentColor" for CSS color inheritance)
const ICONS = {
  secalert: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M7.467.133a1.748 1.748 0 0 1 1.066 0l5.25 1.68A1.75 1.75 0 0 1 15 3.48V7c0 1.566-.32 3.182-1.303 4.682-.983 1.498-2.585 2.813-5.032 3.855a1.697 1.697 0 0 1-1.33 0c-2.447-1.042-4.049-2.357-5.032-3.855C1.32 10.182 1 8.566 1 7V3.48a1.75 1.75 0 0 1 1.217-1.667Zm.61 1.429a.25.25 0 0 0-.153 0l-5.25 1.68a.25.25 0 0 0-.174.238V7c0 1.358.275 2.666 1.057 3.86.784 1.194 2.121 2.34 4.366 3.297a.196.196 0 0 0 .154 0c2.245-.956 3.582-2.104 4.366-3.298C13.225 9.666 13.5 8.36 13.5 7V3.48a.251.251 0 0 0-.174-.237l-5.25-1.68ZM8.75 4.75v3a.75.75 0 0 1-1.5 0v-3a.75.75 0 0 1 1.5 0ZM9 10.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"/></svg>',
  needsreview: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 2c1.981 0 3.671.992 4.933 2.078 1.27 1.091 2.187 2.345 2.637 3.023a1.62 1.62 0 0 1 0 1.798c-.45.678-1.367 1.932-2.637 3.023C11.67 13.008 9.981 14 8 14c-1.981 0-3.671-.992-4.933-2.078C1.797 10.83.88 9.576.43 8.898a1.62 1.62 0 0 1 0-1.798c.45-.677 1.367-1.931 2.637-3.022C4.33 2.992 6.019 2 8 2ZM1.679 7.932a.12.12 0 0 0 0 .136c.411.622 1.241 1.75 2.366 2.717C5.176 11.758 6.527 12.5 8 12.5c1.473 0 2.825-.742 3.955-1.715 1.124-.967 1.954-2.096 2.366-2.717a.12.12 0 0 0 0-.136c-.412-.621-1.242-1.75-2.366-2.717C10.824 4.242 9.473 3.5 8 3.5c-1.473 0-2.825.742-3.955 1.715-1.124.967-1.954 2.096-2.366 2.717ZM8 10a2 2 0 1 1-.001-3.999A2 2 0 0 1 8 10Z"/></svg>',
  review: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M1.75 1h8.5c.966 0 1.75.784 1.75 1.75v5.5A1.75 1.75 0 0 1 10.25 10H7.061l-2.574 2.573A1.458 1.458 0 0 1 2 11.543V10h-.25A1.75 1.75 0 0 1 0 8.25v-5.5C0 1.784.784 1 1.75 1ZM1.5 2.75v5.5c0 .138.112.25.25.25h1a.75.75 0 0 1 .75.75v2.19l2.72-2.72a.749.749 0 0 1 .53-.22h3.5a.25.25 0 0 0 .25-.25v-5.5a.25.25 0 0 0-.25-.25h-8.5a.25.25 0 0 0-.25.25Zm13 2a.25.25 0 0 0-.25-.25h-.5a.75.75 0 0 1 0-1.5h.5c.966 0 1.75.784 1.75 1.75v5.5A1.75 1.75 0 0 1 14.25 12H14v1.543a1.458 1.458 0 0 1-2.487 1.03L9.22 12.28a.749.749 0 0 1 .326-1.275.749.749 0 0 1 .734.215l2.22 2.22v-2.19a.75.75 0 0 1 .75-.75h1a.25.25 0 0 0 .25-.25Z"/></svg>',
  fix: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8.75 1.75V5H12a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-.75.75H8.75v3.25H12a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-.75.75H8.75v2a.75.75 0 0 1-1.5 0v-2H4a.75.75 0 0 1-.75-.75v-.5A.75.75 0 0 1 4 10.25h3.25V7H4a.75.75 0 0 1-.75-.75v-.5A.75.75 0 0 1 4 5h3.25V1.75a.75.75 0 0 1 1.5 0Z"/></svg>',
  merge: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8-8a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM4.25 4a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z"/></svg>',
  fail: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M2.343 13.657A8 8 0 1 1 13.658 2.343 8 8 0 0 1 2.343 13.657ZM6.03 4.97a.751.751 0 0 0-1.042.018.751.751 0 0 0-.018 1.042L6.94 8 4.97 9.97a.749.749 0 0 0 .326 1.275.749.749 0 0 0 .734-.215L8 9.06l1.97 1.97a.749.749 0 0 0 1.275-.326.749.749 0 0 0-.215-.734L9.06 8l1.97-1.97a.749.749 0 0 0-.326-1.275.749.749 0 0 0-.734.215L8 6.94Z"/></svg>',
};

function createIconEl(type, className) {
  const el = document.createElement('div');
  el.className = `${className} ${type}`;
  el.innerHTML = ICONS[type] || '';
  return el;
}

// State
const seenRunIds = new Set();
const counters = { secalert: 0, needsreview: 0, merge: 0, review: 0, fix: 0, fail: 0 };
let totalRuns = 0;
const desks = [null, null, null, null, null];
const runQueue = [];
let pollEtag = null;
let mergeTarget = 0; // Search API count we're animating toward (prevents duplicate celebrations)
let secalertTarget = 0; // Search API count for sec alert PRs
let fixTarget = 0; // Search API count for fix PRs
let needsreviewTarget = 0; // Search API count for open PRs needing human review

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
  robot.src = 'assets/dino-bot.png';
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
  robot.src = 'assets/dino-bot.png';
  robot.className = 'robot';
  slot.appendChild(robot);
  requestAnimationFrame(() => robot.classList.add('active'));

  // Activity icon
  const icon = createIconEl(type, 'activity-icon');
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
    // Swap activity icon to fail X, then track for fail rate
    const oldIcon = slot?.querySelector('.activity-icon');
    if (oldIcon) {
      const failIcon = createIconEl('fail', 'activity-icon');
      oldIcon.replaceWith(failIcon);
    }
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

  const beam = createIconEl(iconType, 'beam');
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
    // Search-API-driven counters (merge, secalert) aren't workflow runs —
    // don't count them toward totalRuns (avoids inflating the fail rate)
    if (counterType !== 'merge' && counterType !== 'secalert' && counterType !== 'fix' && counterType !== 'needsreview') totalRuns++;
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
// MERGES counter. Each robot uses the merge icon and targets "merge".

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
      assignRun(run, 'merge', 3000, 'merge');
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

// ── Search API counts (merges + sec alerts) ──

async function fetchSearchCount(query) {
  try {
    const res = await apiFetch(
      `${MERGE_SEARCH_API}?q=${encodeURIComponent(query)}`
    );
    if (!res) return null;
    const data = await res.json();
    return data.total_count ?? null;
  } catch {
    return null;
  }
}

// ── Initial load ──

function processHistory(allRuns) {
  const completedByType = { review: [] };

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

    // Fetch actual counts from Search API (set directly on initial load)
    const [mergeCount, secalertCount, fixCount, needsreviewCount] = await Promise.all([
      fetchSearchCount(MERGE_SEARCH_QUERY),
      fetchSearchCount(SECALERT_SEARCH_QUERY),
      fetchSearchCount(FIX_SEARCH_QUERY),
      fetchSearchCount(NEEDSREVIEW_SEARCH_QUERY),
    ]);
    if (mergeCount !== null) {
      counters.merge = mergeCount;
      mergeTarget = mergeCount;
    }
    if (needsreviewCount !== null) {
      counters.needsreview = needsreviewCount;
      needsreviewTarget = needsreviewCount;
    }
    if (secalertCount !== null) {
      counters.secalert = secalertCount;
      secalertTarget = secalertCount;

      // Inject a synthetic replay so a sec-alert robot appears on load
      if (secalertCount > 0) {
        counters.secalert--;
        replayRuns.unshift({
          run: {
            id: `secalert-replay-${Date.now()}`,
            html_url: `https://github.com/search?q=${encodeURIComponent(SECALERT_SEARCH_QUERY)}&type=pullrequests&s=created&o=desc`,
            display_title: 'Security investigation',
            conclusion: 'success',
            created_at: new Date(Date.now() - 20_000).toISOString(),
            updated_at: new Date().toISOString(),
          },
          type: 'secalert',
        });
      }
    }
    if (fixCount !== null) {
      counters.fix = fixCount;
      fixTarget = fixCount;

      // Inject a synthetic replay so a fix robot appears on load
      if (fixCount > 0) {
        counters.fix--;
        replayRuns.push({
          run: {
            id: `fix-replay-${Date.now()}`,
            html_url: `https://github.com/search?q=${encodeURIComponent(FIX_SEARCH_QUERY)}&type=pullrequests&s=created&o=desc`,
            display_title: 'CI fix',
            conclusion: 'success',
            created_at: new Date(Date.now() - 25_000).toISOString(),
            updated_at: new Date().toISOString(),
          },
          type: 'fix',
        });
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

    // Refresh actual counts from Search API
    const [mergeCount, secalertCount, fixCount, needsreviewCount] = await Promise.all([
      fetchSearchCount(MERGE_SEARCH_QUERY),
      fetchSearchCount(SECALERT_SEARCH_QUERY),
      fetchSearchCount(FIX_SEARCH_QUERY),
      fetchSearchCount(NEEDSREVIEW_SEARCH_QUERY),
    ]);
    if (mergeCount !== null && mergeCount > mergeTarget) {
      celebrateMerges(mergeCount - mergeTarget);
      mergeTarget = mergeCount;
    } else if (mergeCount !== null && mergeCount < mergeTarget) {
      // Rare: count decreased (reverted PR) — correct directly
      counters.merge = mergeCount;
      mergeTarget = mergeCount;
      updateCounter('merge', counters.merge);
    }
    if (needsreviewCount !== null && needsreviewCount !== needsreviewTarget) {
      counters.needsreview = needsreviewCount;
      needsreviewTarget = needsreviewCount;
      updateCounter('needsreview', counters.needsreview);
    }
    if (secalertCount !== null && secalertCount !== secalertTarget) {
      counters.secalert = secalertCount;
      secalertTarget = secalertCount;
      updateCounter('secalert', counters.secalert);
    }
    if (fixCount !== null && fixCount !== fixTarget) {
      counters.fix = fixCount;
      fixTarget = fixCount;
      updateCounter('fix', counters.fix);
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
