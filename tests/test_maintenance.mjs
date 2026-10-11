import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createMaintenanceAPI, MaintenanceError, previewBinding } from '../frontend/api/maintenance.js';
import { createMaintenanceController, mountMaintenance, isRehearsalURL } from '../frontend/pages/maintenance.js';

const csrf = 'c'.repeat(43), password = 'synthetic-test-password';
const operationId = 'maintenance-' + '1'.repeat(32);
const session = authenticated => ({ authenticated, csrf_token: csrf, expires_at: '2035-01-01T00:00:00Z', ...(authenticated ? { actor: 'synthetic-maintainer' } : {}) });
const preview = (environment = 'isolated', extra = {}) => ({ environment, operation_id: operationId, preview_hash: 'a'.repeat(64), input_hash: 'b'.repeat(64), base_version: 0, expires_at: '2035-01-01T00:00:00Z', operation_type: 'manual_supplement', target: { opportunity_id: 1, school_key: 'gdut', source_key: 'gdut_teachin', source_identity: '1212' }, candidate: { title: '合成隔离公告', source_url: 'https://career.gdut.edu.cn/teachin/view/id/1212' }, differences: { event_date: { before: null, after: '2026-10-20', after_observation: { evidence: [{ excerpt: '合成隔离材料依据' }] } } }, warnings: [], retained_fields: [], visible: true, ...extra });
const receipt = (environment = 'isolated', extra = {}) => ({ environment, operation_id: operationId, new: 1, modified: 0, unchanged: 0, opportunity_ids: [1], dataset_id: 'isolated-synthetic-dataset', version: 1, visible: true, committed_at: '2026-10-12T01:00:00Z', ...extra });
const list = (environment, items = [], extra = {}) => ({ environment, items, has_more: false, next_cursor: null, ...extra });
const catalog = { schools: [{ school_key: 'gdut', name: '隔离广工', sources: [{ source_key: 'gdut_teachin', name: '隔离宣讲会', channel_key: 'teachin' }] }, { school_key: 'scut', name: '隔离华工', sources: [] }] };
const history = (id, environment) => ({ id: Number(id), environment, title: '合成隔离公告', version: 1, visible: true, history: [] });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }

function syntheticAPI(overrides = {}) {
  const calls = [];
  const methods = { session: () => session(false), login: () => session(true), logout: () => ({ authenticated: false }), operations: env => list(env), tasks: env => list(env), history,
    preview: payload => preview(payload.environment), retryPreview: (id, env) => preview(env, { operation_type: 'manual_correction' }), revertPreview: (id, env) => preview(env, { operation_type: 'manual_withdrawal', candidate: null, differences: { __visibility__: { before: true, after: false } }, visible: false }),
    commit: value => receipt(value.environment), ...overrides };
  const api = Object.fromEntries(Object.entries(methods).map(([name, method]) => [name, async (...args) => { calls.push({ name, args }); return method(...args); }]));
  return { api, calls };
}
async function signedController(overrides = {}, options = {}) {
  const fixture = syntheticAPI(overrides);
  const controller = createMaintenanceController({ api: fixture.api, read: async () => catalog, ...options });
  await controller.start(); await controller.login(password);
  controller.setDraft({ school_key: 'gdut', source_key: 'gdut_teachin', url: 'https://career.gdut.edu.cn/teachin/view/id/1212', reason: '合成隔离材料核验', public_text: '标题：合成隔离公告' });
  return { controller, ...fixture };
}

