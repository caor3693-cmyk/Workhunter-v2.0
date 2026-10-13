import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync('ops/preview/worker.mjs', 'utf8').replace('__EMBEDDED_ASSETS__', '{}');
const worker = (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).default;
const env = {WH_API_ORIGIN:'https://bounded-preview.trycloudflare.com', WH_API_SERVICE_TOKEN:'test-service-secret'};
async function capture(fetcher, run) {
  const original = globalThis.fetch;
  const warn = console.warn;
  const logs = [];
  globalThis.fetch = fetcher;
  console.warn = value => logs.push(value);
  try { await run(logs); } finally {globalThis.fetch = original; console.warn = warn;}
}

test('proxy refuses arbitrary routes, writes and unsafe origin', async () => {
  assert.equal((await worker.fetch(new Request('https://site.test/api/proxy?url=https://example.org'),env)).status,404);
  assert.equal((await worker.fetch(new Request('https://site.test/api/admin/operations/commit',{method:'POST'}),env)).status,403);
  assert.equal((await worker.fetch(new Request('https://site.test/api/catalog',{method:'POST'}),env)).status,405);
  assert.equal((await worker.fetch(new Request('https://site.test/api/catalog'),{...env,WH_API_ORIGIN:'http://127.0.0.1:8000'})).status,503);
});
test('refresh status proxies only the read projection and has no trigger route', async () => {
  await capture(async (target, options) => {
    assert.equal(target.pathname, '/api/refresh/status');
    assert.equal(options.method, 'GET');
    return Response.json({dataset_id: 'v2-only', status: 'disabled', next_run_at: null});
  }, async () => {
    const result = await worker.fetch(new Request('https://site.test/api/refresh/status'), env);
    assert.equal(result.status, 200);
    assert.equal((await result.json()).status, 'disabled');
    assert.equal((await worker.fetch(new Request('https://site.test/api/refresh/status', {method: 'POST'}), env)).status, 405);
    assert.equal((await worker.fetch(new Request('https://site.test/api/refresh/start'), env)).status, 404);
  });
});
test('only service authorization is forwarded; payload and dataset stay upstream-owned', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (target, options) => {
      assert.equal(target.href,'https://bounded-preview.trycloudflare.com/api/catalog');
      assert.deepEqual(options.headers,{Accept:'application/json',Authorization:'Bearer test-service-secret'});
      assert.equal(options.redirect,'manual');
      return Response.json({dataset_id:'actual-new-dataset',schools:[]},{headers:{'Set-Cookie':'platform-secret=never-forward'}});
    };
    const response = await worker.fetch(new Request('https://site.test/api/catalog',{headers:{Cookie:'sites-platform=secret',Authorization:'visitor-header'}}),env);
    assert.equal(response.status,200);
    assert.equal(response.headers.get('set-cookie'),null);
    assert.equal((await response.json()).dataset_id,'actual-new-dataset');
  } finally {globalThis.fetch = original;}
});
test('redirect, non-JSON and oversized upstream responses fail without leaking credentials', async () => {
  const original = globalThis.fetch;
  try {
    for (const response of [new Response(null,{status:302,headers:{Location:'https://example.org'}}),new Response('failure'),new Response('{}',{headers:{'Content-Type':'application/json','Content-Length':'1048577'}})]) {
      globalThis.fetch = async()=>response;
      const result = await worker.fetch(new Request('https://site.test/api/catalog'),env);
      assert.equal(result.status,502);
      assert.ok(!(await result.text()).includes(env.WH_API_SERVICE_TOKEN));
    }
  } finally {globalThis.fetch = original;}
});

