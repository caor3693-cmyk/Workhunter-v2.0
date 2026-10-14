import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PAGE_READ_PATHS } from '../frontend/pages/routes.js';
import { createPageReader, pageDatasetsAgree, resourceMessage } from '../frontend/pages/shared.js';
import { assessReadIdentity, feedbackTemplate } from '../frontend/pages/review.js';
import { mountHome, resultScopeText } from '../frontend/pages/home.js';
import { mountDetail } from '../frontend/pages/detail.js';
import { mountSources } from '../frontend/pages/sources.js';
import { ReadError } from '../frontend/api/client.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('page read sets keep home independent of source/identity failures', async () => {
  const requests = [];
  const reader = createPageReader(PAGE_READ_PATHS.home, () => {}, async path => {
    requests.push(path);
    assert.ok(!path.includes('/sources/') && path !== '/health' && path !== '/version');
    return { dataset_id: 'test-isolated-dataset' };
  });
  await reader.reload();
  assert.deepEqual(requests.sort(), ['/api/catalog', '/api/opportunities']);
  reader.destroy();
  assert.deepEqual(Object.values(PAGE_READ_PATHS.sources).sort(), ['/api/catalog', '/api/sources/status']);
  assert.deepEqual(Object.values(PAGE_READ_PATHS.review).sort(), ['/health', '/version']);
});

test('one failed page resource preserves the previous response and does not clear independent resources', async () => {
  let fail = false;
  const reader = createPageReader(PAGE_READ_PATHS.sources, () => {}, async path => {
    if (fail && path.includes('/sources/')) throw new Error('来源读取失败');
    return { dataset_id: 'test-isolated-dataset', sources: [], schools: [] };
  });
  await reader.reload();
  fail = true;
  await reader.reload();
  assert.equal(reader.resources.catalog.status, 'ready');
  assert.equal(reader.resources.sources.status, 'error');
  assert.equal(reader.resources.sources.data.dataset_id, 'test-isolated-dataset');
  assert.match(resourceMessage(reader.resources.sources), /来源读取失败.*上次结果，尚未更新/);
  reader.destroy();
});

test('late responses cannot overwrite a newer page retry', async () => {
  const resolves = [];
  const reader = createPageReader({ catalog: '/api/catalog' }, () => {}, () => new Promise(resolve => resolves.push(resolve)));
  const old = reader.load('catalog');
  const recent = reader.load('catalog');
  resolves[1]({ dataset_id: 'newer' });
  await recent;
  resolves[0]({ dataset_id: 'older' });
  await old;
  await tick();
  assert.equal(reader.resources.catalog.data.dataset_id, 'newer');
  reader.destroy();
});

test('a coalesced side resource read keeps its real in-flight request instead of cancelling and restarting it', async () => {
  const calls = [];
  const reader = createPageReader({ catalog: '/api/catalog' }, () => {}, (path, { signal }) => new Promise(resolve => calls.push({ path, signal, resolve })));
  const first = reader.load('catalog');
  const second = reader.load('catalog', undefined, { reusePending: true });
  assert.equal(first, second);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].signal.aborted, false);
  calls[0].resolve({ dataset_id: 'isolated-current' });
  await second;
  assert.equal(reader.resources.catalog.status, 'ready');
  reader.destroy();
});

test('stale displayed responses remain part of identity consistency', () => {
  assert.equal(pageDatasetsAgree({ catalog: { status: 'ready', data: { dataset_id: 'new' } }, sources: { status: 'error', data: { dataset_id: 'old' } } }), false);
});

const sha = 'a'.repeat(40);
const version = { project: 'Workhunter-v2.0', version: 'test-isolated-version', backend_commit: sha, data_mode: 'empty', dataset_id: 'test-isolated-dataset' };
const health = { ...version, status: 'ok', database: 'readable' };

test('connection identity is verified only when both live responses and frontend agree', () => {
  assert.equal(assessReadIdentity(health, version, sha).verified, true);
  for (const change of [ { project: 'other-project' }, { version: 'other-version' }, { backend_commit: 'b'.repeat(40) }, { data_mode: 'real' }, { dataset_id: 'different' } ]) {
    assert.equal(assessReadIdentity({ ...health, ...change }, version, sha).verified, false, JSON.stringify(change));
  }
  assert.equal(assessReadIdentity({ ...health, backend_commit: sha + '+dirty' }, { ...version, backend_commit: sha + '+dirty' }, sha).verified, false);
  assert.match(assessReadIdentity(health, version, 'b'.repeat(40)).message, /前端与后端源码提交/);
  for (const build_id of ['partial', '', sha + '+dirty']) assert.equal(assessReadIdentity({ ...health, build_id }, { ...version, build_id }, sha).verified, false);
});

