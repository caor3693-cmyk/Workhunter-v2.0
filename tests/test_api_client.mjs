import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readJSON, ReadError, publicReadPath} from '../frontend/api/client.js';

const catalog = {dataset_id: 'isolated-catalog', data_mode: 'empty', schools: []};
async function withFetch(fetcher, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fetcher;
  try { await run(); } finally { globalThis.fetch = original; }
}

test('proxy and API error shapes always produce a string code', async () => {
  for (const [body, code] of [
    [{error: {code: 'development_api_unavailable'}}, 'development_api_unavailable'],
    [{detail: {code: 'database_unavailable'}}, 'database_unavailable'],
    [{error: 'upstream_http_error'}, 'upstream_http_error'],
    [{error: {unexpected: 'object'}}, 'http_error'],
  ]) {
    await withFetch(async () => Response.json(body, {status: 503}), async () => {
      await assert.rejects(readJSON('/api/catalog'), error => error instanceof ReadError && error.code === code && typeof error.code === 'string');
    });
  }
});

test('service authorization failure does not ask the visitor to log in to Site', async () => {
  for (const body of [{detail: {code: 'service_unauthorized'}}, {error: {code: 'service_unauthorized'}}]) {
    await withFetch(async () => Response.json(body, {status: 401}), async () => {
      await assert.rejects(readJSON('/health'), error => error.code === 'service_unauthorized' && /授权配置/.test(error.message) && !/登录/.test(error.message));
    });
  }
  await withFetch(async () => new Response('platform access denied', {status: 403}), async () => {
    await assert.rejects(readJSON('/health'), error => /Site/.test(error.message));
  });
});

test('proxy configuration, timeout and database failures have useful distinct messages', async () => {
  for (const [code, message] of [['development_api_unconfigured', /尚未连接/], ['development_api_timeout', /超时/], ['database_unavailable', /暂不可读/]]) {
    await withFetch(async () => Response.json({error: {code}}, {status: 503}), async () => {
      await assert.rejects(readJSON('/health'), error => error.code === code && message.test(error.message));
    });
  }
});

test('an abort while reading a 200 body is a timeout, not invalid JSON', async () => {
  await withFetch(async (_, {signal}) => ({ok: true, status: 200, json: () => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true}))}), async () => {
    await assert.rejects(readJSON('/health', {timeout: 10}), error => error instanceof ReadError && error.code === 'timeout');
  });
});

test('caller cancellation during the body is preserved as cancellation', async () => {
  const controller = new AbortController();
  await withFetch(async (_, {signal}) => ({ok: true, status: 200, json: () => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true});
    queueMicrotask(() => controller.abort());
  })}), async () => {
    await assert.rejects(readJSON('/health', {signal: controller.signal}), error => error.name === 'AbortError' && !(error instanceof ReadError));
  });
});

test('a malformed completed body remains an invalid response', async () => {
  await withFetch(async () => new Response('{', {headers: {'Content-Type': 'application/json'}}), async () => {
    await assert.rejects(readJSON('/health'), error => error.code === 'invalid_response');
  });
});

test('the default client deadline leaves time for the 12 second proxy response', async () => {
  const original = globalThis.setTimeout;
  let deadline;
  globalThis.setTimeout = (callback, delay) => { deadline = delay; return original(callback, delay); };
  try {
    await withFetch(async (_, options) => {
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.cache, 'no-store');
      return Response.json(catalog);
    }, async () => assert.deepEqual(await readJSON('/api/catalog'), catalog));
    assert.equal(deadline, 15000);
  } finally { globalThis.setTimeout = original; }
});

test('a failed read can recover on the next real request', async () => {
  let reads = 0;
  await withFetch(async () => ++reads === 1 ? Response.json({error: {code: 'development_api_unavailable'}}, {status: 502}) : Response.json(catalog), async () => {
    await assert.rejects(readJSON('/api/catalog'), error => error.code === 'development_api_unavailable');
    assert.deepEqual(await readJSON('/api/catalog'), catalog);
    assert.equal(reads, 2);
  });
});

const list = { dataset_id: 'isolated-list', data_mode: 'isolated-test', items: [], total: 0, offset: 0, limit: 20, has_more: false, as_of: '2026-10-11', applied_filters: { view: 'recent', scope: 'electrical', as_of: '2026-10-11', recent_window: {} } };