test('200 malformed JSON is refused and diagnostic output contains only bounded fields', async () => {
  const query = 'private-query-must-not-appear';
  await capture(async () => new Response('{private-origin=' + env.WH_API_ORIGIN, {headers: {'Content-Type': 'application/json'}}), async logs => {
    const result = await worker.fetch(new Request('https://site.test/api/opportunities/123?keyword=' + query), env);
    assert.equal(result.status, 502);
    const body = await result.json();
    assert.equal(body.error.code, 'upstream_invalid_json');
    assert.deepEqual(Object.keys(body.diagnostic).sort(), ['content_type', 'layer', 'path', 'request_id', 'upstream_status']);
    assert.equal(body.diagnostic.path, '/api/opportunities/{id}');
    assert.equal(body.diagnostic.layer, 'upstream_body');
    assert.equal(body.diagnostic.upstream_status, 200);
    assert.equal(result.headers.get('x-request-id'), body.diagnostic.request_id);
    const output = JSON.stringify(body) + logs.join('');
    for (const privateValue of [query, env.WH_API_ORIGIN, env.WH_API_SERVICE_TOKEN]) assert.ok(!output.includes(privateValue));
    assert.equal(logs.length, 1);
  });
});

test('service authorization and unreadable database retain safe classifications without upstream messages', async () => {
  for (const [status, code] of [[401, 'service_unauthorized'], [503, 'database_unavailable']]) {
    await capture(async () => Response.json({detail: {code, message: env.WH_API_SERVICE_TOKEN + env.WH_API_ORIGIN}}, {status}), async logs => {
      const response = await worker.fetch(new Request('https://site.test/health'), env);
      assert.equal(response.status, status);
      const body = await response.json();
      assert.equal(body.error.code, code);
      assert.equal(body.diagnostic.layer, 'upstream_api');
      assert.equal(body.diagnostic.upstream_status, status);
      assert.ok(!body.error.message.includes('Site'));
      assert.ok(!(JSON.stringify(body) + logs.join('')).includes(env.WH_API_SERVICE_TOKEN));
      assert.ok(!(JSON.stringify(body) + logs.join('')).includes(env.WH_API_ORIGIN));
    });
  }
});

test('redirect, non JSON and unexpected media types have distinct safe diagnostics', async () => {
  for (const [response, code, type] of [
    [new Response(null, {status: 302, headers: {Location: env.WH_API_ORIGIN}}), 'upstream_redirect', 'missing'],
    [new Response('private body', {headers: {'Content-Type': 'text/html'}}), 'upstream_non_json', 'text/html'],
    [new Response('private body', {headers: {'Content-Type': 'application/private-secret'}}), 'upstream_non_json', 'other'],
  ]) await capture(async () => response, async () => {
    const result = await worker.fetch(new Request('https://site.test/health'), env);
    const body = await result.json();
    assert.equal(result.status, 502);
    assert.equal(body.error.code, code);
    assert.equal(body.diagnostic.content_type, type);
    assert.ok(!JSON.stringify(body).includes('private'));
  });
});

test('JSON suffix media types are accepted without rewriting successful payload facts', async () => {
  await capture(async () => new Response('{"dataset_id":"actual","data_mode":"empty"}', {headers: {'Content-Type': 'application/problem+json'}}), async () => {
    const result = await worker.fetch(new Request('https://site.test/health'), env);
    assert.equal(result.status, 200);
    assert.equal((await result.json()).dataset_id, 'actual');
  });
});

test('a streamed response without content length cannot exceed the response limit', async () => {
  let cancelled = false;
  await capture(async () => new Response(new ReadableStream({start(controller) { controller.enqueue(new Uint8Array(1048577)); }, cancel() { cancelled = true; }}), {headers: {'Content-Type': 'application/json'}}), async () => {
    const result = await worker.fetch(new Request('https://site.test/health'), env);
    assert.equal(result.status, 502);
    assert.equal((await result.json()).error.code, 'response_too_large');
    assert.equal(cancelled, true);
  });
});

