import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PAGE_READ_PATHS } from '../frontend/pages/routes.js';
import { createPageReader, pageDatasetsAgree, resourceMessage } from '../frontend/pages/shared.js';
import { assessReadIdentity, feedbackTemplate } from '../frontend/pages/review.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('page read sets keep home independent of source/identity failures', async () => {
  const requests = [];
  const reader = createPageReader(PAGE_READ_PATHS.home, () => {}, async path => {
    requests.push(path);
    assert.ok(!path.includes('/sources/') && path !== '/health' && path !== '/version');
    return { dataset_id: 'test-isolated-dataset' };
  });
  await reader.reload();
  assert.deepEqual(requests.sort(), ['/api/catalog', '/api/opportunities', '/api/updates/summary']);
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
  assert.equal((review.match(/用户结果：未测/g) || []).length, 8);
});
