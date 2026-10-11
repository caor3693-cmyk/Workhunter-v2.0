// Read-only audit reproductions against the frozen GitHub file snapshot.
// All data and timings below are isolated fixtures; never production evidence.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mountHome } from '../../../../frontend/pages/home.js';
import { detailContent } from '../../../../frontend/components/cards.js';
import { readJSON } from '../../../../frontend/api/client.js';

class PageNode {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.value = ''; this.dataset = {}; this.attributes = {}; this.events = {}; this.hidden = false; this.disabled = false;
    const classes = new Set();
    this.classList = { toggle(name, active) { if (active) classes.add(name); else classes.delete(name); }, add(name) { classes.add(name); } };
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(child => child.textContent ?? String(child)).join(''); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  addEventListener(type, handler) { (this.events[type] ||= []).push(handler); }
  fire(type, target = this) { for (const handler of this.events[type] || []) handler({ target, preventDefault() {} }); }
  set innerHTML(_) { throw new Error('Source HTML must remain literal text'); }
}

function pageDocument() {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new PageNode()); return nodes.get(id); };
  const controls = Object.fromEntries(['school_key', 'campus_id', 'kind', 'keyword', 'date_from', 'date_to'].map(key => [key, new PageNode(['keyword', 'date_from', 'date_to'].includes(key) ? 'input' : 'select')]));
  nodes.set('school-select', controls.school_key); nodes.set('campus-select', controls.campus_id);
  const form = get('search-form'); form.elements = { namedItem: key => controls[key] }; form.querySelectorAll = () => Object.values(controls);
  const tabs = ['recent', 'upcoming', 'history', 'undated'].map(view => { const node = new PageNode('button'); node.dataset.view = view; return node; });
  return { controls, form, tabs, getElementById: get, querySelectorAll: () => tabs, createElement: tag => new PageNode(tag), title: '' };
}

const tick = () => new Promise(resolve => setImmediate(resolve));
const schools = ['scut', 'gdut'].map((school_key, index) => ({ school_key, name: `隔离学校${index + 1}`, campuses: [{ id: index + 1, name: `隔离校区${index + 1}` }] }));
const identity = dataset_id => ({ dataset_id, data_mode: 'isolated_fixture' });
const list = (path, dataset_id = 'isolated-A') => {
  const params = new URL(path, 'https://audit.invalid').searchParams;
  return { ...identity(dataset_id), items: [{ id: 42, title: `隔离结果 ${dataset_id}` }], total: 1, offset: Number(params.get('offset')), limit: Number(params.get('limit')), has_more: false, as_of: '2026-10-11', applied_filters: { ...Object.fromEntries([...params].filter(([key]) => !['offset', 'limit', 'dataset_id', 'as_of'].includes(key))), as_of: '2026-10-11', recent_window: { published_from: '2026-09-12', published_to: '2026-10-11', events_from: '2026-10-11', events_to: '2026-11-09' } } };
};
const payload = (path, dataset_id = 'isolated-A') => path === '/api/catalog'
  ? { ...identity(dataset_id), schools }
  : path === '/api/updates/summary'
    ? { ...identity(dataset_id), check_status: 'checked', today: { newly_collected: 1, official_changes: 0 }, message: '隔离摘要' }
    : list(path, dataset_id);
const renderCard = item => { const node = new PageNode('article'); node.textContent = item.title; return node; };
const snapshot = (doc, page) => ({ query_status: page.state.status, resource_statuses: Object.fromEntries(Object.entries(page.resources).map(([key, value]) => [key, value.status])), displayed_dataset: page.state.dataset, visible_cards: doc.getElementById('result-list').children.length, count_text: doc.getElementById('result-count').textContent, result_scope: doc.getElementById('result-scope').textContent, notice_hidden: doc.getElementById('opportunity-status').hidden, notice: doc.getElementById('opportunity-status').textContent, reload_disabled: doc.getElementById('reload-button').disabled, reload_text: doc.getElementById('reload-button').textContent });

const report = {
  classification: 'isolated_reproduction_not_live_latency_measurement',
  snapshot_commit: '02ae529ce4637be643b7751bddea7f07a5750509',
  runtime_application_commit: 'b6300f4991d4c9a36ecf8f425a6de578c0106275',
  cases: [],
};

async function withDOM(run) {
  const original = globalThis.document;
  const doc = pageDocument(); globalThis.document = doc;
  try { await run(doc); } finally { globalThis.document = original; }
}

