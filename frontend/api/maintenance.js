import { opportunityPath } from '../components/dom.js';

const environments = new Set(['real', 'isolated']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const hex = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const operation = value => typeof value === 'string' && /^[A-Za-z0-9:_-]{1,160}$/.test(value);
const date = value => typeof value === 'string' && !Number.isNaN(Date.parse(value));
const integer = value => Number.isSafeInteger(value) && value >= 0;

export class MaintenanceError extends Error {
  constructor(message, status = 0, code = 'maintenance_connection_failed') {
    super(message); this.name = 'MaintenanceError'; this.status = status; this.code = code;
  }
}

function invalid(message = '维护数据与当前接口不一致，请重新读取。') {
  throw new MaintenanceError(message, 0, 'maintenance_invalid_contract');
}
function environment(value) {
  if (!environments.has(value)) invalid('请选择真实维护或隔离演练环境。');
  return value;
}
function operationPath(id) {
  if (!operation(id)) invalid('操作编号无效。');
  return `/api/admin/operations/${id}`;
}
function taskPath(id) {
  const path = opportunityPath(id, '/api/admin/tasks/');
  if (!path) invalid('待办编号无效。');
  return path;
}
function errorMessage(status, data) {
  const code = errorCode(data);
  const messages = {
    maintenance_unauthorized: '维护登录已失效，请重新登录。',
    maintenance_origin: '请求来源校验失败，请从本次维护页面重试。',
    maintenance_csrf: '登录校验已失效，请重新读取登录状态。',
    maintenance_unavailable: '维护登录尚未配置，请联系维护者。',
    maintenance_login_failed: '登录未成功，请检查口令或稍后重试。',
    maintenance_isolation_unavailable: '隔离演练库尚未配置，请联系维护者。',
    maintenance_busy: '另一项写入正在提交，请稍后重试。',
    database_unavailable: '维护数据暂不可读，请稍后重试。',
    development_api_unconfigured: '开发环境尚未连接，请稍后重试。',
    development_api_unavailable: '暂时无法连接开发数据，请稍后重试。',
    development_api_timeout: '数据连接超时，请重新读取确认结果。',
  };
  if (messages[code]) return messages[code];
  const text = data?.detail?.message ?? data?.error?.message;
  if (typeof text === 'string' && text.length <= 2000 && !/[\u0000-\u0008]/.test(text)) return text;
  if (status === 409) return '目标或预览已变化，请重新核对预览。';
  if (status === 401) return '请先登录维护页面。';
  if (status === 403) return '维护权限或请求校验失败，请重新读取登录状态。';
  if (status === 413) return '材料超过允许大小，请缩减后重试。';
  if (status === 422) return '维护输入无效，请核对材料和操作原因。';
  if (status >= 500) return '维护服务暂不可用，请稍后重试。';
  return '维护请求未成功，请重新读取确认结果。';
}

function errorCode(data) {
  for (const value of [data?.detail?.code, data?.error?.code]) {
    if (typeof value === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(value)) return value;
  }
  return 'maintenance_http_error';
}

function validate(kind, data, env) {
  let valid = object(data);
  if (kind === 'session' || kind === 'login') valid &&= typeof data.authenticated === 'boolean' && typeof data.csrf_token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(data.csrf_token) && date(data.expires_at)
    && (!data.authenticated || (typeof data.actor === 'string' && !!data.actor));
  if (kind === 'login') valid &&= data.authenticated === true;
  if (kind === 'logout') valid &&= data.authenticated === false;
  if (kind === 'preview') valid &&= data.environment === env && operation(data.operation_id) && hex(data.preview_hash) && hex(data.input_hash)
    && integer(data.base_version) && date(data.expires_at) && object(data.target) && object(data.differences)
    && (object(data.candidate) || data.candidate === null) && typeof data.visible === 'boolean';
  if (kind === 'receipt') valid &&= data.environment === env && operation(data.operation_id) && integer(data.new) && integer(data.modified) && integer(data.unchanged)
    && Array.isArray(data.opportunity_ids) && typeof data.dataset_id === 'string' && !!data.dataset_id && integer(data.version) && typeof data.visible === 'boolean' && date(data.committed_at);
  if (kind === 'operations' || kind === 'tasks') valid &&= data.environment === env && Array.isArray(data.items) && typeof data.has_more === 'boolean'
    && (data.next_cursor === null || (kind === 'operations' ? operation(data.next_cursor) : !!opportunityPath(data.next_cursor)));
  if (kind === 'history') valid &&= data.environment === env && !!opportunityPath(data.id) && typeof data.title === 'string' && Array.isArray(data.history) && typeof data.visible === 'boolean';
  if (!valid) invalid();
  return data;
}

export function previewBinding(preview) {
  if (!object(preview) || !operation(preview.operation_id) || !hex(preview.preview_hash) || !hex(preview.input_hash) || !integer(preview.base_version)) invalid('缺少完整预览，请重新预览。');
  return { environment: environment(preview.environment), operation_id: preview.operation_id, preview_hash: preview.preview_hash, input_hash: preview.input_hash, base_version: preview.base_version };
}

export function createMaintenanceAPI({ fetch: request = globalThis.fetch, timeout = 30000 } = {}) {
  async function call(path, { method = 'GET', body, csrf, kind, env } = {}) {
    if (method === 'POST' && (typeof csrf !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(csrf))) throw new MaintenanceError('请重新读取登录状态。', 403, 'maintenance_csrf');
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
    const headers = { Accept: 'application/json' };
    if (method === 'POST') { headers['Content-Type'] = 'application/json'; headers['X-WH-CSRF'] = csrf; }
    try {
      const response = await request(path, { method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers, signal: controller.signal,
        ...(method === 'POST' ? { body: JSON.stringify(body ?? {}) } : {}) });
      let data;
      try { data = await response.json(); } catch { throw new MaintenanceError('维护响应未完整取得，请重新读取确认结果。', response.status, 'maintenance_invalid_response'); }
      if (!response.ok) {
        throw new MaintenanceError(errorMessage(response.status, data), response.status, errorCode(data));
      }
      return validate(kind, data, env);
    } catch (error) {
      if (error instanceof MaintenanceError) throw error;
      throw new MaintenanceError(timedOut ? '维护连接超时，操作结果尚未确认。' : '维护连接失败，操作结果尚未确认。', 0, timedOut ? 'maintenance_timeout' : 'maintenance_connection_failed');
    } finally { clearTimeout(timer); }
  }
  const listPath = (name, env, before) => {
    const params = new URLSearchParams({ environment: environment(env), limit: '20' });
    if (before !== undefined && before !== null) {
      if (name === 'operations' ? !operation(before) : !opportunityPath(before)) invalid('分页编号无效。');
      params.set('before', String(before));
    }
    return `/api/admin/${name}?${params}`;
  };
  return {
    session: () => call('/api/admin/session', { kind: 'session' }),
    login: (password, csrf) => call('/api/admin/session/login', { method: 'POST', body: { password }, csrf, kind: 'login' }),
    logout: csrf => call('/api/admin/session/logout', { method: 'POST', csrf, kind: 'logout' }),
    operations: (env, before) => call(listPath('operations', env, before), { kind: 'operations', env }),
    tasks: (env, before) => call(listPath('tasks', env, before), { kind: 'tasks', env }),
    history: (id, env) => {
      const path = opportunityPath(id, '/api/admin/opportunities/');
      if (!path) invalid('记录编号无效。');
      return call(`${path}/history?${new URLSearchParams({ environment: environment(env) })}`, { kind: 'history', env });
    },
    preview: (payload, csrf) => call('/api/admin/materials/preview', { method: 'POST', body: payload, csrf, kind: 'preview', env: environment(payload.environment) }),
    retryPreview: (id, env, reason, csrf) => call(`${taskPath(id)}/retry-preview`, { method: 'POST', body: { environment: environment(env), reason }, csrf, kind: 'preview', env }),
    revertPreview: (id, env, reason, csrf) => call(`${operationPath(id)}/revert-preview`, { method: 'POST', body: { environment: environment(env), reason }, csrf, kind: 'preview', env }),
    commit: (preview, csrf, originalId) => call(originalId ? `${operationPath(originalId)}/revert` : '/api/admin/operations/commit',
      { method: 'POST', body: previewBinding(preview), csrf, kind: 'receipt', env: preview.environment }),
  };
}
