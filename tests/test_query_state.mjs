import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createQueryState, datasetConsistency, queryPath } from '../frontend/state/store.js';

// Every response here is isolated test input, never production or collection evidence.
const response = (path, dataset = 'isolated-A', as_of = '2026-10-11') => {
  const params = new URL(path, 'https://test.invalid').searchParams;
  const filters = Object.fromEntries([...params].filter(([key]) => !['offset', 'limit', 'dataset_id', 'as_of'].includes(key)));
  return { dataset_id: dataset, data_mode: 'isolated-test', as_of, items: [{ id: 1 }], total: 50,
    offset: Number(params.get('offset')), limit: Number(params.get('limit')), has_more: true,
    applied_filters: { ...filters, as_of, recent_window: { days: 14, published_from: '2026-09-28', published_to: as_of, events_from: as_of, events_to: '2026-10-25' } } };
};
function pendingReads() {
  const calls = [];
  return { calls, read: (path, { signal }) => new Promise((resolve, reject) => calls.push({ path, signal, resolve, reject })) };
}

test('draft edits do not leak into pagination, dates, scope or view requests', async () => {
  const calls = [];
  const query = createQueryState(async path => { calls.push(path); return response(path); });
  query.editDraft({ school_key: 'scut', keyword: '电气', date_from: '2026-09-01', campus_id: '' });
  await query.submit();
  query.editDraft({ keyword: '未提交的草稿', date_from: '2026-01-01' });
  await query.page(20);
  let params = new URL(calls.at(-1), 'https://test.invalid').searchParams;
  assert.equal(params.get('keyword'), '电气');
  assert.equal(params.get('date_from'), '2026-09-01');
  assert.equal(params.get('dataset_id'), 'isolated-A');
  assert.equal(params.get('as_of'), '2026-10-11');
  await query.setScope('all');
  await query.setView('history');
  params = new URL(calls.at(-1), 'https://test.invalid').searchParams;
  assert.equal(params.get('keyword'), '电气');
  assert.equal(params.get('date_from'), '2026-09-01');
  assert.equal(params.get('scope'), 'all');
  assert.equal(params.get('view'), 'history');
  assert.equal(params.get('offset'), '0');
  assert.equal(query.state.draft.keyword, '未提交的草稿');
  query.destroy();
});

test('school changes clear incompatible campus and invalidate an in-flight query without submission', async () => {
  const pending = pendingReads();
  const query = createQueryState(pending.read);
  query.editDraft({ school_key: 'scut' });
  query.editDraft({ campus_id: '1' });
  const old = query.submit();
  query.editDraft({ school_key: 'gdut' });
  assert.equal(query.state.draft.campus_id, undefined);
  assert.equal(pending.calls[0].signal.aborted, true);
  assert.equal(pending.calls.length, 1);
  pending.calls[0].resolve(response(pending.calls[0].path));
  await old;
  assert.equal(query.state.data, null);
  query.destroy();
});

test('unknown campus is a separate submitted condition and a valid campus is not submitted with it', async () => {
  const calls = [];
  const query = createQueryState(async path => { calls.push(path); return response(path); });
  query.editDraft({ school_key: 'gdut' });
  query.editDraft({ campus_unknown: true, campus_id: '' });
  await query.submit();
  const params = new URL(calls[0], 'https://test.invalid').searchParams;
  assert.equal(params.get('campus_unknown'), 'true');
  assert.equal(params.has('campus_id'), false);
  query.destroy();
});

test('a late response and its after-await continuation cannot replace a newer query', async () => {
  const pending = pendingReads();
  const query = createQueryState(pending.read);
  const old = query.query({ school_key: 'scut', keyword: 'old' });
  const latest = query.query({ school_key: 'gdut', keyword: 'new' });
  pending.calls[1].resolve(response(pending.calls[1].path, 'isolated-new'));
  await latest;
  const accepted = query.state.displayed;
  pending.calls[0].resolve(response(pending.calls[0].path, 'isolated-old'));
  await old;
  assert.equal(query.state.displayed, accepted);
  assert.equal(query.state.applied.school_key, 'gdut');
  assert.equal(query.state.dataset, 'isolated-new');
  query.destroy();
});

test('manual search and clear reset page; clear retains explicitly selected scope and view', async () => {
  const query = createQueryState(async path => response(path));
  await query.query({ view: 'history', scope: 'all', keyword: 'previous' });
  await query.page(20);
  query.editDraft({ keyword: 'next' });
  await query.submit();
  assert.equal(query.state.page, 0);
  await query.page(20);
  await query.clear();
  assert.equal(query.state.page, 0);
  assert.deepEqual(query.state.draft, {});
  assert.deepEqual(query.state.applied, { view: 'history', scope: 'all' });
  query.destroy();
});