test('homepage has no engineering/review boxes or disabled placeholder filters', () => {
  const html = readFileSync('frontend/index.html', 'utf8');
  assert.ok(!html.includes('id="build-identity"') && !html.includes('id="source-list"') && !html.includes('qa-list'));
  assert.ok(!html.includes('disabled') && !html.includes('工程骨架') && !html.includes('W00'));
  for (const id of ['search-form', 'school-select', 'campus-select', 'opportunity-status', 'result-list', 'pagination']) assert.ok(html.includes(`id="${id}"`));
  assert.ok(html.includes('href="/sources"') && html.includes('href="/review"'));
  for (const removed of ['update-title', 'update-message', 'new-count', 'change-count']) assert.ok(!html.includes(`id="${removed}"`));
});

test('feedback retains seven M0 and eight M1 stable numbers and current identity placeholders', () => {
  for (const [stage, count] of [['M0', 7], ['M1', 8]]) {
    const text = feedbackTemplate(stage);
    for (let i = 1; i <= count; i++) assert.ok(text.includes(`${stage}-0${i}：`));
    assert.ok(!text.includes(`${stage}-0${count + 1}：`));
    assert.match(text, /尚未取得/);
  }
  const review = readFileSync('frontend/pages/review.html', 'utf8');
  assert.match(review, /M0-02、M0-07 失败/);
  assert.match(review, /M0-03、M0-06 阻塞/);
  assert.equal((review.match(/本轮候选：待复验/g) || []).length, 8);
});

class PageNode {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.value = ''; this.dataset = {}; this.attributes = {}; this.events = {}; this.hidden = false;
    const classes = new Set(); this.classList = { toggle(name, active) { if (active) classes.add(name); else classes.delete(name); }, add(name) { classes.add(name); } };
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(child => child.textContent ?? String(child)).join(''); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  addEventListener(type, handler) { (this.events[type] ||= []).push(handler); }
  fire(type, target = this) { for (const handler of this.events[type] || []) handler({ target, preventDefault() {} }); }
  set innerHTML(_) { throw new Error('Unsafe source HTML'); }
}
function pageDocument() {
  const nodes = new Map();
  const get = id => { if (['update-title', 'update-message', 'new-count', 'change-count'].includes(id)) return null; if (!nodes.has(id)) nodes.set(id, new PageNode()); return nodes.get(id); };
  const controls = Object.fromEntries(['school_key', 'campus_id', 'kind', 'keyword', 'date_from', 'date_to'].map(key => [key, new PageNode(['keyword','date_from','date_to'].includes(key) ? 'input' : 'select')]));
  nodes.set('school-select', controls.school_key); nodes.set('campus-select', controls.campus_id);
  const form = get('search-form'); form.elements = { namedItem: key => controls[key] }; form.querySelectorAll = () => Object.values(controls);
  const tabs = ['recent','upcoming','history','undated'].map(view => { const node = new PageNode('button'); node.dataset.view = view; return node; });
  return { controls, form, tabs, getElementById: get, querySelectorAll: () => tabs, createElement: tag => new PageNode(tag), title: '' };
}

test('sources show a persisted plan and aging without hiding restricted status', async () => withPageDOM(async doc => {
  let schedule = { status: 'scheduled', next_run_at: '2026-10-13T18:00:00+08:00' };
  const read = async path => path === '/api/catalog' ? { dataset_id: 'aging-test', schools: [{school_key: 'scut', name: '华工'}] } :
    { dataset_id: 'aging-test', schedule, sources: [{school_key: 'scut', status: 'restricted', name: '官方来源',
      official_entry_url: 'https://jyzx.scut.edu.cn/', last_success_at: '2026-10-10T12:00:00+08:00', stale: true}] };
  const page = mountSources({ document: doc, read });
  await tick();
  assert.match(doc.getElementById('source-status').textContent, /已登记下次检查/);
  assert.match(doc.getElementById('source-list').textContent, /访问受限/);
  assert.match(doc.getElementById('source-list').textContent, /48 小时.*陈旧/);
  schedule = {status: 'overdue', next_run_at: null};
  await page.reload();
  assert.match(doc.getElementById('source-status').textContent, /逾期.*尚未核实/);
  assert.ok(!doc.getElementById('source-status').textContent.includes('已登记下次检查'));
  page.destroy();
}));
async function withPageDOM(run) {
  const original = globalThis.document;
  const doc = pageDocument(); globalThis.document = doc;
  try { await run(doc); } finally { globalThis.document = original; }
}
const isolatedSchools = ['scut','gdut','ncepu','shiep','neepu','csust','ctgu','gzhu','hnu','csu'].map((school_key, index) => ({ school_key, name: index === 0 ? '隔离华工' : index === 1 ? '隔离广工' : `隔离学校${index}`, campuses: [{ id: index + 1, name: `隔离校区${index}` }] }));
const isolatedList = path => {
  const params = new URL(path, 'https://test.invalid').searchParams;
  return { dataset_id: 'isolated-page', data_mode: 'isolated-test', items: [], total: 0, offset: Number(params.get('offset')), limit: Number(params.get('limit')), has_more: false, as_of: '2026-10-11', empty_reason: 'no_matches', applied_filters: { ...Object.fromEntries([...params].filter(([key]) => !['offset','limit','dataset_id','as_of'].includes(key))), as_of: '2026-10-11', recent_window: { published_from: '2026-09-28', published_to: '2026-10-11', events_from: '2026-10-11', events_to: '2026-10-25' } } };
};

