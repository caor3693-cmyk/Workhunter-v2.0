import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync('ops/preview/worker.mjs', 'utf8').replace('__EMBEDDED_ASSETS__', '{}');
const worker = (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).default;
const env = {WH_API_ORIGIN:'https://bounded-preview.trycloudflare.com', WH_API_SERVICE_TOKEN:'test-service-secret'};

test('proxy refuses arbitrary routes, writes and unsafe origin', async () => {
  assert.equal((await worker.fetch(new Request('https://site.test/api/proxy?url=https://example.org'),env)).status,404);
  assert.equal((await worker.fetch(new Request('https://site.test/api/admin/operations/commit',{method:'POST'}),env)).status,404);
  assert.equal((await worker.fetch(new Request('https://site.test/api/catalog',{method:'POST'}),env)).status,405);
  assert.equal((await worker.fetch(new Request('https://site.test/api/catalog'),{...env,WH_API_ORIGIN:'http://127.0.0.1:8000'})).status,503);
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
