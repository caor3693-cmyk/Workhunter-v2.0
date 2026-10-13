// Thin transport only: business facts remain in the Python service.
const ASSETS = __EMBEDDED_ASSETS__;
const PUBLIC_PATHS = new Set(['/health', '/version', '/api/catalog', '/api/opportunities', '/api/updates/summary', '/api/sources/status', '/api/refresh/status']);
const PAGE_PATHS = new Map([['/', '/index.html'], ['/sources', '/frontend/pages/sources.html'], ['/review', '/frontend/pages/review.html'], ['/maintenance', '/frontend/pages/maintenance.html']]);
const MAX_BYTES = 1048576;
const API_CODES = new Set(['service_unauthorized', 'loopback_only', 'database_unavailable', 'dataset_changed', 'dataset_required', 'unsupported_parameter', 'duplicate_parameter', 'invalid_date', 'invalid_date_range', 'invalid_as_of', 'as_of_required', 'invalid_keyword', 'invalid_dataset', 'invalid_kind', 'invalid_view_or_scope', 'invalid_number', 'invalid_campus_unknown', 'campus_conflict', 'school_not_found', 'campus_not_found', 'school_campus_conflict', 'invalid_opportunity', 'opportunity_not_found']);
export const isPublicPath = path => PUBLIC_PATHS.has(path) || /^\/api\/opportunities\/[1-9]\d*$/.test(path);
export function adminRoute(path, method) {
  if (method==='GET' && ['/api/admin/session','/api/admin/operations','/api/admin/tasks'].includes(path)) return true;
  if (method==='GET' && /^\/api\/admin\/opportunities\/[1-9]\d*(?:\/history)?$/.test(path)) return true;
  if (method==='POST' && ['/api/admin/session/login','/api/admin/session/logout','/api/admin/materials/preview','/api/admin/operations/commit'].includes(path)) return true;
  return method==='POST' && (/^\/api\/admin\/operations\/[A-Za-z0-9_-]{1,120}\/(?:revert-preview|revert)$/.test(path) || /^\/api\/admin\/tasks\/[1-9]\d*\/retry-preview$/.test(path));
}
const ADMIN_CODES = new Set(['maintenance_unauthorized','maintenance_origin','maintenance_csrf','maintenance_unavailable','maintenance_login_failed','maintenance_rate_limited','maintenance_invalid_input','maintenance_input_too_large','maintenance_conflict','maintenance_busy','maintenance_material_unavailable','maintenance_input','maintenance_body_size','maintenance_environment','maintenance_source','maintenance_target','maintenance_record_url','maintenance_field_evidence','maintenance_operation_missing','maintenance_revert_type','maintenance_task','maintenance_task_unavailable','maintenance_commit_input','maintenance_revert_input','maintenance_retry_input','maintenance_reason']);
for (const code of ['maintenance_archive','maintenance_expiry','maintenance_fields','maintenance_isolation_unavailable','maintenance_material','maintenance_material_size','maintenance_material_unusable','maintenance_operation','maintenance_owner_evidence','maintenance_pagination','maintenance_restricted','maintenance_source_url','maintenance_task_status','maintenance_task_target']) ADMIN_CODES.add(code);
function maintenanceCookie(header) {
  const matches=(header||'').split(';').map(x=>x.trim()).filter(x=>x.startsWith('wh_maintenance='));
  if (matches.length>1) return null;
  if (!matches.length) return '';
  return /^wh_maintenance=[bs]\.[A-Za-z0-9_-]{43}$/.test(matches[0]) ? matches[0] : null;
}
function responseCookie(header) {
  const first=(header||'').split(';')[0];
  if (!/^wh_maintenance=(?:[bs]\.[A-Za-z0-9_-]{43})?$/.test(first)) return null;
  const age=/(?:^|;)\s*Max-Age=(-?\d+)\s*(?:;|$)/i.exec(header);
  return first+'; Path=/; Secure; HttpOnly; SameSite=Strict'+(age && Number(age[1])>=0 && Number(age[1])<=28800 ? '; Max-Age='+Number(age[1]) : '');
}
async function boundedBody(request, signal) {
  const reader=request.body?.getReader();
  if (!reader) return new Uint8Array();
  const parts=[]; let size=0; let abort;
  const aborted=new Promise((_,reject)=>{abort=()=>reject(new DOMException('Aborted','AbortError'));signal.addEventListener('abort',abort,{once:true});});
  try {
    if (signal.aborted) throw new DOMException('Aborted','AbortError');
    while (true) {
      const {done,value}=await Promise.race([reader.read(),aborted]);
      if (done) break;
      size+=value.length;
      if (size>524288) return null;
      parts.push(value);
    }
    const body=new Uint8Array(size);let offset=0;
    for (const part of parts) {body.set(part,offset);offset+=part.length;}
    return body;
  } finally {signal.removeEventListener('abort',abort);void reader.cancel().catch(()=>{});}
}
export const pageAssetPath = path => PAGE_PATHS.get(path) || (/^\/opportunities\/[1-9]\d*$/.test(path) ? '/frontend/pages/detail.html' : path);
const SECURITY = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'",
  'Cache-Control': 'no-store',
};

