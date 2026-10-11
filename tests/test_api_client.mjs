import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readJSON, ReadError} from '../frontend/api/client.js';

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