test('maintenance requests use only fixed same-origin routes, browser cookies and CSRF', async () => {
  const calls = [];
  const api = createMaintenanceAPI({ fetch: async (path, options) => {
    calls.push({ path, options });
    return new Response(JSON.stringify(path.endsWith('/logout') ? { authenticated: false } : path.endsWith('/commit') ? receipt() : path.endsWith('/preview') ? preview() : path.includes('/operations?') ? list('isolated') : session(path.endsWith('/login'))), { status: 200 });
  } });
  await api.session(); await api.login(password, csrf); await api.preview({ environment: 'isolated', url: 'https://career.gdut.edu.cn/teachin/view/id/1212' }, csrf);
  await api.commit({ ...preview(), actor: 'must-not-be-sent', sql: 'must-not-be-sent' }, csrf); await api.operations('isolated'); await api.logout(csrf);
  assert.deepEqual(calls.map(item => item.options.method), ['GET', 'POST', 'POST', 'POST', 'GET', 'POST']);
  for (const call of calls) {
    assert.ok(call.path.startsWith('/api/admin/') && !call.path.startsWith('//'));
    assert.equal(call.options.credentials, 'same-origin'); assert.equal(call.options.cache, 'no-store'); assert.equal(call.options.redirect, 'error');
    assert.ok(!('Authorization' in call.options.headers) && !('Cookie' in call.options.headers) && !('Origin' in call.options.headers));
    if (call.options.method === 'POST') assert.equal(call.options.headers['X-WH-CSRF'], csrf);
  }
  assert.deepEqual(JSON.parse(calls[1].options.body), { password });
  assert.deepEqual(JSON.parse(calls[3].options.body), previewBinding(preview()));
  assert.ok(!calls.some(item => item.path.includes(password) || item.path.includes(csrf)));
});

test('dynamic identifiers and environments cannot become a different endpoint', async () => {
  let calls = 0; const api = createMaintenanceAPI({ fetch: () => { calls += 1; throw new Error(); } });
  for (const id of ['../session/logout', '//other.test', 'bad/id', '%2e%2e', 'x?url=https://other.test']) assert.throws(() => api.revertPreview(id, 'isolated', 'reason', csrf));
  assert.throws(() => api.history('0', 'isolated'));
  assert.throws(() => api.operations('C:/arbitrary.sqlite3'));
  await assert.rejects(api.login(password, ''), /重新读取/);
  assert.equal(calls, 0);
});

test('revert and task retry follow exact preview then commit routes and bindings', async () => {
  const calls = []; const api = createMaintenanceAPI({ fetch: async (path, options) => {
    calls.push({ path, body: JSON.parse(options.body) });
    return new Response(JSON.stringify(path.endsWith('/revert') ? receipt() : preview()), { status: 200 });
  } });
  const data = await api.revertPreview(operationId, 'isolated', '合成撤回原因', csrf);
  await api.commit(data, csrf, operationId); await api.retryPreview(12, 'isolated', '合成重试原因', csrf);
  assert.equal(calls[0].path, `/api/admin/operations/${operationId}/revert-preview`);
  assert.deepEqual(calls[0].body, { environment: 'isolated', reason: '合成撤回原因' });
  assert.equal(calls[1].path, `/api/admin/operations/${operationId}/revert`);
  assert.deepEqual(calls[1].body, previewBinding(data));
  assert.equal(calls[2].path, '/api/admin/tasks/12/retry-preview');
});

test('incorrect response environment or missing preview bindings is rejected', async () => {
  const api = createMaintenanceAPI({ fetch: async () => new Response(JSON.stringify(preview('real')), { status: 200 }) });
  await assert.rejects(api.preview({ environment: 'isolated' }, csrf), /接口不一致/);
  assert.throws(() => previewBinding({ ...preview(), input_hash: '' }), /完整预览/);
  const invalidSession = createMaintenanceAPI({ fetch: async () => new Response(JSON.stringify({ authenticated: true }), { status: 200 }) });
  await assert.rejects(invalidSession.session(), /接口不一致/);
});