await withDOM(async doc => {
  const calls = [];
  const page = mountHome({ document: doc, read: (path, { signal }) => new Promise((resolve, reject) => calls.push({ path, signal, resolve, reject })), renderCard });
  assert.equal(calls.length, 3);
  const events = [{ logical_ms: 0, ...snapshot(doc, page) }];
  const result = calls.find(call => call.path.startsWith('/api/opportunities'));
  result.resolve(payload(result.path)); await tick();
  events.push({ logical_ms: 100, ...snapshot(doc, page) });
  assert.equal(page.state.status, 'ready');
  assert.equal(doc.getElementById('result-list').children.length, 1);
  assert.equal(doc.getElementById('reload-button').disabled, true);
  calls.find(call => call.path === '/api/catalog').resolve(payload('/api/catalog')); await tick();
  events.push({ logical_ms: 200, ...snapshot(doc, page) });
  assert.equal(doc.getElementById('reload-button').disabled, true);
  calls.find(call => call.path === '/api/updates/summary').reject(new Error('隔离摘要模拟超时')); await tick();
  events.push({ logical_ms: 12000, ...snapshot(doc, page) });
  assert.equal(doc.getElementById('reload-button').disabled, false);
  assert.equal(page.state.status, 'ready');
  report.cases.push({ id: 'F30-A', result: 'confirmed', fact: '招聘先完成即可渲染；重新加载按钮仍等最慢旁路资源', timing_note: 'logical_ms 是显式控制的事件时间标签，不是实际毫秒或 p95', events });
  page.destroy();
});

await withDOM(async doc => {
  const calls = []; let dataset = 'isolated-A';
  const page = mountHome({ document: doc, read: async path => { calls.push(path); return payload(path, dataset); }, renderCard });
  await tick();
  assert.equal(doc.getElementById('opportunity-status').hidden, true);
  dataset = 'isolated-B';
  doc.controls.school_key.value = 'gdut'; doc.form.fire('change', doc.controls.school_key);
  doc.controls.campus_id.value = '2'; doc.form.fire('change', doc.controls.campus_id);
  const before = calls.length;
  doc.form.fire('submit'); await tick();
  const afterSubmit = snapshot(doc, page);
  assert.equal(calls.length - before, 1);
  assert.equal(page.state.status, 'ready');
  assert.equal(page.state.dataset, 'isolated-B');
  assert.equal(page.resources.catalog.data.dataset_id, 'isolated-A');
  assert.equal(page.resources.updates.data.dataset_id, 'isolated-A');
  assert.match(afterSubmit.count_text, /上次结果，尚未更新/);
  assert.match(afterSubmit.notice, /身份尚未一致/);
  assert.equal(afterSubmit.reload_disabled, false);
  doc.form.fire('submit'); await tick();
  assert.match(doc.getElementById('result-count').textContent, /上次结果，尚未更新/);
  const stillStale = snapshot(doc, page);
  const beforeReload = calls.length;
  await page.reload();
  assert.equal(calls.length - beforeReload, 3);
  assert.equal(doc.getElementById('opportunity-status').hidden, true);
  report.cases.push({ id: 'F30-B', result: 'confirmed', fact: '提交新筛选拿到新数据集时，旁路资源停留旧数据集；最新成功列表被标旧且不会自行协调', query_only_request_count: 1, all_resource_reload_count: 3, after_submit: afterSubmit, repeated_submit: stillStale, after_full_reload: snapshot(doc, page) });
  page.destroy();
});

await withDOM(async doc => {
  const calls = [];
  const page = mountHome({ document: doc, read: async path => { calls.push(path); return payload(path); }, renderCard }); await tick();
  doc.controls.school_key.value = 'scut'; doc.form.fire('change', doc.controls.school_key);
  doc.controls.campus_id.value = '1'; doc.form.fire('change', doc.controls.campus_id);
  assert.equal(calls.length, 3);
  const before = calls.length; doc.form.fire('submit'); await tick();
  assert.equal(calls.length - before, 1);
  assert.match(calls.at(-1), /school_key=scut/); assert.match(calls.at(-1), /campus_id=1/);
  doc.controls.campus_id.value = '__unknown__'; doc.form.fire('change', doc.controls.campus_id);
  const beforeReload = calls.length; await page.reload();
  const params = new URL(calls.at(-1), 'https://audit.invalid').searchParams;
  assert.equal(calls.length - beforeReload, 3);
  assert.equal(params.get('campus_id'), '1');
  assert.equal(params.has('campus_unknown'), false);
  report.cases.push({ id: 'F30-control', result: 'existing_contract_preserved', fact: '选择学校/校区只改草稿，不触发网络；搜索仅提交一条列表请求；重新加载使用已提交条件并读三路', automatic_request_count_from_selection: 0, submitted_list_request_count: 1, reload_request_count: 3, reload_applied_campus: params.get('campus_id'), unsent_campus_unknown: page.state.draft.campus_unknown });
  page.destroy();
});

