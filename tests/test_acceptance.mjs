import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { collectFrontendAssets } from '../scripts/build_site.mjs';
import { FIXTURE_ORIGIN, fixtureHTML, fixtureResponse, verificationReport } from '../scripts/verify_m0_m1.mjs';
import { readJSON } from '../frontend/api/client.js';
import { createQueryState } from '../frontend/state/store.js';
import { cardFacts, fieldFact } from '../frontend/components/cards.js';
import { realSampleLinksAvailable } from '../frontend/pages/review.js';

const assets = collectFrontendAssets('frontend', 'a'.repeat(40));
test('isolated preview uses only fixed loopback API, declared reads and never visitor credentials', async () => {
  let calls = 0;
  const fetcher = async (url, options) => {
    calls++;
    assert.ok(url.startsWith(FIXTURE_ORIGIN + '/api/opportunities?'));
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers.Cookie, undefined);
    return Response.json({ data_mode: 'isolated_fixture', dataset_id: 'fixture-ds-isolated' });
  };
  const good = await fixtureResponse(new Request('http://127.0.0.1:8789/api/opportunities?view=history&offset=0'), assets, fetcher);
  assert.equal(good.status, 200);
  for (const suffix of ['/api/opportunities?target=https://elsewhere.example/', '/api/admin/write', '/api/opportunities/0', '/unknown']) assert.equal((await fixtureResponse(new Request('http://127.0.0.1:8789' + suffix), assets, fetcher)).status, 404);
  assert.equal((await fixtureResponse(new Request('http://127.0.0.1:8789/api/catalog', { method: 'POST' }), assets, fetcher)).status, 405);
  assert.equal(calls, 1);
});

test('isolated preview refuses real mode, wrong dataset and unconfigured/failed API', async () => {
  for (const data of [{ data_mode: 'real', dataset_id: 'ds-real' }, { data_mode: 'isolated_fixture', dataset_id: 'ds-real' }]) {
    const result = await fixtureResponse(new Request('http://127.0.0.1:8789/api/catalog'), assets, async () => Response.json(data));
    assert.equal(result.status, 503);
    assert.equal((await result.json()).error.code, 'fixture_identity_mismatch');
  }
  const failed = await fixtureResponse(new Request('http://127.0.0.1:8789/api/catalog'), assets, async () => { throw new Error('offline'); });
  assert.equal((await failed.json()).error.code, 'isolated_api_unavailable');
});