test('server rejection, malformed success and timeout never become success', async () => {
  const denied = createMaintenanceAPI({ fetch: async () => new Response(JSON.stringify({ detail: { code: 'maintenance_csrf', message: 'server message' } }), { status: 403 }) });
  await assert.rejects(denied.login(password, csrf), error => error.status === 403 && error.code === 'maintenance_csrf');
  const malformed = createMaintenanceAPI({ fetch: async () => new Response('<html>login</html>', { status: 200 }) });
  await assert.rejects(malformed.session(), /未完整取得/);
  const incompleteLogin = createMaintenanceAPI({ fetch: async () => new Response(JSON.stringify(session(false)), { status: 200 }) });
  await assert.rejects(incompleteLogin.login(password, csrf), /接口不一致/);
  const stalled = createMaintenanceAPI({ timeout: 5, fetch: async (path, { signal }) => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))) });
  await assert.rejects(stalled.commit(preview(), csrf), error => error.code === 'maintenance_timeout' && /尚未确认/.test(error.message));
});

test('actual Site proxy error shape preserves failure codes and usable bootstrap after bad password', async () => {
  const api = createMaintenanceAPI({ fetch: async path => path === '/api/admin/session' ? new Response(JSON.stringify(session(false)), { status: 200 })
    : new Response(JSON.stringify({ error: { code: path.endsWith('/login') ? 'maintenance_login_failed' : 'maintenance_conflict', message: '安全代理原因' } }), { status: path.endsWith('/login') ? 401 : 409 }) });
  const controller = createMaintenanceController({ api });
  await controller.start(); await controller.login(password);
  assert.equal(controller.state.session.csrf_token, csrf);
  assert.equal(controller.state.error.code, 'maintenance_login_failed'); assert.equal(typeof controller.state.error.code, 'string');
  await assert.rejects(api.commit(preview(), csrf), error => error.status === 409 && error.code === 'maintenance_conflict');
});

test('anonymous bootstrap loads no audit records and no write is allowed', async () => {
  const fixture = syntheticAPI(); let publicReads = 0;
  const controller = createMaintenanceController({ api: fixture.api, read: async () => { publicReads += 1; return catalog; } });
  await controller.start(); await controller.preview();
  assert.deepEqual(fixture.calls.map(item => item.name), ['session']);
  assert.equal(publicReads, 0); assert.equal(controller.state.environment, 'isolated'); assert.equal(controller.state.session, null);
});

test('preview does not save; editing material invalidates its binding and preserves input', async () => {
  const { controller, calls } = await signedController();
  await controller.preview(); assert.ok(controller.state.preview);
  assert.equal(calls.filter(item => item.name === 'commit').length, 0);
  controller.setDraft({ reason: '修改后的原因' });
  assert.equal(controller.state.preview, null); await controller.commit();
  assert.equal(controller.state.draft.reason, '修改后的原因');
  assert.equal(calls.filter(item => item.name === 'commit').length, 0);
});

test('403 preserves the draft while 409 discards a stale preview', async () => {
  let failure = 403;
  const { controller } = await signedController({ commit: () => { throw new MaintenanceError('synthetic rejection', failure, failure === 403 ? 'maintenance_csrf' : 'maintenance_conflict'); } });
  await controller.preview(); const before = structuredClone(controller.state.draft);
  await controller.commit(); assert.ok(controller.state.preview); assert.deepEqual(controller.state.draft, before);
  failure = 409; await controller.commit(); assert.equal(controller.state.preview, null); assert.deepEqual(controller.state.draft, before);
});

test('an unconfirmed save retries exactly the same operation and reports its original receipt', async () => {
  let commits = 0;
  const { controller, calls } = await signedController({ commit: value => { if (++commits === 1) throw new MaintenanceError('操作结果尚未确认。', 0, 'maintenance_timeout'); return receipt(value.environment, { replayed: true }); } });
  await controller.preview(); const original = controller.state.preview.data;
  await controller.commit(); assert.equal(controller.state.preview.data, original); assert.equal(controller.state.receipt, null);
  await controller.commit(); assert.equal(controller.state.receipt.replayed, true); assert.equal(controller.state.preview, null);
  assert.equal(calls.filter(item => item.name === 'preview').length, 1);
  assert.deepEqual(calls.filter(item => item.name === 'commit').map(item => item.args[0]), [original, original]);
  assert.match(controller.state.notice, /原提交回执/);
});

