import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const worker=(await import('data:text/javascript;base64,'+Buffer.from(readFileSync('ops/preview/worker.mjs','utf8').replace('__EMBEDDED_ASSETS__','{}')).toString('base64'))).default;
const env={WH_API_ORIGIN:'https://bounded-review.trycloudflare.com',WH_API_SERVICE_TOKEN:'test-service-secret'};
const token='s.'+'a'.repeat(43),csrf='b'.repeat(43);
test('maintenance forwards only business cookie, fixed origin, CSRF and bounded JSON',async()=>{
  const original=globalThis.fetch;
  try{
    globalThis.fetch=async(target,options)=>{
      assert.equal(target.href,env.WH_API_ORIGIN+'/api/admin/operations/commit');
      assert.deepEqual(options.headers,{Accept:'application/json',Authorization:'Bearer test-service-secret',Cookie:'wh_maintenance='+token,Origin:'https://review.test','X-WH-CSRF':csrf,'Content-Type':'application/json'});
      assert.deepEqual(JSON.parse(new TextDecoder().decode(options.body)),{operation_id:'op-test'});
      return Response.json({replayed:false},{headers:{'Set-Cookie':`wh_maintenance=${token}; Domain=upstream.example; Path=/admin; Max-Age=28800; Secure; HttpOnly; SameSite=Strict`}});
    };
    const response=await worker.fetch(new Request('https://review.test/api/admin/operations/commit',{method:'POST',headers:{Origin:'https://review.test','X-WH-CSRF':csrf,'Content-Type':'application/json',Cookie:'site_access=platform-secret; wh_maintenance='+token,Authorization:'visitor-secret'},body:JSON.stringify({operation_id:'op-test'})}),env);
    assert.equal(response.status,200);
    assert.equal(response.headers.get('set-cookie'),`wh_maintenance=${token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=28800`);
  }finally{globalThis.fetch=original;}
});
test('maintenance rejects other methods, duplicate cookies, foreign origin and invalid queries before fetching',async()=>{
  const original=globalThis.fetch;globalThis.fetch=()=>{throw new Error('must not fetch');};
  try{
    for (const [path,options,status] of [
      ['/api/admin/sql',{method:'POST'},404],['/api/admin/tasks/1/retry',{method:'POST'},404],
      ['/api/admin/session',{headers:{Cookie:`wh_maintenance=${token}; wh_maintenance=${token}`}},401],
      ['/api/admin/session',{headers:{Origin:'https://foreign.test'}},403],
      ['/api/admin/operations?environment=real&environment=isolated',{},422],
      ['/api/admin/operations/commit',{method:'POST',headers:{Origin:'https://review.test','X-WH-CSRF':csrf,'Content-Type':'text/plain'},body:'text'},413]]) {
      assert.equal((await worker.fetch(new Request('https://review.test'+path,options),env)).status,status);
    }
  }finally{globalThis.fetch=original;}
});
test('business logout clears only maintenance cookie and safe errors preserve the conflict code',async()=>{
  const original=globalThis.fetch;
  try{
    globalThis.fetch=async()=>Response.json({authenticated:false},{headers:{'Set-Cookie':'wh_maintenance=; expires=Mon, 12 Oct 2026 00:00:00 GMT; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict'}});
    const response=await worker.fetch(new Request('https://review.test/api/admin/session/logout',{method:'POST',headers:{Origin:'https://review.test','X-WH-CSRF':csrf,'Content-Type':'application/json'},body:'{}'}),env);
    assert.equal(response.headers.get('set-cookie'),'wh_maintenance=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0');
    globalThis.fetch=async()=>Response.json({detail:{code:'maintenance_conflict',message:'upstream-secret'}},{status:409});
    const error=await worker.fetch(new Request('https://review.test/api/admin/operations'),env);
    const body=await error.json();assert.equal(body.error.code,'maintenance_conflict');assert.ok(!JSON.stringify(body).includes('upstream-secret'));
  }finally{globalThis.fetch=original;}
});
test('streamed maintenance body is bounded even without Content-Length',async()=>{
  const response=await worker.fetch(new Request('https://review.test/api/admin/materials/preview',{method:'POST',headers:{Origin:'https://review.test','X-WH-CSRF':csrf,'Content-Type':'application/json'},body:'x'.repeat(524289)}),env);
  assert.equal(response.status,413);
});