test('mounted home keeps all ten school options, catalog refresh preserves draft and independent failures preserve data', async () => withPageDOM(async doc => {
  let failCatalog = false;
  const requests = [];
  const read = async path => {
    requests.push(path);
    if (path === '/api/catalog') { if (failCatalog) throw new Error('目录失败'); return { dataset_id: 'isolated-page', data_mode: 'isolated-test', schools: isolatedSchools }; }
    assert.ok(path.startsWith('/api/opportunities?'), `Unexpected homepage read: ${path}`);
    return isolatedList(path);
  };
  const page = mountHome({ document: doc, read });
  await tick();
  assert.equal(doc.getElementById('school-select').children.length, 11);
  assert.equal(doc.getElementById('search-form').hidden, false);
  doc.controls.school_key.value = 'scut'; doc.form.fire('change', doc.controls.school_key);
  doc.controls.campus_id.value = '1'; doc.form.fire('change', doc.controls.campus_id);
  doc.controls.keyword.value = '未提交草稿'; doc.form.fire('input', doc.controls.keyword);
  await page.reload();
  assert.equal(page.state.draft.campus_id, '1');
  assert.equal(page.state.draft.keyword, '未提交草稿');
  assert.equal(doc.controls.keyword.value, '未提交草稿');
  assert.equal(doc.controls.school_key.value, 'scut');
  assert.equal(page.resources.updates, undefined);
  assert.ok(requests.every(path => !path.includes('/updates/')));
  failCatalog = true;
  await page.reload();
  assert.equal(page.resources.catalog.data.schools.length, 10);
  assert.equal(doc.controls.school_key.value, 'scut');
  assert.equal(page.state.draft.keyword, '未提交草稿');
  page.destroy();
}));

test('mounted home school draft clears campus, view changes use applied filters, and errors keep old school/date caption', async () => withPageDOM(async doc => {
  const requests = [];
  let fail = false;
  const page = mountHome({ document: doc, read: async path => {
    if (path === '/api/catalog') return { dataset_id: 'isolated-page', data_mode: 'isolated-test', schools: isolatedSchools };
    requests.push(path);
    if (fail) throw new Error('读取超时');
    return isolatedList(path);
  } });
  await tick();
  doc.controls.school_key.value = 'scut'; doc.form.fire('change', doc.controls.school_key);
  doc.controls.campus_id.value = '1'; doc.form.fire('change', doc.controls.campus_id);
  doc.form.fire('submit'); await tick();
  doc.controls.keyword.value = '未提交草稿'; doc.form.fire('input', doc.controls.keyword);
  doc.tabs.find(tab => tab.dataset.view === 'history').fire('click'); await tick();
  const params = new URL(requests.at(-1), 'https://test.invalid').searchParams;
  assert.equal(params.get('school_key'), 'scut'); assert.equal(params.get('campus_id'), '1');
  assert.equal(params.has('keyword'), false);
  doc.controls.school_key.value = 'gdut'; doc.form.fire('change', doc.controls.school_key);
  assert.equal(page.state.draft.campus_id, undefined);
  assert.equal(doc.controls.campus_id.value, '');
  fail = true;
  doc.form.fire('submit'); await tick();
  assert.match(doc.getElementById('result-scope').textContent, /隔离华工.*历史.*2026-10-11/);
  assert.ok(!doc.getElementById('result-scope').textContent.includes('隔离广工'));
  assert.match(doc.getElementById('opportunity-status').textContent, /读取超时.*上次结果/);
  page.destroy();
}));