function jsonError(status, code, message, diagnostic) {
  const body = {error: {code, message}, ...(diagnostic ? {diagnostic} : {})};
  if (diagnostic) console.warn(JSON.stringify({event: 'workhunter_proxy_failure', code, ...diagnostic}));
  return new Response(JSON.stringify(body), {status, headers: {...SECURITY, 'Content-Type': 'application/json; charset=utf-8', ...(diagnostic ? {'X-Request-ID': diagnostic.request_id} : {})}});
}

function mediaType(value) {
  const type = (value || '').split(';', 1)[0].trim().toLowerCase();
  if (!type) return 'missing';
  if (type === 'application/json' || /^application\/[a-z0-9.-]+\+json$/.test(type)) return 'application/json';
  return ['text/html', 'text/plain', 'application/octet-stream'].includes(type) ? type : 'other';
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const api = isPublicPath(url.pathname);
    const admin=adminRoute(url.pathname,request.method);
    if (url.pathname.startsWith('/api/') && !api && !admin) return jsonError(404, 'route_not_available', '该入口尚未开放。');
    if (api || admin) {
      if (!admin && request.method !== 'GET') return jsonError(405, 'read_only', '此入口只提供读取。');
      if (url.search.length > 4096) return jsonError(414, 'query_too_large', '查询条件过长。');
      const incomingOrigin=request.headers.get('origin');
      const cookie=admin ? maintenanceCookie(request.headers.get('cookie')) : '';
      if (admin) {
        if (cookie===null) return jsonError(401,'maintenance_unauthorized','维护会话无效，请重新登录。');
        if (incomingOrigin && incomingOrigin!==url.origin || request.method==='POST' && incomingOrigin!==url.origin) return jsonError(403,'maintenance_origin','维护请求必须来自当前页面。');
        if (request.method==='POST' && !/^[A-Za-z0-9_-]{43}$/.test(request.headers.get('x-wh-csrf')||'')) return jsonError(403,'maintenance_csrf','维护校验已失效，请重新打开维护页。');
        const allowed = url.pathname==='/api/admin/session' || request.method==='POST' ? [] : url.pathname.includes('/opportunities/') ? ['environment'] : ['environment','limit','before'];
        const keys=[...url.searchParams.keys()];
        if (keys.length!==new Set(keys).size || keys.some(key=>!allowed.includes(key))) return jsonError(422,'maintenance_input','维护查询参数无效。');
        if (request.method==='POST' && (mediaType(request.headers.get('content-type'))!=='application/json' || Number(request.headers.get('content-length')||0)>524288)) return jsonError(413,'maintenance_body_size','维护输入格式或长度无效。');
      }
      const diagnostic = {request_id: crypto.randomUUID(), path: admin ? '/api/admin/{route}' : PUBLIC_PATHS.has(url.pathname) ? url.pathname : '/api/opportunities/{id}', layer: 'configuration', upstream_status: null, content_type: null};
      const fail = (status, code, message) => jsonError(status, code, message, diagnostic);
      let origin;
      try {
        origin = new URL(env.WH_API_ORIGIN);
        if (origin.protocol !== 'https:' || origin.username || origin.password || origin.port || origin.pathname !== '/' || origin.search || origin.hash || !/^[a-z0-9-]+\.trycloudflare\.com$/.test(origin.hostname)) throw new Error('Invalid fixed development origin');
        if (typeof env.WH_API_SERVICE_TOKEN !== 'string' || !env.WH_API_SERVICE_TOKEN.trim() || /[\r\n]/.test(env.WH_API_SERVICE_TOKEN)) throw new Error();
      } catch {
        return fail(503, 'development_api_unconfigured', '开发环境尚未连接，请稍后重新加载。');
      }
      const target = new URL(url.pathname + url.search, origin);
      const controller = new AbortController();
      let clientAborted = false;
      const abortClient = () => { clientAborted = true; controller.abort(); };
      if (request.signal.aborted) abortClient();
      request.signal.addEventListener('abort', abortClient, {once: true});
      const timeout = setTimeout(() => controller.abort(), 12000);
      const started = performance.now();
      let headersAt;
      let reader;
      try {
        diagnostic.layer = 'upstream_connect';
        const upstreamHeaders={'Accept':'application/json','Authorization':`Bearer ${env.WH_API_SERVICE_TOKEN}`};
        let input;
        if (admin) {
          if (cookie) upstreamHeaders.Cookie=cookie;
          if (incomingOrigin) upstreamHeaders.Origin=incomingOrigin;
          if (request.method==='POST') {
            upstreamHeaders['X-WH-CSRF']=request.headers.get('x-wh-csrf');upstreamHeaders['Content-Type']='application/json';
            input=await boundedBody(request,controller.signal);
            if (input===null) return fail(413,'maintenance_body_size','维护输入超过允许长度。');
          }
        }
        const response = await fetch(target, {
          method: request.method, redirect: 'manual', signal: controller.signal,
          headers:upstreamHeaders, ...(input ? {body:input} : {}),
        });
        headersAt = performance.now();
        if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
        diagnostic.layer = 'upstream_headers';
        diagnostic.upstream_status = response.status;
        diagnostic.content_type = mediaType(response.headers.get('content-type'));
        if (response.status >= 300 && response.status < 400) return fail(502, 'upstream_redirect', '数据连接返回了跳转，请重新加载。');
        if (diagnostic.content_type !== 'application/json') return fail(502, 'upstream_non_json', '数据连接未返回可读数据，请重新加载。');
        if (Number(response.headers.get('content-length') || 0) > MAX_BYTES) return fail(502, 'response_too_large', '返回内容超过本次读取上限。');
        diagnostic.layer = 'upstream_body';
        reader = response.body?.getReader();
        const chunks = [];
        let size = 0;
        while (reader) {
          const {done, value} = await reader.read();
          if (done) break;
          size += value.length;
          if (size > MAX_BYTES) return fail(502, 'response_too_large', '返回内容超过本次读取上限。');
          chunks.push(value);
        }
        const body = new Uint8Array(size);
        let cursor = 0;
        for (const chunk of chunks) {body.set(chunk, cursor); cursor += chunk.length;}
        if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
        let data;
        try { data = JSON.parse(new TextDecoder().decode(body)); }
        catch { return fail(502, 'upstream_invalid_json', '数据连接返回内容不完整，请重新加载。'); }
        if (!response.ok) {
          diagnostic.layer = 'upstream_api';
          const supplied = data?.detail?.code || data?.error?.code;
          const code = API_CODES.has(supplied) || admin && ADMIN_CODES.has(supplied) ? supplied : 'upstream_http_error';
          const message = code === 'service_unauthorized' ? '数据连接授权配置需要检查，请稍后重新加载。'
            : code === 'database_unavailable' ? '开发数据暂不可读，请稍后重新加载。'
            : response.status === 409 ? '数据版本已改变，请重新加载。'
            : response.status === 422 ? '读取条件暂不可用，请检查筛选后重新加载。'
            : '开发数据读取失败，请稍后重新加载。';
          return fail(response.status, code, message);
        }
        const finished = performance.now();
        const timings = [
          `proxy_connect;dur=${(headersAt - started).toFixed(3)}`,
          `proxy_body;dur=${(finished - headersAt).toFixed(3)}`,
          `proxy_total;dur=${(finished - started).toFixed(3)}`,
        ];
        const apiTiming = /(?:^|,)\s*api;dur=(\d+(?:\.\d+)?)\s*(?:,|$)/.exec(response.headers.get('server-timing') || '');
        if (apiTiming && Number(apiTiming[1]) <= 60000) timings.unshift(`api;dur=${apiTiming[1]}`);
        const headers = {...SECURITY, 'Content-Type': 'application/json; charset=utf-8', 'X-Request-ID': diagnostic.request_id, 'Server-Timing': timings.join(', ')};
        if (admin) {
          const cookie=responseCookie(response.headers.get('set-cookie'));
          if (cookie) headers['Set-Cookie']=cookie;
        }
        for (const name of ['X-WH-API-Started', 'X-WH-API-Ended']) {
          const stamp = response.headers.get(name + '-At') || response.headers.get(name);
          if (/^\d{13}$/.test(stamp || '')) headers[name] = stamp;
        }
        return new Response(body, {status: response.status, headers});
      } catch {
        if (clientAborted) return jsonError(499, 'request_cancelled', '本次查询已取消。');
        return fail(controller.signal.aborted ? 504 : 502, controller.signal.aborted ? 'development_api_timeout' : 'development_api_unavailable', controller.signal.aborted ? '连接开发环境超时，请重新加载。' : '暂时无法连接开发环境，请重新加载。');
      } finally {
        clearTimeout(timeout);
        request.signal.removeEventListener('abort', abortClient);
        if (reader) { try { void reader.cancel().catch(() => {}); } catch {} }
      }
    }
    if (!['GET', 'HEAD'].includes(request.method)) return jsonError(405, 'read_only', '当前阶段只提供读取。');
    const asset = ASSETS[pageAssetPath(url.pathname)];
    if (!asset) return new Response('页面不存在。', {status: 404, headers: SECURITY});
    return new Response(request.method === 'HEAD' ? null : asset.body, {headers: {...SECURITY, 'Content-Type': asset.type, 'ETag': `"${asset.hash}"`}});
  },
};