test('the 12 second deadline covers both connection and body streaming', async () => {
  const originalTimer = globalThis.setTimeout;
  globalThis.setTimeout = (callback, delay) => {assert.equal(delay, 12000); return originalTimer(callback, 10);};
  try {
    for (const phase of ['upstream_connect', 'upstream_body']) await capture(async (_, {signal}) => {
      if (phase === 'upstream_connect') return await new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true}));
      return new Response(new ReadableStream({start(controller) {signal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), {once: true});}}), {headers: {'Content-Type': 'application/json'}});
    }, async () => {
      const result = await worker.fetch(new Request('https://site.test/health'), env);
      assert.equal(result.status, 504);
      const body = await result.json();
      assert.equal(body.error.code, 'development_api_timeout');
      assert.equal(body.diagnostic.layer, phase);
    });
  } finally {globalThis.setTimeout = originalTimer;}
});

test('the fixed page mapping supports direct entry and keeps unknown pages at 404', async () => {
  const assets = Object.fromEntries(['/index.html', '/frontend/pages/sources.html', '/frontend/pages/review.html', '/frontend/pages/detail.html'].map(path => [path, {type: 'text/html', body: path, hash: 'fixture-only'}]));
  const pageSource = readFileSync('ops/preview/worker.mjs', 'utf8').replace('__EMBEDDED_ASSETS__', JSON.stringify(assets));
  const pages = (await import('data:text/javascript;base64,' + Buffer.from(pageSource).toString('base64'))).default;
  for (const [path, asset] of [['/', '/index.html'], ['/sources', '/frontend/pages/sources.html'], ['/review', '/frontend/pages/review.html'], ['/opportunities/123', '/frontend/pages/detail.html']]) {
    const response = await pages.fetch(new Request('https://site.test' + path), env);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), asset);
  }
  for (const path of ['/missing', '/sources/', '/opportunities/0', '/api/unknown']) assert.equal((await pages.fetch(new Request('https://site.test' + path), env)).status, 404);
});

test('known pagination and field errors keep their safe business codes', async () => {
  for (const code of ['invalid_as_of', 'as_of_required', 'invalid_keyword', 'invalid_dataset']) {
    await capture(async () => Response.json({detail:{code,message:'private upstream content'}},{status:422}), async () => {
      const result = await worker.fetch(new Request('https://site.test/api/opportunities'), env);
      assert.equal(result.status,422);
      const payload=await result.json();
      assert.equal(payload.error.code,code);
      assert.ok(!JSON.stringify(payload).includes('private upstream content'));
    });
  }
});

test('client cancellation reaches the bounded upstream request without becoming a timeout', async () => {
  const active=new AbortController();
  let begin;
  const entered=new Promise(resolve=>{begin=resolve;});
  let upstreamAborted=false;
  await capture(async (_, {signal}) => {
    begin();
    return new Promise((_,reject)=>signal.addEventListener('abort',()=>{
      upstreamAborted=true;
      reject(new DOMException('Aborted','AbortError'));
    },{once:true}));
  }, async logs => {
    const pending=worker.fetch(new Request('https://site.test/api/opportunities',{signal:active.signal}),env);
    await entered;
    active.abort();
    const result=await pending;
    assert.equal(result.status,499);
    assert.equal((await result.json()).error.code,'request_cancelled');
    assert.equal(upstreamAborted,true);
    assert.equal(logs.length,0);
  });
});

test('segmented timing forwards only bounded API durations and numeric timestamps', async () => {
  await capture(async()=>Response.json({dataset_id:'actual'}, {headers:{
    'Server-Timing':'private;desc="secret", api;dur=4.25',
    'X-WH-API-Started-At':'1791727200000', 'X-WH-API-Ended-At':'private-value',
  }}),async()=>{
    const result=await worker.fetch(new Request('https://site.test/api/opportunities'),env);
    assert.match(result.headers.get('server-timing'),/^api;dur=4.25, proxy_connect;dur=[\d.]+, proxy_body;dur=[\d.]+, proxy_total;dur=[\d.]+$/);
    assert.equal(result.headers.get('x-wh-api-started'),'1791727200000');
    assert.equal(result.headers.get('x-wh-api-ended'),null);
    assert.ok(!result.headers.get('server-timing').includes('secret'));
    assert.equal(result.headers.get('cache-control'),'no-store');
  });
});