test('query-bearing reads validate pathname and the exact declared parameter set before fetching', async () => {
  const path = '/api/opportunities?school_key=gdut&keyword=%E7%94%B5%E6%B0%94&campus_unknown=true&view=history&scope=all&offset=0&limit=20';
  assert.equal(publicReadPath(path), '/api/opportunities');
  await withFetch(async requested => { assert.equal(requested, path); return Response.json(list); }, async () => assert.deepEqual(await readJSON(path), list));
  for (const bad of ['/api/opportunities?admin=true', '/api/opportunities?view=history&view=recent', '/api/catalog?keyword=x', '/api/opportunities/1?keyword=x', '//other.example/api/catalog', 'https://other.example/api/catalog', '/api/../health', '/api/opportunities#x', '/api/opportunities/01', '/api/opportunities/0', '/api/opportunities/9223372036854775808', '/api/opportunities/1/more']) {
    await withFetch(async () => { throw new Error('A rejected route must not fetch'); }, async () => await assert.rejects(readJSON(bad), error => error.code === 'unsupported_path'));
  }
});

test('detail reads preserve the flat card/material/coverage contract and reject mismatched identity', async () => {
  const detail = { dataset_id: 'isolated-detail', data_mode: 'isolated-test', id: 42, field_observations: {}, roster_fragments: [], job_fragments: [], attachments: [], materials: [], coverage: {} };
  await withFetch(async () => Response.json(detail), async () => assert.deepEqual(await readJSON('/api/opportunities/42'), detail));
  for (const patch of [{ id: 43 }, { materials: null }, { coverage: null }, { field_observations: [] }]) await withFetch(async () => Response.json({ ...detail, ...patch }), async () => assert.rejects(readJSON('/api/opportunities/42'), error => error.code === 'invalid_contract'));
  assert.equal(publicReadPath('/api/opportunities/9223372036854775807'), '/api/opportunities/9223372036854775807');
});

test('list needs a frozen calendar day, canonical filter window and valid pagination shape', async () => {
  for (const patch of [{ as_of: '2026-02-30' }, { as_of: undefined }, { applied_filters: null }, { applied_filters: [] }, { applied_filters: { as_of: '2026-10-10', recent_window: {} } }, { offset: -1 }, { limit: 0 }, { total: Number.MAX_SAFE_INTEGER + 1 }, { has_more: 'true' }]) {
    await withFetch(async () => Response.json({ ...list, ...patch }), async () => assert.rejects(readJSON('/api/opportunities?view=history'), error => error.code === 'invalid_contract'));
  }
});

test('422 field failures and missing announcements explain the concrete next action', async () => {
  for (const [code, pattern, status] of [['invalid_date_range', /起始日期.*结束日期/, 422], ['school_campus_conflict', /校区.*学校/, 422], ['as_of_required', /首页查询日期/, 422], ['invalid_dataset', /分页数据版本.*第一页/, 422], ['opportunity_not_found', /不存在或尚未收录/, 404]]) await withFetch(async () => Response.json({ detail: { code } }, { status }), async () => assert.rejects(readJSON('/api/opportunities'), error => error.code === code && pattern.test(error.message)));
});

test('timing observes actual request/header/body boundaries and safe API clocks without adding response fields', async () => {
  const events = [];
  const headers = { 'Server-Timing': 'api;dur=7, proxy_total;dur=12', 'X-WH-API-Started': '1791680400000', 'X-WH-API-Ended': '1791680400007' };
  await withFetch(async () => Response.json(catalog, { headers }), async () => {
    const data = await readJSON('/api/catalog', { onTiming: event => events.push(event) });
    assert.deepEqual(data, catalog);
    assert.deepEqual(Object.keys(data).sort(), Object.keys(catalog).sort());
  });
  assert.deepEqual(events.map(event => event.phase), ['request', 'headers', 'json', 'validated']);
  assert.equal(events[1].server_timing, headers['Server-Timing']);
  assert.equal(events[1].api_started_at, 1791680400000);
  assert.equal(events[1].api_ended_at, 1791680400007);
  assert.ok(events.every((event, index) => Number.isFinite(event.at) && Number.isFinite(event.elapsed_ms) && (index === 0 || event.elapsed_ms >= events[index - 1].elapsed_ms)));
});

test('failed timing stays failed, absent or malformed API clocks stay null and observer errors cannot break reads', async () => {
  const events = [];
  await withFetch(async () => Response.json({ error: { code: 'http_error' } }, { status: 403, headers: { 'X-WH-API-Started': 'not-a-clock', 'X-WH-API-Ended': 'Infinity' } }), async () => {
    await assert.rejects(readJSON('/api/catalog', { onTiming: event => events.push(event) }), error => error.status === 403);
  });
  assert.equal(events.at(-1).phase, 'failed');
  assert.equal(events.at(-1).status, 403);
  assert.equal(events.find(event => event.phase === 'headers').api_started_at, null);
  assert.equal(events.find(event => event.phase === 'headers').api_ended_at, null);
  assert.ok(!events.some(event => event.phase === 'validated'));
  await withFetch(async () => Response.json(catalog), async () => assert.deepEqual(await readJSON('/api/catalog', { onTiming() { throw new Error('broken measurement'); } }), catalog));
});