await withDOM(async () => {
  const proof = { material_id: 7, source_url: 'https://career.gdut.edu.cn/teachin/view/id/191549', locator: ".infoList:has(a[href*='/teachin/view/id/191549'])", excerpt: '隔离测试活动日期 2026-10-20', scope: 'partial', observed_at: '2026-10-11T16:57:00+08:00', parser_version: 'isolated-parser' };
  const item = { id: 68, title: '隔离详情样例，非官方采集结果', detail_url: '/opportunities/68', school_name: '隔离学校', kind: 'campus_talk', date_basis: 'event', source_url: proof.source_url, field_observations: { event_date: { state: 'known', value: '2026-10-20', evidence: [proof] } }, materials: [{ id: 7, source_url: proof.source_url, material_hash: 'a'.repeat(64), fetched_at: '2026-10-11T16:57:00+08:00', scope: { type: 'source_list', coverage: 'complete_for_page' } }], roster_fragments: [], job_fragments: [], attachments: [], coverage: { coverage: 'selected_public_channel', page_budget: 2 } };
  const before = JSON.stringify(item);
  const content = detailContent(item).textContent;
  assert.match(content, /查看定位证据/);
  assert.ok(content.includes(proof.locator));
  assert.match(content, /材料 7/);
  assert.match(content, /SHA-256：a{64}/);
  assert.match(content, /selected_public_channel/);
  assert.match(content, /complete_for_page/);
  assert.match(content, /source_list/);
  assert.equal(JSON.stringify(item), before);
  report.cases.push({ id: 'F29', result: 'confirmed', fact: '访客详情 DOM 含技术定位器、材料ID和SHA-256，现有测试还要求hash出现', locator_present: content.includes(proof.locator), material_id_present: /材料 7/.test(content), hash_present: /SHA-256：a{64}/.test(content), raw_scope_codes_present: ['selected_public_channel', 'complete_for_page', 'source_list'].filter(code => content.includes(code)), input_evidence_mutated: false });
});

const workerSource = readFileSync(new URL('../../../../ops/preview/worker.mjs', import.meta.url), 'utf8').replace('__EMBEDDED_ASSETS__', '{}');
const worker = (await import('data:text/javascript;base64,' + Buffer.from(workerSource).toString('base64'))).default;
const env = { WH_API_ORIGIN: 'https://isolated-only.trycloudflare.com', WH_API_SERVICE_TOKEN: 'isolated-audit-token' };
const originalFetch = globalThis.fetch, originalWarn = console.warn;
try {
  console.warn = () => {};
  let observed, finish;
  globalThis.fetch = async (_url, options) => { observed = options.signal; return new Promise(resolve => { finish = resolve; }); };
  const downstream = new AbortController();
  const request = new Request('https://audit.invalid/api/opportunities?school_key=gdut', { signal: downstream.signal });
  const pending = worker.fetch(request, env);
  assert.ok(observed);
  downstream.abort(); await tick();
  assert.equal(request.signal.aborted, true);
  assert.equal(observed.aborted, false);
  finish(Response.json({ ...identity('isolated-A'), items: [] }));
  const response = await pending;
  report.cases.push({ id: 'F30-C', result: 'application_code_gap_confirmed_platform_impact_unmeasured', fact: '下游 Request.signal 的取消未传入代理上游；真实平台是否自动取消及其延迟影响未测', downstream_aborted: request.signal.aborted, upstream_aborted_after_downstream: observed.aborted, fixture_proxy_response_status: response.status });

  const rows = [];
  for (const code of ['invalid_keyword', 'as_of_required', 'invalid_as_of', 'invalid_dataset']) {
    globalThis.fetch = async () => Response.json({ detail: { code, message: 'isolated upstream diagnostic' } }, { status: 422 });
    const response = await worker.fetch(new Request('https://audit.invalid/api/opportunities?keyword=x'), env);
    const body = await response.clone().json();
    globalThis.fetch = async () => response.clone();
    let caught; try { await readJSON('/api/opportunities?keyword=x'); } catch (error) { caught = error; }
    assert.equal(body.error.code, 'upstream_http_error');
    assert.equal(caught.code, 'upstream_http_error');
    rows.push({ backend_code: code, proxy_code: body.error.code, visitor_message: caught.message });
  }
  report.cases.push({ id: 'F30-D', result: 'confirmed_related_error_guidance_gap', fact: '代理白名单漏掉后端422错误码，访客失去改正条件的具体指引', rows });
} finally {
  globalThis.fetch = originalFetch; console.warn = originalWarn;
}

console.log(JSON.stringify(report, null, 2));