test('mounted detail reads only its actual API, renders material scope, and retains prior detail on failure', async () => withPageDOM(async doc => {
  let fail = false;
  const requests = [];
  const page = mountDetail({ document: doc, opportunityId: '42', read: async path => {
    requests.push(path); if (fail) throw new Error('详情暂不可读');
    return { id: 42, title: '隔离详情', dataset_id: 'isolated-page', field_observations: {}, roster_fragments: [], job_fragments: [], attachments: [], materials: [], coverage: { school_wide: false, coverage: 'partial' } };
  } });
  await tick();
  assert.deepEqual(requests, ['/api/opportunities/42']);
  assert.equal(doc.getElementById('page-title').textContent, '隔离详情');
  assert.equal(doc.getElementById('detail-content').hidden, false);
  assert.match(doc.getElementById('detail-content').textContent, /非全校覆盖/);
  fail = true; await page.reload();
  assert.match(doc.getElementById('detail-status').textContent, /详情暂不可读.*上次结果/);
  assert.equal(doc.getElementById('page-title').textContent, '隔离详情');
  page.destroy();
}));

test('displayed recent window is explicit and undated view never borrows an ingestion date', () => {
  const recent = resultScopeText({ view: 'recent', scope: 'electrical', as_of: '2026-10-11', recent_window: { published_from: '2026-09-28', published_to: '2026-10-11', events_from: '2026-10-11', events_to: '2026-10-25' } });
  assert.match(recent, /公告 2026-09-28 至 2026-10-11，活动 2026-10-11 至 2026-10-25/);
  assert.match(resultScopeText({ view: 'undated' }), /日期未知/);
  assert.ok(!resultScopeText({ view: 'undated' }).includes('收录时间'));
});

test('a ready list restores its button and card while catalog remains slow independently', async () => withPageDOM(async doc => {
  const calls = [];
  const page = mountHome({ document: doc, read: (path, { signal }) => new Promise((resolve, reject) => calls.push({ path, signal, resolve, reject })) });
  const list = calls.find(call => call.path.startsWith('/api/opportunities?'));
  list.resolve({ ...isolatedList(list.path), items: [{ id: 42, title: '隔离卡片' }], total: 1 });
  await tick();
  assert.equal(page.state.status, 'ready');
  assert.equal(doc.getElementById('reload-button').disabled, false);
  assert.equal(doc.getElementById('reload-button').textContent, '重新加载');
  assert.match(doc.getElementById('result-list').textContent, /隔离卡片/);
  assert.ok(!doc.getElementById('result-count').textContent.includes('上次结果'));
  assert.equal(doc.controls.school_key.disabled, true);
  const card = doc.getElementById('result-list').children[0];
  calls.find(call => call.path === '/api/catalog').resolve({ dataset_id: 'isolated-page', data_mode: 'isolated-test', schools: isolatedSchools });
  await tick();
  assert.equal(doc.controls.school_key.disabled, false);
  assert.equal(doc.getElementById('result-list').children[0], card);
  assert.equal(doc.getElementById('reload-button').disabled, false);
  assert.equal(calls.length, 2, 'home reads only catalog and opportunities');
  assert.ok(!doc.getElementById('result-count').textContent.includes('上次结果'));
  page.destroy();
}));