test('duplicate commit and environment edits during a real pending save issue only one request', async () => {
  const delayed = deferred(); const { controller, calls } = await signedController({ commit: () => delayed.promise });
  await controller.preview(); const first = controller.commit();
  assert.equal(controller.state.busy, true); assert.equal(controller.setEnvironment('real'), false); assert.equal(controller.setDraft({ url: 'changed' }), false);
  await controller.commit(); assert.equal(calls.filter(item => item.name === 'commit').length, 1);
  delayed.resolve(receipt()); await first; assert.equal(controller.state.receipt.new, 1);
});

test('expired previews are discarded without requesting a write', async () => {
  const { controller, calls } = await signedController({ preview: () => preview('isolated', { expires_at: '2000-01-01T00:00:00Z' }) });
  await controller.preview(); await controller.commit();
  assert.equal(controller.state.preview, null); assert.match(controller.state.notice, /过期/);
  assert.equal(calls.filter(item => item.name === 'commit').length, 0);
});

test('late reads from an old environment cannot enter the new environment', async () => {
  const delayed = deferred(); let started = false;
  const { controller } = await signedController({ operations: env => started && env === 'isolated' ? delayed.promise : list(env) });
  started = true; const old = controller.refresh(); await tick();
  controller.setEnvironment('real'); await tick();
  assert.equal(controller.state.resources.operations.data.environment, 'real');
  delayed.resolve(list('isolated', [{ actor: 'must-not-reappear' }])); await old;
  assert.equal(controller.state.resources.operations.data.environment, 'real');
  assert.equal(controller.state.preview, null);
});

test('read refreshes coalesce and ordinary read failure keeps clearly stale previous records', async () => {
  const delayed = deferred(); let delay = false;
  const { controller, calls } = await signedController({ operations: env => delay ? delayed.promise : list(env, [{ operation_id: operationId }]) });
  delay = true; const before = calls.filter(item => item.name === 'operations').length;
  const first = controller.refresh(), second = controller.refresh(); await tick();
  assert.equal(calls.filter(item => item.name === 'operations').length, before + 1);
  delayed.reject(new MaintenanceError('synthetic unavailable', 503)); await Promise.all([first, second]);
  assert.equal(controller.state.resources.operations.status, 'error');
  assert.equal(controller.state.resources.operations.data.items[0].operation_id, operationId);
});

test('401 clears privileged state and late old audit responses cannot restore it', async () => {
  const delayed = deferred(); let delay = false;
  const { controller } = await signedController({ operations: env => delay ? delayed.promise : list(env), tasks: env => { if (delay) throw new MaintenanceError('登录过期', 401, 'maintenance_unauthorized'); return list(env); } });
  await controller.preview(); delay = true; const reading = controller.refresh(); await tick();
  assert.equal(controller.state.session, null); assert.equal(controller.state.preview, null);
  delayed.resolve(list('isolated', [{ actor: 'must-not-reappear' }])); await reading;
  assert.equal(controller.state.resources.operations.data, null);
});

test('logout clears audit and preview immediately; lost response remains explicitly unconfirmed', async () => {
  const delayed = deferred(); const { controller } = await signedController({ logout: () => delayed.promise });
  await controller.preview(); const pending = controller.logout();
  assert.equal(controller.state.session, null); assert.equal(controller.state.preview, null); assert.equal(controller.state.resources.operations.data, null);
  delayed.reject(new MaintenanceError('connection lost')); await pending;
  assert.match(controller.state.notice, /退出结果未确认/); assert.equal(controller.state.draft.public_text, '标题：合成隔离公告');
});

test('failed password keeps bootstrap usable for retry without storing the password', async () => {
  const fixture = syntheticAPI({ login: () => { throw new MaintenanceError('登录未成功', 401, 'maintenance_login_failed'); } });
  const controller = createMaintenanceController({ api: fixture.api }); await controller.start(); await controller.login(password);
  assert.equal(controller.state.session.csrf_token, csrf); assert.ok(!JSON.stringify(controller.state).includes(password));
  await controller.login(password); assert.equal(fixture.calls.filter(item => item.name === 'login').length, 2);
});

