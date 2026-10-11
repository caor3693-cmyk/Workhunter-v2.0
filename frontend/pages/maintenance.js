import { createMaintenanceAPI, MaintenanceError } from '../api/maintenance.js';
import { readJSON } from '../api/client.js';
import { displayTime, safePublicURL } from '../components/dom.js';

const FIELD_LABELS = { published_date: '公告发布时间', event_date: '活动日期', start_time: '开始时刻', end_time: '结束时刻', deadline: '投递截止', event_venue: '举办地点', work_locations: '工作地点', relevance: '电气相关性', title: '标题', kind: '招聘类型', original_kind: '原文类型', date_basis: '日期依据', campus_key: '校区', work_locations_scope: '工作地点范围', event_status: '活动状态', recruitment_status: '招聘状态', roster_fragments: '已取得名单片段', job_fragments: '已取得岗位片段', attachments: '适用附件', __visibility__: '访客可见' };
const OPERATION_LABELS = { manual_supplement: '人工补录', manual_correction: '人工纠错', manual_revert: '撤回更正', manual_withdrawal: '撤回人工可见贡献', semantic_revision: '事实修订' };
const STATUS_LABELS = { preview: '待确认预览', committed: '已提交', pending: '待处理', failed: '失败待核查', partial: '部分取得', restricted: '路径受限', resolved: '已处理' };
const resource = () => ({ status: 'idle', data: null, error: null });
const draft = () => ({ operation_type: 'supplement', school_key: '', source_key: '', url: '', public_text: '', reason: '', opportunity_id: '', fields: [] });

