export function datasetConsistency(state, { includeDataset = true } = {}) {
  const displayed = Object.values(state).map(resource => resource.data).filter(Boolean);
  return [...(includeDataset ? ['dataset_id'] : []), 'data_mode', 'project', 'backend_commit', 'build_id', 'version'].every(key =>
    new Set(displayed.map(data => data[key]).filter(value => value !== undefined)).size <= 1);
}

const DRAFT_KEYS = ['school_key', 'campus_id', 'campus_unknown', 'kind', 'keyword', 'date_from', 'date_to'];
const DEFAULTS = { view: 'recent', scope: 'electrical' };
export function normalizeFilters(filters = {}) {
  const result = { ...DEFAULTS };
  for (const key of [...DRAFT_KEYS, 'view', 'scope']) {
    const value = filters[key];
    if (key === 'campus_unknown') { if (value === true || value === 'true') result[key] = true; }
    else if (value !== undefined && value !== null && String(value).trim()) result[key] = String(value).trim();
  }
  return result;
}
function sameFilters(a, b) {
  return JSON.stringify(Object.entries(normalizeFilters(a)).sort()) === JSON.stringify(Object.entries(normalizeFilters(b)).sort());
}
export function queryPath(filters, offset = 0, snapshot = null, limit = 20) {
  const parameters = new URLSearchParams({ ...normalizeFilters(filters), offset: String(offset), limit: String(limit) });
  if (offset > 0) {
    if (!snapshot?.dataset_id || !snapshot?.as_of) throw new Error('分页缺少首页数据版本或查询日期。');
    parameters.set('dataset_id', snapshot.dataset_id);
    parameters.set('as_of', snapshot.as_of);
  }
  return `/api/opportunities?${parameters}`;
}

// The request owns every asynchronous continuation, including a 409 recovery.
export function createQueryState(read, onChange = () => {}, { limit = 20, onTiming } = {}) {
  const state = { draft: {}, applied: { ...DEFAULTS }, displayed: null, page: 0, dataset: null, as_of: null,
    generation: 0, status: 'idle', data: null, error: null, observedAt: null, recovering: false };
  let controller, destroyed = false;
  const emit = () => { if (!destroyed) onChange(state); };
  const current = (generation, active) => !destroyed && state.generation === generation && controller === active && !active.signal.aborted;
  function editDraft(patch, { validCampusIds } = {}) {
    const previousSchool = state.draft.school_key;
    state.draft = Object.fromEntries(Object.entries({ ...state.draft, ...patch }).filter(([key]) => DRAFT_KEYS.includes(key)));
    if (previousSchool !== state.draft.school_key) {
      delete state.draft.campus_id;
      delete state.draft.campus_unknown;
      controller?.abort();
      controller = null;
      state.generation++;
      state.status = state.data ? 'stale' : 'idle';
      state.error = null;
      state.recovering = false;
    } else if (state.draft.campus_id && validCampusIds && !validCampusIds.map(String).includes(String(state.draft.campus_id))) delete state.draft.campus_id;
    emit();
  }
  async function query(filters = state.applied, offset = 0, { action = 'query', operationAt = Date.now() } = {}) {
    controller?.abort();
    const active = new AbortController();
    controller = active;
    const generation = ++state.generation;
    const timing = event => {
      if (typeof onTiming !== 'function') return;
      try { onTiming({ generation, action, at: Date.now(), ...event }); } catch { /* Observability never owns query state. */ }
    };
    const applied = normalizeFilters(filters);
    const snapshot = state.displayed && sameFilters(state.displayed.filters, applied) ? state.displayed : null;
    // A changed query always starts at its own first page.
    offset = snapshot ? offset : 0;
    state.applied = applied;
    state.status = 'loading';
    state.error = null;
    state.recovering = false;
    timing({ phase: 'operation', at: operationAt, filters: applied, offset });
    emit();
    try {
      let data;
      try { data = await read(queryPath(applied, offset, snapshot, limit), { signal: active.signal, onTiming: timing }); }
      catch (error) {
        if (!current(generation, active)) return;
        if (error.code !== 'dataset_changed' || offset === 0) throw error;
        // Do not retain a page from a dataset that explicitly became invalid.
        state.data = null; state.displayed = null; state.dataset = null; state.as_of = null; state.page = 0;
        state.recovering = true;
        timing({ phase: 'recovery' });
        emit();
        offset = 0;
        data = await read(queryPath(applied, 0, null, limit), { signal: active.signal, onTiming: timing });
      }
      if (!current(generation, active)) return;
      if (!sameFilters(data.applied_filters, applied)) throw new Error('服务返回的查询范围与已提交条件不一致，请重新加载。');
      if (data.offset !== offset || data.limit !== limit) throw new Error('服务返回的分页范围不一致，请重新加载。');
      if (offset > 0 && (data.dataset_id !== snapshot.dataset_id || data.as_of !== snapshot.as_of)) throw new Error('分页数据身份或查询日期改变，保留上次结果，请重新加载。');
      state.data = data;
      state.displayed = { filters: { ...data.applied_filters }, dataset_id: data.dataset_id, as_of: data.as_of, offset: data.offset, limit: data.limit };
      state.page = data.offset;
      state.dataset = data.dataset_id;
      state.as_of = data.as_of;
      state.status = 'ready';
      state.observedAt = new Date().toISOString();
      timing({ phase: 'accepted', dataset_id: data.dataset_id, data_mode: data.data_mode, backend_commit: data.backend_commit || null,
        build_id: data.build_id || null, version: data.version || null, filters: data.applied_filters, total: data.total, item_count: data.items.length, offset: data.offset });
    } catch (error) {
      if (!current(generation, active)) return;
      state.status = 'error';
      state.error = error;
      timing({ phase: 'error', code: error.code || 'query_failed' });
    } finally {
      if (current(generation, active)) { state.recovering = false; controller = null; emit(); }
      else timing({ phase: 'discarded' });
    }
  }
  const canPage = () => state.status !== 'loading' && Boolean(state.displayed) && sameFilters(state.displayed.filters, state.applied);
  return { state, editDraft, query, canPage,
    submit: options => query({ ...state.draft, view: state.applied.view, scope: state.applied.scope }, 0, { action: 'submit', ...options }),
    clear(options) { state.draft = {}; emit(); return query({ view: state.applied.view, scope: state.applied.scope }, 0, { action: 'clear', ...options }); },
    setView: (view, options) => query({ ...state.applied, view }, 0, { action: 'view', ...options }),
    setScope: (scope, options) => query({ ...state.applied, scope }, 0, { action: 'scope', ...options }),
    page(offset, options) { return canPage() ? query(state.applied, Math.max(0, offset), { action: 'page', ...options }) : Promise.resolve(); },
    reload: options => query(state.applied, state.displayed && sameFilters(state.displayed.filters, state.applied) ? state.page : 0, { action: 'reload', ...options }),
    destroy() { destroyed = true; controller?.abort(); controller = null; state.generation++; },
  };
}