test('task retry and withdrawal require separate preview and explicit commit', async () => {
  const { controller, calls } = await signedController(); controller.setActionReason('合成原因');
  await controller.retryPreview(12); assert.equal(calls.filter(item => item.name === 'commit').length, 0);
  await controller.commit(); assert.equal(calls.find(item => item.name === 'commit').args[2], null);
  await controller.revertPreview(operationId); assert.equal(controller.state.preview.data.visible, false);
  await controller.commit(); assert.equal(calls.filter(item => item.name === 'commit')[1].args[2], operationId);
});

test('selected correction fields and target remain server-bound, never include actor or database path', async () => {
  const { controller, calls } = await signedController();
  controller.setDraft({ operation_type: 'correction', opportunity_id: '1212', fields: ['event_date'], actor: 'attacker', db_path: 'arbitrary' });
  await controller.preview(); const value = calls.find(item => item.name === 'preview').args[0];
  assert.equal(value.opportunity_id, 1212); assert.deepEqual(value.fields, ['event_date']);
  assert.ok(!('actor' in value) && !('db_path' in value));
});

class Node {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {}; this.events = {}; this.value = ''; this.hidden = false; this.disabled = false; this.checked = false; this.classList = { toggle() {} }; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(node => node.textContent || '').join(''); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  addEventListener(event, callback) { (this.events[event] ||= []).push(callback); }
  async fire(event) { for (const callback of this.events[event] || []) await callback({ target: this, preventDefault() {} }); }
  set innerHTML(value) { throw new Error('Unsafe source HTML'); }
}
function pageDocument() {
  const html = readFileSync('frontend/pages/maintenance.html', 'utf8'), nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const controls = [...html.matchAll(/<[^>]*id="([^"]+)"[^>]*data-maintenance-control[^>]*>/g)].map(match => get(match[1]));
  const fields = [...html.matchAll(/<input[^>]*value="([^"]+)"[^>]*data-maintenance-field[^>]*>/g)].map(match => { const node = new Node('input'); node.value = match[1]; controls.push(node); return node; });
  return { getElementById: get, createElement: tag => new Node(tag), querySelectorAll: selector => selector === '[data-maintenance-field]' ? fields : controls };
}

test('mounted page can log in, review differences and explicitly save with only text rendering', async () => {
  const fixture = syntheticAPI({ preview: payload => preview(payload.environment, { candidate: { title: '<script>synthetic</script>' }, differences: { title: { before: null, after: '<img src=x onerror=synthetic>' } } }), history: (id, env) => ({ ...history(id, env), title: '<script>synthetic</script>', history: [{ field_name: 'title', before_json: 'null', after_json: '"<img>"', actor: 'synthetic', committed_at: '2026-10-12T01:00:00Z' }] }) });
  const doc = pageDocument(); const page = mountMaintenance({ document: doc, api: fixture.api, read: async () => catalog }); await tick();
  assert.equal(doc.getElementById('maintenance-tools').hidden, true);
  doc.getElementById('maintenance-password').value = password;
  await doc.getElementById('maintenance-login-form').fire('submit');
  assert.equal(doc.getElementById('maintenance-password').value, ''); assert.equal(doc.getElementById('maintenance-tools').hidden, false);
  assert.match(doc.getElementById('maintenance-environment-note').textContent, /隔离演练/);
  page.setDraft({ school_key: 'gdut', source_key: 'gdut_teachin', url: 'https://career.gdut.edu.cn/teachin/view/id/1212', reason: '合成核验' });
  await doc.getElementById('maintenance-material-form').fire('submit'); await tick();
  assert.equal(doc.getElementById('maintenance-preview-panel').hidden, false);
  assert.ok(doc.getElementById('maintenance-preview-content').textContent.includes('<img src=x onerror=synthetic>'));
  assert.equal(fixture.calls.filter(item => item.name === 'commit').length, 0);
  await doc.getElementById('maintenance-commit').fire('click');
  assert.equal(doc.getElementById('maintenance-receipt-panel').hidden, false); assert.match(doc.getElementById('maintenance-receipt').textContent, /提交已确认/);
  assert.ok(doc.getElementById('maintenance-history').textContent.includes('<script>synthetic</script>'));
  await doc.getElementById('maintenance-logout').fire('click');
  assert.equal(doc.getElementById('maintenance-tools').hidden, true); assert.equal(doc.getElementById('maintenance-history').textContent, '');
  page.destroy();
});