test('new list B and old side resources A coordinate once without stale-list labels, storms or cancelling useful side requests', async () => withPageDOM(async doc => {
  let dataset = 'isolated-A', slow = false;
  const pending = [], listCalls = [];
  const side = () => ({ dataset_id: 'isolated-A', data_mode: 'isolated-test', schools: isolatedSchools });
  const page = mountHome({ document: doc, read: (path, { signal }) => {
    if (path.startsWith('/api/opportunities?')) { listCalls.push(path); return Promise.resolve({ ...isolatedList(path), dataset_id: dataset, items: [{ id: 42, title: '隔离当前列表' }], total: 1 }); }
    if (slow) return new Promise(resolve => pending.push({ path, signal, resolve }));
    return Promise.resolve(side(path));
  } });
  await tick();
  dataset = 'isolated-B'; slow = true;
  await page.query({ school_key: 'gdut' });
  await tick();
  assert.equal(page.state.dataset, 'isolated-B');
  assert.equal(pending.length, 1);
  assert.equal(doc.getElementById('reload-button').disabled, false);
  assert.ok(!doc.getElementById('result-count').textContent.includes('上次结果'));
  assert.ok(!doc.getElementById('opportunity-status').textContent.includes('尚未一致'));
  const firstReload = page.reload();
  const secondReload = page.reload();
  doc.controls.school_key.value = 'scut'; doc.form.fire('change', doc.controls.school_key);
  doc.form.fire('submit');
  await tick();
  assert.equal(pending.length, 1);
  assert.ok(pending.every(call => !call.signal.aborted));
  for (const call of pending) call.resolve(side(call.path));
  await Promise.all([firstReload, secondReload]);
  await tick();
  assert.equal(pending.length, 1, 'a mismatched coordination response must not poll repeatedly');
  assert.match(doc.getElementById('catalog-status').textContent, /尚未同步当前招聘/);
  assert.ok(!doc.getElementById('result-count').textContent.includes('上次结果'));
  const count = listCalls.length;
  doc.controls.keyword.value = '未提交草稿'; doc.form.fire('input', doc.controls.keyword);
  assert.equal(listCalls.length, count);
  doc.form.fire('submit'); await tick();
  assert.equal(listCalls.length, count + 1);
  assert.equal(pending.length, 1);
  page.destroy();
}));

test('dataset coordination never hides a real project/build/mode mismatch', async () => withPageDOM(async doc => {
  const base = { project: 'Workhunter-v2.0', backend_commit: 'a'.repeat(40), build_id: 'a'.repeat(40), version: 'isolated-version', data_mode: 'isolated-test' };
  let patch = {};
  const page = mountHome({ document: doc, read: async path => {
    if (path === '/api/catalog') return { ...base, dataset_id: 'isolated-A', schools: isolatedSchools };
    return { ...isolatedList(path), ...base, ...patch, dataset_id: 'isolated-B', items: [{ id: 42 }], total: 1 };
  } });
  await tick();
  for (const key of ['project', 'backend_commit', 'build_id', 'version', 'data_mode']) {
    patch = { [key]: 'different-identity' };
    await page.query();
    assert.match(doc.getElementById('opportunity-status').textContent, /数据连接身份不一致/, key);
    assert.equal(doc.getElementById('opportunity-status').hidden, false);
  }
  page.destroy();
}));

test('home stores bounded nonvisual request measurements, distinguishes failure and excludes old cards from fresh samples', async () => withPageDOM(async doc => {
  let fail = false;
  const page = mountHome({ document: doc, read: async (path, { onTiming }) => {
    onTiming?.({ phase: 'request', path, at: Date.now() });
    onTiming?.({ phase: 'headers', at: Date.now(), elapsed_ms: 0, status: fail ? 403 : 200, server_timing: 'api;dur=1', api_started_at: null, api_ended_at: null });
    onTiming?.({ phase: 'json', at: Date.now(), elapsed_ms: 0, status: fail ? 403 : 200 });
    if (path === '/api/catalog') return { dataset_id: 'isolated-page', data_mode: 'isolated-test', schools: isolatedSchools };
    if (fail) throw new ReadError('隔离无访问权限', 403, 'http_error');
    return { ...isolatedList(path), items: [{ id: 42 }], total: 1 };
  } });
  await tick();
  for (let index = 0; index < 64; index++) await page.reload();
  const readSamples = () => JSON.parse(doc.getElementById('result-list').attributes['data-m1-timing-samples']);
  let samples = readSamples();
  assert.equal(samples.length, 60);
  const sample = samples.at(-1);
  assert.equal(sample.action, 'reload');
  assert.equal(sample.outcome, 'ready');
  assert.equal(sample.requests[0].server_timing, 'api;dur=1');
  assert.equal(sample.requests[0].api_started_at, null);
  assert.equal(sample.requests[0].api_ended_at, null);
  assert.ok(sample.operation_at <= sample.requests[0].request_at && sample.requests[0].request_at <= sample.requests[0].headers_at && sample.requests[0].headers_at <= sample.requests[0].json_at);
  assert.ok(sample.requests[0].json_at <= sample.first_card_at && sample.first_card_at <= sample.button_ready_at);
  assert.ok(!doc.getElementById('result-list').textContent.includes('server_timing'));
  fail = true; await page.reload();
  samples = readSamples();
  assert.equal(samples.length, 60);
  assert.equal(samples.at(-1).outcome, 'error');
  assert.equal(samples.at(-1).requests[0].status, 403);
  assert.equal(samples.at(-1).first_card_at, null);
  assert.match(doc.getElementById('result-count').textContent, /上次结果/);
  page.destroy();
}));