export function createMaintenanceController({ api = createMaintenanceAPI(), read = readJSON, onChange = () => {} } = {}) {
  const state = { session: null, environment: 'isolated', draft: draft(), actionReason: '', busy: false, notice: '正在读取登录状态…', error: null, preview: null, receipt: null,
    resources: { catalog: resource(), operations: resource(), tasks: resource(), history: resource() } };
  let alive = true, epoch = 0;
  const pending = new Map(), sequences = new Map();
  const notify = () => { if (alive) onChange(state); };
  const signature = () => JSON.stringify({ environment: state.environment, draft: state.draft, actionReason: state.actionReason });
  function clearProtected() {
    epoch += 1; pending.clear(); state.preview = null; state.receipt = null;
    for (const name of ['operations', 'tasks', 'history']) state.resources[name] = resource();
  }
  function failure(error) {
    state.error = error instanceof Error ? error : new Error('本次维护请求未成功。');
    state.notice = state.error.message;
    if (error?.status === 409) state.preview = null;
    if (error?.status === 401 && error.code !== 'maintenance_login_failed') { state.session = null; clearProtected(); }
  }
  async function action(message, work) {
    if (!alive || state.busy) return null;
    state.busy = true; state.error = null; state.notice = message; notify();
    try { return await work(); }
    catch (error) { if (alive) failure(error); return null; }
    finally { state.busy = false; notify(); }
  }
  function authenticated() {
    if (!state.session?.authenticated) throw new MaintenanceError('请先登录维护页面。', 401, 'maintenance_unauthorized');
    return state.session.csrf_token;
  }
  function load(name, getter, { force = false } = {}) {
    if (!alive || !state.session?.authenticated) return Promise.resolve(null);
    const previous = pending.get(name);
    if (previous && !force) return previous.promise;
    const generation = epoch, sequence = (sequences.get(name) || 0) + 1;
    sequences.set(name, sequence);
    const item = state.resources[name]; item.status = 'loading'; item.error = null; notify();
    const promise = Promise.resolve().then(getter).then(data => {
      if (!alive || generation !== epoch || sequences.get(name) !== sequence) return null;
      item.data = data; item.status = 'ready'; notify(); return data;
    }).catch(error => {
      if (!alive || generation !== epoch || sequences.get(name) !== sequence) return null;
      item.status = 'error'; item.error = error;
      if (error?.status === 401) failure(error);
      notify(); return null;
    }).finally(() => { if (pending.get(name)?.sequence === sequence) pending.delete(name); });
    pending.set(name, { sequence, promise });
    return promise;
  }
  function refresh() {
    const env = state.environment;
    return Promise.all([load('catalog', () => read('/api/catalog')), load('operations', () => api.operations(env)), load('tasks', () => api.tasks(env))]);
  }
  function payload() {
    const value = state.draft;
    const result = { environment: state.environment, operation_type: value.operation_type, school_key: value.school_key, source_key: value.source_key, url: value.url.trim(), reason: value.reason.trim() };
    if (value.public_text.trim()) result.public_text = value.public_text;
    if (value.opportunity_id.trim()) {
      const target = Number(value.opportunity_id);
      if (!/^[1-9]\d*$/.test(value.opportunity_id) || !Number.isSafeInteger(target)) throw new MaintenanceError('目标记录编号必须为可识别的正整数。', 422, 'maintenance_target');
      result.opportunity_id = target;
    }
    if (value.operation_type === 'correction' && value.fields.length) result.fields = [...value.fields];
    return result;
  }
  function installPreview(data, originalId = null) {
    if (!alive) return;
    if (data.environment !== state.environment) throw new MaintenanceError('预览环境不同，请重新生成。', 409, 'maintenance_environment');
    state.preview = { data, originalId, signature: signature() };
    state.receipt = null; state.resources.history = resource();
    state.notice = '已取得服务端预览。请核对差异，再点击确认保存。';
  }
  const controller = {
    state,
    start: () => controller.reloadSession(),
    reloadSession: () => action('正在核对登录状态…', async () => {
      try {
        const session = await api.session();
        if (!alive) return null;
        clearProtected(); state.session = session;
        state.notice = session.authenticated ? `已登录：${session.actor}` : '请使用维护口令登录。';
        if (session.authenticated) await refresh();
        return session;
      } catch (error) { state.session = null; clearProtected(); throw error; }
    }),
    login: password => action('正在校验维护口令…', async () => {
      if (!state.session?.csrf_token) throw new MaintenanceError('请先重新读取登录状态。', 403, 'maintenance_csrf');
      const session = await api.login(password, state.session.csrf_token);
      if (!alive) return null;
      clearProtected(); state.session = session; state.notice = `已登录：${session.actor}`;
      await refresh(); return session;
    }),
    logout: () => action('正在退出维护登录…', async () => {
      const csrf = authenticated(); state.session = null; clearProtected(); notify();
      try { await api.logout(csrf); }
      catch (error) { throw new MaintenanceError('退出结果未确认，请重新读取登录状态。', error.status, error.code); }
      if (!alive) return null;
      state.notice = '已退出维护登录。';
      state.session = await api.session(); return state.session;
    }),
    setEnvironment(value) {
      if (!alive || state.busy || !['real', 'isolated'].includes(value)) return false;
      if (state.environment === value) return true;
      clearProtected(); state.environment = value; state.error = null;
      state.notice = value === 'real' ? '已选择真实维护，请核对材料与保存差异。' : '已选择隔离演练，操作只写入演练库。';
      notify(); void refresh(); return true;
    },
    setDraft(patch) {
      if (!alive || state.busy) return false;
      const next = { ...state.draft };
      for (const [name, value] of Object.entries(patch)) {
        if (!(name in next) || (name === 'fields' ? !Array.isArray(value) : typeof value !== 'string')) continue;
        next[name] = name === 'fields' ? [...new Set(value)].sort() : value;
      }
      if (patch.school_key !== undefined && patch.school_key !== state.draft.school_key && patch.source_key === undefined) next.source_key = '';
      state.draft = next; state.preview = null; notify(); return true;
    },
    setActionReason(value) {
      if (!alive || state.busy) return false;
      state.actionReason = String(value); state.preview = null; notify(); return true;
    },
    preview: () => action('正在读取公开材料并生成预览…', async () => {
      const csrf = authenticated(), input = payload(); state.preview = null;
      const data = await api.preview(input, csrf); installPreview(data); return data;
    }),
    retryPreview: id => action('正在为本条待办生成重试预览…', async () => {
      const csrf = authenticated(); state.preview = null;
      const data = await api.retryPreview(id, state.environment, state.actionReason.trim(), csrf); installPreview(data); return data;
    }),
    revertPreview: id => action('正在核对撤回贡献并生成预览…', async () => {
      const csrf = authenticated(); state.preview = null;
      const data = await api.revertPreview(id, state.environment, state.actionReason.trim(), csrf); installPreview(data, id); return data;
    }),
    commit: () => action('正在保存已核对的预览…', async () => {
      const csrf = authenticated(), preview = state.preview;
      if (!preview || preview.signature !== signature() || preview.data.environment !== state.environment || Date.parse(preview.data.expires_at) <= Date.now()) {
        throw new MaintenanceError('预览已变化或过期，请重新生成。', 409, 'maintenance_conflict');
      }
      const receipt = await api.commit(preview.data, csrf, preview.originalId);
      if (!alive) return null;
      state.receipt = receipt; state.preview = null;
      state.notice = receipt.replayed ? '已读取同一操作的原提交回执，没有重复保存。' : '服务端已确认提交。';
      const id = receipt.opportunity_ids[0] ?? preview.data.target.opportunity_id;
      await Promise.all([refresh(), id ? controller.history(id) : Promise.resolve()]);
      return receipt;
    }),
    discard() { if (!alive || state.busy) return; state.preview = null; state.notice = '已放弃本次预览，业务事实未因此改变。'; notify(); },
    refresh,
    nextOperations: () => { const env = state.environment, cursor = state.resources.operations.data?.next_cursor; return load('operations', () => api.operations(env, cursor)); },
    nextTasks: () => { const env = state.environment, cursor = state.resources.tasks.data?.next_cursor; return load('tasks', () => api.tasks(env, cursor)); },
    history: id => { const env = state.environment; return load('history', () => api.history(id, env), { force: true }); },
    destroy() { alive = false; epoch += 1; pending.clear(); state.session = null; state.preview = null; state.receipt = null; },
  };
  return controller;
}

