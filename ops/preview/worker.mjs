// Thin transport only: business facts remain in the Python service.
const ASSETS = __EMBEDDED_ASSETS__;
const PUBLIC_PATHS = new Set(['/health', '/version', '/api/catalog', '/api/opportunities', '/api/updates/summary', '/api/sources/status']);
const PAGE_PATHS = new Map([['/', '/index.html'], ['/sources', '/frontend/pages/sources.html'], ['/review', '/frontend/pages/review.html']]);
const MAX_BYTES = 1048576;
const API_CODES = new Set(['service_unauthorized', 'loopback_only', 'database_unavailable', 'dataset_changed', 'dataset_required', 'unsupported_parameter', 'duplicate_parameter', 'invalid_date', 'invalid_date_range', 'invalid_kind', 'invalid_view_or_scope', 'invalid_number', 'invalid_campus_unknown', 'campus_conflict', 'school_not_found', 'campus_not_found', 'school_campus_conflict', 'invalid_opportunity', 'opportunity_not_found']);
export const isPublicPath = path => PUBLIC_PATHS.has(path) || /^\/api\/opportunities\/[1-9]\d*$/.test(path);
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
    if (url.pathname.startsWith('/api/') && !api) return jsonError(404, 'route_not_available', '该入口尚未开放。');
    if (api) {
      if (request.method !== 'GET') return jsonError(405, 'read_only', '当前阶段只提供读取。');
      if (url.search.length > 4096) return jsonError(414, 'query_too_large', '查询条件过长。');
      const diagnostic = {request_id: crypto.randomUUID(), path: PUBLIC_PATHS.has(url.pathname) ? url.pathname : '/api/opportunities/{id}', layer: 'configuration', upstream_status: null, content_type: null};
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
      const timeout = setTimeout(() => controller.abort(), 12000);
      let reader;
      try {
        diagnostic.layer = 'upstream_connect';
        const response = await fetch(target, {
          method: 'GET', redirect: 'manual', signal: controller.signal,
          headers: {'Accept': 'application/json', 'Authorization': `Bearer ${env.WH_API_SERVICE_TOKEN}`},
        });
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
          const code = API_CODES.has(supplied) ? supplied : 'upstream_http_error';
          const message = code === 'service_unauthorized' ? '数据连接授权配置需要检查，请稍后重新加载。'
            : code === 'database_unavailable' ? '开发数据暂不可读，请稍后重新加载。'
            : response.status === 409 ? '数据版本已改变，请重新加载。'
            : response.status === 422 ? '读取条件暂不可用，请检查筛选后重新加载。'
            : '开发数据读取失败，请稍后重新加载。';
          return fail(response.status, code, message);
        }
        return new Response(body, {status: response.status, headers: {...SECURITY, 'Content-Type': 'application/json; charset=utf-8', 'X-Request-ID': diagnostic.request_id}});
      } catch {
        return fail(controller.signal.aborted ? 504 : 502, controller.signal.aborted ? 'development_api_timeout' : 'development_api_unavailable', controller.signal.aborted ? '连接开发环境超时，请重新加载。' : '暂时无法连接开发环境，请重新加载。');
      } finally {
        clearTimeout(timeout);
        if (reader) { try { void reader.cancel().catch(() => {}); } catch {} }
      }
    }
    if (!['GET', 'HEAD'].includes(request.method)) return jsonError(405, 'read_only', '当前阶段只提供读取。');
    const asset = ASSETS[pageAssetPath(url.pathname)];
    if (!asset) return new Response('页面不存在。', {status: 404, headers: SECURITY});
    return new Response(request.method === 'HEAD' ? null : asset.body, {headers: {...SECURITY, 'Content-Type': asset.type, 'ETag': `"${asset.hash}"`}});
  },
};