test('maintenance artifacts use no credential persistence or HTML insertion and keep required click controls', () => {
  const html = readFileSync('frontend/pages/maintenance.html', 'utf8');
  const js = readFileSync('frontend/pages/maintenance.js', 'utf8') + readFileSync('frontend/api/maintenance.js', 'utf8');
  assert.ok(!/localStorage|sessionStorage|document\.cookie|innerHTML|insertAdjacentHTML|console\.log/.test(js));
  assert.ok(!html.includes('csrf_token') && !html.includes('service_token'));
  for (const id of ['maintenance-environment', 'maintenance-public-text', 'maintenance-preview-panel', 'maintenance-commit', 'maintenance-receipt', 'maintenance-action-reason', 'maintenance-tasks', 'maintenance-history']) assert.ok(html.includes(`id="${id}"`));
});

test('registered homepage manual entry, protected summary and resolved task receipt stay usable without retry', async () => {
  const fixture = syntheticAPI({ tasks: env => ({ environment: env, items: [{id: 8, source_key: 'csu_homepage', opportunity_id: 12, status: 'resolved', retry_supported: false, reason_label: '来源获取失败', next_action: '核对公开材料', resolution_history: [{operation_id: 'receipt-8', committed_at:'2026-10-12T01:00:00Z', reason:'已用合法公开材料解决'}]}], groups:[{source_key:'csu_homepage', reason_label:'来源获取失败',next_action:'核对公开材料',active_scope_count:0,resolved_scope_count:1,opportunity_count:1}]}), operations: env => ({environment:env,items:[],summary:{today:{manual_corrections:1,official_changes:null,newly_collected:null},message:'今日自动检查尚未确认'}}) });
  const entries={schools:[{school_key:'csu',name:'中南大学',sources:[{source_key:'csu_homepage',name:'官方入口',channel_key:'homepage',maintenance_material_supported:true}]}]};
  const doc=pageDocument(),page=mountMaintenance({document:doc,api:fixture.api,read:async()=>entries});await tick();
  await page.login(password);page.setDraft({school_key:'csu'});await tick();
  assert.match(doc.getElementById('maintenance-source').textContent,/官方入口/);
  assert.match(doc.getElementById('maintenance-summary').textContent,/人工纠错 1 条/);
  assert.match(doc.getElementById('maintenance-summary').textContent,/官方变化 待核实/);
  assert.match(doc.getElementById('maintenance-tasks').textContent,/receipt-8/);
  assert.ok(!doc.getElementById('maintenance-tasks').textContent.includes('生成重试预览'));
  await page.logout();assert.equal(doc.getElementById('maintenance-summary').textContent,'本环境摘要尚未取得。');
  page.destroy();
});

test('plain and encoded rehearsal markers have the same no-external-link boundary',()=>{
  for(const marker of ['__isolated_fixture__','%5f%5fisolated_fixture%5f%5f','%255f%255fisolated_fixture%255f%255f','%2525255f%2525255fisolated_fixture%2525255f%2525255f']) assert.equal(isRehearsalURL(`https://cnsba.scut.edu.cn/${marker}/c29313a900000001/page.htm`),true);
  assert.equal(isRehearsalURL('https://career.gdut.edu.cn/teachin/view/id/191558'),false);
});
