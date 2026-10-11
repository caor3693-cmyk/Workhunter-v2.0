// Thin transport only: business facts remain in the Python service.
const ASSETS = __EMBEDDED_ASSETS__;
const PUBLIC_PATHS = new Set(['/health', '/version', '/api/catalog', '/api/opportunities', '/api/updates/summary', '/api/sources/status']);
const MAX_BYTES = 1048576;
export const isPublicPath = path => PUBLIC_PATHS.has(path) || /^\/api\/opportunities\/[1-9]\d*$/.test(path);
const SECURITY = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'",
  'Cache-Control': 'no-store',
};

function jsonError(status, code, message) {
  return new Response(JSON.stringify({error: {code, message}}), {status, headers: {...SECURITY, 'Content-Type': 'application/json; charset=utf-8'}});
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const api = isPublicPath(url.pathname);
    if (url.pathname.startsWith('/api/') && !api) return jsonError(404, 'route_not_available', '该入口尚未开放。');
    if (api) {
      if (request.method !== 'GET') return jsonError(405, 'read_only', '当前阶段只提供读取。');
      if (url.search.length > 4096) return jsonError(414, 'query_too_large', '查询条件过长。');
      let origin;
      try {
        origin = new URL(env.WH_API_ORIGIN);
        if (origin.protocol !== 'https:' || origin.username || origin.password || origin.port || origin.pathname !== '/' || origin.search || origin.hash || !/^[a-z0-9-]+\.trycloudflare\.com$/.test(origin.hostname)) throw new Error('Invalid fixed development origin');
        if (!env.WH_API_SERVICE_TOKEN) throw new Error('Missing service credential');
      } catch {
        return jsonError(503, 'development_api_unconfigured', '开发环境尚未连接，请稍后重新加载。');
      }
      const target = new URL(url.pathname + url.search, origin);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12000);
      try {
        const response = await fetch(target, {
          method: 'GET', redirect: 'manual', signal: controller.signal,
          headers: {'Accept': 'application/json', 'Authorization': `Bearer ${env.WH_API_SERVICE_TOKEN}`},
        });
        if (response.status >= 300 && response.status < 400) return jsonError(502, 'upstream_redirect', '开发环境响应异常，请重新加载。');
        if (!response.headers.get('content-type')?.includes('application/json')) return jsonError(502, 'upstream_unavailable', '暂时无法连接开发环境，请重新加载。');
        if (Number(response.headers.get('content-length') || 0) > MAX_BYTES) return jsonError(502, 'response_too_large', '返回内容超过本次读取上限。');
        const reader = response.body?.getReader();
        const chunks = [];
        let size = 0;
        while (reader) {
          const {done, value} = await reader.read();
          if (done) break;
          size += value.length;
          if (size > MAX_BYTES) { await reader.cancel(); return jsonError(502, 'response_too_large', '返回内容超过本次读取上限。'); }
          chunks.push(value);
        }
        const body = new Uint8Array(size);
        let cursor = 0;
        for (const chunk of chunks) {body.set(chunk, cursor); cursor += chunk.length;}
        return new Response(body, {status: response.status, headers: {...SECURITY, 'Content-Type': 'application/json; charset=utf-8'}});
      } catch {
        return jsonError(controller.signal.aborted ? 504 : 502, controller.signal.aborted ? 'development_api_timeout' : 'development_api_unavailable', controller.signal.aborted ? '连接开发环境超时，请重新加载。' : '暂时无法连接开发环境，请重新加载。');
      } finally { clearTimeout(timeout); }
    }
    if (!['GET', 'HEAD'].includes(request.method)) return jsonError(405, 'read_only', '当前阶段只提供读取。');
    const assetPath = url.pathname === '/' ? '/index.html' : url.pathname;
    const asset = ASSETS[assetPath];
    if (!asset) return new Response('页面不存在。', {status: 404, headers: SECURITY});
    return new Response(request.method === 'HEAD' ? null : asset.body, {headers: {...SECURITY, 'Content-Type': asset.type, 'ETag': `"${asset.hash}"`}});
  },
};