function valueText(value) {
  if (value === null || value === undefined || value === '') return '未知';
  if (value === true) return '是'; if (value === false) return '否';
  if (value === 'related') return '明确电气相关'; if (value === 'unknown') return '待核实'; if (value === 'unrelated') return '明确无关';
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'string' ? item : item.text || item.title || item.label || JSON.stringify(item)).join('；') : '尚未取得';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
function storedText(value) { try { return valueText(JSON.parse(value)); } catch { return valueText(value); } }
function resourceText(item, empty) {
  if (item.status === 'loading') return '正在读取…';
  if (item.status === 'error') return `${item.error?.message || '本次读取失败。'}${item.data ? ' 上次结果，尚未更新。' : ''}`;
  return item.data?.items?.length ? '' : empty;
}

export function mountMaintenance({ document: doc = globalThis.document, api = createMaintenanceAPI(), read = readJSON } = {}) {
  const get = id => doc.getElementById(id);
  function element(tag, { text, className, ...attributes } = {}, children = []) {
    const node = doc.createElement(tag); if (text !== undefined) node.textContent = String(text); if (className) node.className = className;
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    node.append(...children); return node;
  }
  const controller = createMaintenanceController({ api, read, onChange: render });
  const state = controller.state;
  const fieldInputs = [...doc.querySelectorAll('[data-maintenance-field]')];
  const controls = [...doc.querySelectorAll('[data-maintenance-control]')];
  const inputIds = { operation_type: 'maintenance-operation-type', school_key: 'maintenance-school', source_key: 'maintenance-source', url: 'maintenance-url', public_text: 'maintenance-public-text', reason: 'maintenance-reason', opportunity_id: 'maintenance-target' };
  function button(text, callback, attributes = {}) {
    const node = element('button', { text, type: 'button', className: 'button button-plain', ...attributes });
    node.disabled = state.busy; node.addEventListener('click', callback); return node;
  }
  function options(node, items, selected, prompt) {
    node.replaceChildren(element('option', { text: prompt, value: '' }), ...items.map(item => element('option', { text: item.name, value: item.key })));
    node.value = selected;
  }
  function sourceName(key) {
    for (const school of state.resources.catalog.data?.schools || []) {
      const source = school.sources?.find(item => item.source_key === key);
      if (source) return `${school.name} · ${source.name}`;
    }
    return key || '来源待核实';
  }
  function evidenceDetails(observation) {
    const proofs = observation?.evidence || [];
    if (!proofs.length) return null;
    return element('details', {}, [element('summary', { text: '本字段的材料依据' }), ...proofs.map(proof => element('p', { text: proof.excerpt || '本条适用材料' }))]);
  }
  function render() {
    const authenticated = !!state.session?.authenticated;
    get('maintenance-status').textContent = state.notice;
    get('maintenance-status').classList.toggle('is-error', !!state.error);
    get('maintenance-login').hidden = authenticated; get('maintenance-tools').hidden = !authenticated;
    for (const control of controls) control.disabled = state.busy;
    get('maintenance-login-button').disabled = state.busy || !state.session?.csrf_token;
    get('maintenance-environment').value = state.environment;
    get('maintenance-environment-note').textContent = state.environment === 'real' ? '真实维护：确认保存后，会改变真实招聘记录。' : '隔离演练：本页操作只写入独立演练库。';
    for (const [name, id] of Object.entries(inputIds)) if (get(id).value !== state.draft[name]) get(id).value = state.draft[name];
    for (const node of fieldInputs) { node.checked = state.draft.fields.includes(node.value); node.disabled = state.busy || state.draft.operation_type !== 'correction'; }
    get('maintenance-action-reason').value = state.actionReason;
    const catalog = state.resources.catalog;
    get('maintenance-catalog-status').textContent = catalog.status === 'error' ? `${catalog.error?.message || '学校与来源尚未取得。'}${catalog.data ? ' 上次目录，尚未更新。' : ''}` : catalog.data ? '请选择本条材料对应的学校与登记来源。' : '正在读取学校与登记来源…';
    const schools = catalog.data?.schools || [];
    options(get('maintenance-school'), schools.map(item => ({ key: item.school_key, name: item.name })), state.draft.school_key, '请选择学校');
    const sources = schools.find(item => item.school_key === state.draft.school_key)?.sources || [];
    options(get('maintenance-source'), sources.filter(item => item.channel_key !== 'homepage').map(item => ({ key: item.source_key, name: item.name })), state.draft.source_key, '请选择来源');
    get('maintenance-preview-button').disabled = state.busy || !authenticated || !catalog.data;
    const preview = state.preview?.data;
    get('maintenance-preview-panel').hidden = !preview;
    if (preview) {
      const expired = Date.parse(preview.expires_at) <= Date.now();
      get('maintenance-preview-note').textContent = `${state.environment === 'real' ? '真实维护' : '隔离演练'} · ${OPERATION_LABELS[preview.operation_type] || '维护操作'} · ${preview.candidate?.title || '本条贡献'} · ${expired ? '预览已过期，请重新生成' : `有效至 ${displayTime(preview.expires_at)}`}。`;
      const rows = Object.entries(preview.differences).map(([field, difference]) => element('article', { className: 'opportunity-card' }, [
        element('h3', { text: FIELD_LABELS[field] || field }), element('p', { text: `当前：${valueText(difference.before)}` }), element('p', { text: `保存后：${valueText(difference.after)}` }),
        ...(evidenceDetails(difference.after_observation) ? [evidenceDetails(difference.after_observation)] : []),
      ]));
      if (!rows.length) rows.push(element('p', { text: '当前没有需要改变的公开事实；请核对保留说明。' }));
      for (const warning of preview.warnings || []) rows.push(element('p', { text: warning, className: 'source-message' }));
      if (preview.retained_fields?.length) rows.push(element('p', { text: `保留后续贡献：${preview.retained_fields.map(field => FIELD_LABELS[field] || field).join('、')}` }));
      const url = safePublicURL(preview.candidate?.source_url);
      if (url) rows.push(element('a', { text: '核对官方原文', href: url, target: '_blank', rel: 'noopener noreferrer', className: 'original-link' }));
      get('maintenance-preview-content').replaceChildren(...rows);
      get('maintenance-commit').disabled = state.busy || expired || !authenticated;
      get('maintenance-commit').textContent = state.preview.originalId ? '确认撤回这次预览中的贡献' : '确认保存这次预览';
    } else get('maintenance-preview-content').replaceChildren();
    const receipt = state.receipt;
    get('maintenance-receipt-panel').hidden = !receipt;
    get('maintenance-receipt').textContent = receipt ? `${receipt.replayed ? '原提交回执' : '提交已确认'} · ${displayTime(receipt.committed_at)} · 新增 ${receipt.new} 条、修改 ${receipt.modified} 条、无变化 ${receipt.unchanged} 条。${receipt.visible ? '' : '本条人工可见贡献已撤回。'}操作编号：${receipt.operation_id}` : '';
    for (const name of ['operations', 'tasks']) {
      const item = state.resources[name];
      get(`maintenance-${name}-status`).textContent = resourceText(item, name === 'operations' ? '当前页没有操作记录。' : '当前页没有维护待办。');
      get(`maintenance-${name}-status`).classList.toggle('is-error', item.status === 'error');
      get(`maintenance-${name}-more`).hidden = !item.data?.has_more;
      get(`maintenance-${name}-more`).disabled = state.busy || item.status === 'loading';
    }
    get('maintenance-operations').replaceChildren(...(state.resources.operations.data?.items || []).map(item => {
      const children = [element('h3', { text: OPERATION_LABELS[item.operation_type] || '维护操作' }), element('p', { text: `${STATUS_LABELS[item.status] || item.status} · ${displayTime(item.committed_at)} · ${item.actor}` }), element('p', { text: item.reason || '原因尚未记录' })];
      if (item.opportunity_id) children.push(button('读取本条历史', () => { get('maintenance-history-id').value = String(item.opportunity_id); void controller.history(item.opportunity_id); }));
      if (item.status === 'committed' && ['manual_supplement', 'manual_correction'].includes(item.operation_type)) children.push(button('生成撤回预览', () => controller.revertPreview(item.operation_id), { 'data-revert-operation': item.operation_id }));
      if (item.materials?.length) children.push(element('details', {}, [element('summary', { text: '已归档材料依据' }), ...item.materials.map(material => element('p', { text: `${material.source_url || '本条材料'} · ${material.scope?.note || '保留原始材料与适用关联'}` }))]));
      return element('article', { className: 'opportunity-card' }, children);
    }));
    get('maintenance-tasks').replaceChildren(...(state.resources.tasks.data?.items || []).map(item => {
      const children = [element('h3', { text: sourceName(item.source_key) }), element('p', { text: `${STATUS_LABELS[item.status] || item.status} · 已尝试 ${item.attempts ?? 0} 次` })];
      if (item.status === 'restricted') children.push(element('p', { text: '受限路径已停止，请核查合法公开材料。' }));
      else if (item.opportunity_id) children.push(button('读取材料并生成重试预览', () => controller.retryPreview(item.id), { 'data-retry-task': item.id }));
      else children.push(element('p', { text: '此待办没有单条公告目标，请先检查来源入口。' }));
      return element('article', { className: 'opportunity-card' }, children);
    }));
    const history = state.resources.history;
    get('maintenance-history-status').textContent = history.status === 'error' ? `${history.error?.message || '历史读取失败。'}${history.data ? ' 上次结果，尚未更新。' : ''}` : history.status === 'loading' ? '正在读取本条记录与历史…' : '';
    const record = history.data;
    get('maintenance-history').replaceChildren(...(record ? [element('h3', { text: record.title }), element('p', { text: `记录 ${record.id} · 版本 ${record.version} · ${record.visible ? '访客可见' : '人工可见贡献已撤回'}` }),
      ...(record.history || []).map(item => element('article', { className: 'opportunity-card' }, [element('h3', { text: FIELD_LABELS[item.field_name] || '公告记录' }), element('p', { text: `${displayTime(item.committed_at)} · ${item.actor || '采集服务'} · ${item.reason || ''}` }), element('p', { text: `变更前：${storedText(item.before_json)}` }), element('p', { text: `变更后：${storedText(item.after_json)}` })]))] : []));
  }
  get('maintenance-login-form').addEventListener('submit', async event => { event.preventDefault(); const password = get('maintenance-password').value; try { await controller.login(password); } finally { get('maintenance-password').value = ''; } });
  get('session-reload').addEventListener('click', () => controller.reloadSession());
  get('maintenance-logout').addEventListener('click', () => controller.logout());
  get('maintenance-environment').addEventListener('change', event => controller.setEnvironment(event.target.value));
  for (const [name, id] of Object.entries(inputIds)) get(id).addEventListener(['operation_type', 'school_key', 'source_key'].includes(name) ? 'change' : 'input', event => controller.setDraft({ [name]: event.target.value }));
  for (const input of fieldInputs) input.addEventListener('change', () => controller.setDraft({ fields: fieldInputs.filter(node => node.checked).map(node => node.value) }));
  get('maintenance-action-reason').addEventListener('input', event => controller.setActionReason(event.target.value));
  get('maintenance-material-form').addEventListener('submit', event => { event.preventDefault(); void controller.preview(); });
  get('maintenance-commit').addEventListener('click', () => controller.commit());
  get('maintenance-discard').addEventListener('click', () => controller.discard());
  get('maintenance-refresh').addEventListener('click', () => controller.refresh());
  get('maintenance-operations-more').addEventListener('click', () => controller.nextOperations());
  get('maintenance-tasks-more').addEventListener('click', () => controller.nextTasks());
  get('maintenance-history-form').addEventListener('submit', event => { event.preventDefault(); void controller.history(get('maintenance-history-id').value); });
  render(); void controller.start();
  return controller;
}