test('a failed changed query keeps displayed scope, dataset and as_of and disables mixed pagination', async () => {
  let fail = false;
  const query = createQueryState(async path => { if (fail) throw new Error('503'); return response(path); });
  await query.query({ school_key: 'scut', view: 'history' });
  const displayed = query.state.displayed;
  fail = true;
  await query.query({ school_key: 'gdut', view: 'recent' });
  assert.equal(query.state.status, 'error');
  assert.equal(query.state.displayed, displayed);
  assert.equal(query.state.displayed.filters.school_key, 'scut');
  assert.equal(query.state.dataset, 'isolated-A');
  assert.equal(query.state.as_of, '2026-10-11');
  assert.equal(query.canPage(), false);
  query.destroy();
});

test('409 discards old page before recovery and reloads first page with the same applied conditions', async () => {
  const calls = [];
  const pending = pendingReads();
  const query = createQueryState(async (path, options) => {
    calls.push(path);
    if (calls.length === 1) return response(path);
    if (calls.length === 2) throw Object.assign(new Error('changed'), { code: 'dataset_changed' });
    return pending.read(path, options);
  });
  await query.query({ school_key: 'gdut', keyword: '电气', view: 'history', scope: 'all' });
  query.editDraft({ keyword: '未提交草稿' });
  const page = query.page(20);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(query.state.displayed, null);
  assert.equal(query.state.data, null);
  assert.equal(query.state.recovering, true);
  const params = new URL(calls[2], 'https://test.invalid').searchParams;
  assert.equal(params.get('offset'), '0');
  assert.equal(params.get('keyword'), '电气');
  assert.equal(params.get('scope'), 'all');
  assert.equal(params.has('dataset_id'), false);
  assert.equal(params.has('as_of'), false);
  pending.calls[0].resolve(response(calls[2], 'isolated-B', '2026-10-12'));
  await page;
  assert.equal(query.state.dataset, 'isolated-B');
  assert.equal(query.state.as_of, '2026-10-12');
  assert.equal(query.state.page, 0);
  query.destroy();
});

test('an old 409 recovery cannot overwrite a newer manual query or its scope after awaiting', async () => {
  const pending = pendingReads();
  let count = 0;
  const query = createQueryState(async (path, options) => {
    if (++count === 1) return response(path);
    if (count === 2) throw Object.assign(new Error('changed'), { code: 'dataset_changed' });
    return pending.read(path, options);
  });
  await query.query({ school_key: 'scut' });
  const old = query.page(20);
  await new Promise(resolve => setTimeout(resolve, 0));
  const latest = query.query({ school_key: 'gdut', view: 'undated' });
  pending.calls[1].resolve(response(pending.calls[1].path, 'isolated-latest'));
  await latest;
  pending.calls[0].resolve(response(pending.calls[0].path, 'isolated-old-recovery'));
  await old;
  assert.equal(query.state.dataset, 'isolated-latest');
  assert.equal(query.state.displayed.filters.view, 'undated');
  query.destroy();
});

test('pagination cannot accept a quietly changed dataset, day, offset or applied condition', async () => {
  for (const patch of [{ dataset_id: 'quiet-change' }, { as_of: '2026-10-12' }, { offset: 0 }, { applied_filters: { view: 'undated', scope: 'all' } }]) {
    let first = true;
    const query = createQueryState(async path => { const data = response(path); if (first) { first = false; return data; } return { ...data, ...patch }; });
    await query.query({ school_key: 'gdut' });
    const snapshot = query.state.displayed;
    await query.page(20);
    assert.equal(query.state.status, 'error', JSON.stringify(patch));
    assert.equal(query.state.displayed, snapshot);
    query.destroy();
  }
});

test('midnight pagination retains original Shanghai query day and snapshots include stale/loading identity', () => {
  assert.match(queryPath({ view: 'recent' }, 20, { dataset_id: 'isolated-A', as_of: '2026-10-11' }), /as_of=2026-10-11/);
  assert.throws(() => queryPath({}, 20, { dataset_id: 'isolated-A' }), /首页/);
  for (const status of ['loading', 'error', 'stale']) assert.equal(datasetConsistency({ catalog: { status: 'ready', data: { dataset_id: 'new', data_mode: 'real' } }, opportunities: { status, data: { dataset_id: 'old', data_mode: 'real' } } }), false);
  assert.equal(datasetConsistency({ one: { data: { dataset_id: 'same', project: 'Workhunter-v2.0' } }, two: { data: { dataset_id: 'same', project: 'other' } } }), false);
});

test('destroyed query never publishes an arriving result', async () => {
  const pending = pendingReads();
  const query = createQueryState(pending.read);
  const request = query.query();
  query.destroy();
  pending.calls[0].resolve(response(pending.calls[0].path));
  await request;
  assert.equal(query.state.data, null);
});