test('every isolated page is visibly labelled and placeholder source clicks are blocked', async () => {
  for (const route of ['/', '/sources', '/review', '/opportunities/42']) {
    const response = await fixtureResponse(new Request('http://127.0.0.1:8789' + route), assets);
    assert.equal(response.status, 200);
    const html = await response.text();
    assert.match(html, /data-isolated-fixture="true"/);
    assert.match(html, /未从学校官网取得/);
    assert.match(html, /__isolated_fixture__/);
    assert.match(html, /event.preventDefault/);
    assert.match(html, /aria|role="status"/);
    assert.match(html, /data-isolated-link-status/);
    assert.doesNotMatch(html, /\balert\s*\(/);
  }
  assert.match(fixtureHTML('<body>plain</body>'), /隔离验收样例/);
});

test('placeholder click and middle click show an adjacent live notice without blocking later page actions', () => {
  const html = fixtureHTML('<body>fixture</body>');
  const source = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  const handlers = new Map();
  const notice = { textContent: '', hidden: true, style: {} };
  runInNewContext(source, {
    document: { addEventListener: (name, handler) => handlers.set(name, handler), querySelector: selector => selector === '[data-isolated-link-status]' ? notice : null },
    alert: () => { throw new Error('blocking dialog must never open'); },
  });
  for (const type of ['click', 'auxclick']) {
    let prevented = false;
    let adjacent = false;
    const link = { href: 'https://career.gdut.edu.cn/__isolated_fixture__/attachment', after: value => { adjacent = value === notice; } };
    handlers.get(type)({ target: { closest: () => link }, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(adjacent, true);
    assert.equal(notice.hidden, false);
    assert.equal(notice.style.display, 'block');
    assert.match(notice.textContent, /已阻止外部访问。页面仍可继续操作/);
  }
  let ordinaryPrevented = false;
  handlers.get('click')({ target: { closest: () => ({ href: 'http://127.0.0.1:8789/sources' }) }, preventDefault: () => { ordinaryPrevented = true; } });
  assert.equal(ordinaryPrevented, false);
});

test('engineering report keeps actual CUA and all human acceptance as pending', () => {
  const report = verificationReport([{ name: 'isolated check', exit_code: 0 }], { commit: 'a'.repeat(40), worktree_dirty: true });
  assert.equal(report.status, 'passed');
  assert.equal(report.browser.status, 'pending_actual_CUA');
  assert.equal(report.user_acceptance, 'not_assessed');
  assert.equal(report.site_runtime_identity, 'not_verified_by_this_script');
  assert.equal(report.code_identity.worktree_dirty, true);
  assert.equal(verificationReport([{ exit_code: 1 }], {}).status, 'failed');
});

test('real review sample links require current clean same-project identity and never appear in fixtures or stale reads', () => {
  const sha = 'a'.repeat(40);
  const identity = { project: 'Workhunter-v2.0', backend_commit: sha, build_id: sha, version: '2.0', dataset_id: 'ds-real', data_mode: 'real' };
  const resources = { health: { status: 'ready', data: { ...identity, status: 'ok', database: 'readable' } }, version: { status: 'ready', data: identity } };
  assert.equal(realSampleLinksAvailable(resources, sha), true);
  assert.equal(realSampleLinksAvailable(resources, sha + '+dirty'), false);
  assert.equal(realSampleLinksAvailable({ ...resources, health: { ...resources.health, status: 'loading' } }, sha), false);
  const isolated = Object.fromEntries(Object.entries(resources).map(([key, value]) => [key, { ...value, data: { ...value.data, data_mode: 'isolated_fixture', dataset_id: 'fixture-ds-isolated' } }]));
  assert.equal(realSampleLinksAvailable(isolated, sha), false);
  const html = assets['/frontend/pages/review.html'].body;
  for (const stage of ['M0', 'M1']) for (let index = 1; index <= (stage === 'M0' ? 7 : 8); index++) assert.ok(html.includes(stage + '-0' + index));
  assert.equal((html.match(/本轮候选：待复验/g) || []).length, 8);
  assert.match(html, /M0-02、M0-07 失败；M0-03、M0-06 阻塞/);
  assert.match(html, /第二轮 M0-01—07 已由用户确认通过/);
  assert.equal((html.match(/历史用户结果：失败（待修复复验）/g) || []).length, 3);
  assert.match(html, /M0-M1-REVIEW-20261011.md/);
  for (const id of [3, 31, 41, 38, 96, 40, 70]) assert.ok(html.includes('/opportunities/' + id));
  assert.equal((html.match(/class="real-sample-links" hidden/g) || []).length, 10);
  for (const id of [133, 148, 193, 295]) assert.ok(html.includes('/opportunities/' + id));
  for (const stage of ['M2']) for (let index = 1; index <= 8; index++) assert.ok(html.includes(stage + '-0' + index));
});

test('real generated database API DTOs pass client, frozen query state and card/detail field projection', async () => {
  const python = process.env.WH_PYTHON || (existsSync('.venv/Scripts/python.exe') ? path.resolve('.venv/Scripts/python.exe') : 'python3');
  const source = `import json,tempfile,shutil
from pathlib import Path
from fastapi.testclient import TestClient
from backend.config import ROOT,Settings
from backend.api.app import create_app
from scripts.prepare_acceptance import prepare_bundle,DB_NAME
runtime=(ROOT/'.runtime').resolve(); runtime.mkdir(exist_ok=True)
temporary=Path(tempfile.mkdtemp(prefix='r5-node-api-',dir=runtime)).resolve()
assert temporary.is_relative_to(runtime) and temporary!=runtime
try:
 bundle=temporary/'isolated'; manifest=prepare_bundle(bundle,isolated=True)
 client=TestClient(create_app(Settings(db_path=bundle/DB_NAME,backend_commit='a'*40)),client=('127.0.0.1',1))
 first=client.get('/api/opportunities').json()
 second=client.get('/api/opportunities',params={'offset':20,'dataset_id':first['dataset_id'],'as_of':first['as_of']}).json()
 detail=client.get('/api/opportunities/'+str(manifest['case_ids']['ordinary-six-work-locations'])).json()
 conflict=client.get('/api/opportunities/'+str(manifest['case_ids']['conflicting-retained-venue'])).json()
 print(json.dumps({'first':first,'second':second,'detail':detail,'conflict':conflict},ensure_ascii=False))
finally:
 assert temporary.is_relative_to(runtime) and temporary!=runtime
 shutil.rmtree(temporary)
`;
  const result = spawnSync(python, ['-c', source], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' }, timeout: 30000 });
  assert.equal(result.status, 0, result.stderr);
  const data = JSON.parse(result.stdout);
  const original = globalThis.fetch;
  globalThis.fetch = async route => Response.json(route.startsWith('/api/opportunities/') ? data.detail : new URL(route, 'https://test.invalid').searchParams.get('offset') === '20' ? data.second : data.first);
  const query = createQueryState(readJSON);
  try {
    await query.query();
    assert.equal(query.state.status, 'ready');
    await query.page(20);
    assert.equal(query.state.status, 'ready');
    assert.equal(query.state.dataset, data.first.dataset_id);
    assert.equal(query.state.as_of, data.first.as_of);
    const detail = await readJSON('/api/opportunities/' + data.detail.id);
    assert.equal(detail.materials.length, 2);
    assert.equal(cardFacts(detail).find(row => row.label === '工作地点').text, '广州、深圳、珠海、佛山、东莞 等，详见原文');
    assert.equal(fieldFact(data.conflict, 'event_venue').text, '待核实（材料有冲突）');
    assert.ok(!cardFacts(data.conflict).some(row => row.text.includes('旧会场A')));
  } finally { query.destroy(); globalThis.fetch = original; }
});
