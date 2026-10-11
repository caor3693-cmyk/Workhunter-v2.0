import { readJSON } from "../api/client.js";
import { element } from "../components/dom.js";
import { resultCard } from "../components/cards.js";
import { createQueryState } from "../state/store.js";
import { PAGE_READ_PATHS } from "./routes.js";
import { createPageReader, pageDatasetsAgree, resourceMessage, renderNotice, setResourceStatus } from "./shared.js";

const EMPTY_RESULTS = {
  empty_database: ["尚未收录招聘", "当前新库没有招聘记录；这不代表学校没有招聘。"],
  school_not_collected: ["该校暂未收录", "该校当前没有入库记录，不能据此判断官方没有招聘。"],
  no_undated_matches: ["没有日期未知的记录", "当前条件下未找到日期未知的记录。"],
  no_matches: ["没有匹配结果", "可以调整条件，或查看其他日期视图。"],
};
const VIEW_LABELS = { recent: "近期", upcoming: "临近活动", history: "历史", undated: "日期未知" };
const KIND_LABELS = { campus_talk: "线下宣讲会", job_fair: "双选会 / 招聘会", online_recruitment: "线上招聘", announcement: "招聘公告" };

export function resultScopeText(filters, schools = []) {
  const school = schools.find(item => item.school_key === filters.school_key);
  const campus = school?.campuses?.find(item => String(item.id) === String(filters.campus_id));
  const parts = [filters.school_key ? school?.name || filters.school_key : "全部学校", VIEW_LABELS[filters.view] || "近期", filters.scope === "all" ? "全部招聘" : "电气相关与相关性未知"];
  if (filters.campus_unknown) parts.push("校区未知");
  else if (filters.campus_id) parts.push(campus?.name || "已选择校区");
  if (filters.kind) parts.push(KIND_LABELS[filters.kind] || "已选择招聘类型");
  if (filters.keyword) parts.push(`关键词：${filters.keyword}`);
  if (filters.date_from || filters.date_to) parts.push(`日期：${filters.date_from || "不限起始"} 至 ${filters.date_to || "不限结束"}`);
  if (filters.view === "recent" && filters.recent_window) {
    const window = filters.recent_window;
    parts.push(`公告 ${window.published_from} 至 ${window.published_to}，活动 ${window.events_from} 至 ${window.events_to}`);
  }
  if (filters.as_of) parts.push(`查询日期 ${filters.as_of}（北京时间）`);
  return parts.join(" · ");
}

export function mountHome({ document: doc = globalThis.document, read = readJSON, renderCard = resultCard } = {}) {
  const get = id => doc.getElementById(id);
  const form = get("search-form");
  const reader = createPageReader({ catalog: PAGE_READ_PATHS.home.catalog, updates: PAGE_READ_PATHS.home.updates }, render, read);
  const query = createQueryState(read, () => render("opportunities"));
  const state = query.state;
  const resources = reader.resources;
  resources.opportunities = state;
  form.hidden = false;
  get("query-navigation").hidden = false;

  function renderCampuses() {
    const school = resources.catalog.data?.schools.find(item => item.school_key === state.draft.school_key);
    const selected = state.draft.campus_unknown ? "__unknown__" : String(state.draft.campus_id || "");
    const campuses = school?.campuses || [];
    const options = [element("option", { value: "", text: "全部校区" }), ...campuses.map(campus => element("option", { value: campus.id, text: campus.name })), element("option", { value: "__unknown__", text: "校区未知" })];
    if (selected && selected !== "__unknown__" && !campuses.some(campus => String(campus.id) === selected)) options.push(element("option", { value: selected, text: "已填写校区（待核对）" }));
    get("campus-select").replaceChildren(...options);
    get("campus-select").value = selected;
  }
  function renderCatalog() {
    const resource = resources.catalog;
    const schools = resource.data?.schools || [];
    const selected = state.draft.school_key || "";
    const options = [element("option", { value: "", text: "全部学校" }), ...schools.map(school => element("option", { value: school.school_key, text: school.name }))];
    if (selected && !schools.some(school => school.school_key === selected)) options.push(element("option", { value: selected, text: `${selected}（目录待核对）` }));
    get("school-select").replaceChildren(...options);
    get("school-select").value = selected;
    renderCampuses();
    setResourceStatus(get("catalog-status"), resource, "正在读取学校目录…", `${schools.length} 所学校已登记 · 采集情况见来源状态`);
  }
  function renderUpdates() {
    const resource = resources.updates;
    get("new-count").textContent = resource.data?.today?.newly_collected ?? "—";
    get("change-count").textContent = resource.data?.today?.official_changes ?? "—";
    const parserCount = resource.data?.today?.parser_improvements;
    const conflictCount = resource.data?.today?.evidence_conflicts;
    const message = resource.data?.message || "检查情况暂不可确认。";
    setResourceStatus(get("update-message"), resource, "正在读取检查情况…", message + (parserCount !== undefined && parserCount !== null ? ` 解析补全 ${parserCount} 条，单独计算。` : "") + (conflictCount !== undefined && conflictCount !== null ? ` 材料冲突 ${conflictCount} 条待核实，单独计算。` : ""));
  }
  function renderResults() {
    const data = state.data;
    const panel = get("opportunity-status");
    const consistent = pageDatasetsAgree(resources);
    const stale = Boolean(data && (state.status !== "ready" || !consistent));
    const scope = state.displayed?.filters || state.applied;
    get("result-scope").textContent = resultScopeText(scope, resources.catalog.data?.schools);
    get("result-count").textContent = data ? `${data.total} 条结果${stale ? " · 上次结果，尚未更新" : ""}` : "";
    get("result-list").replaceChildren(...(data?.items || []).map(renderCard));
    let notice = resourceMessage(state);
    if (!consistent) notice += " 目录、摘要与招聘数据身份尚未一致，请重新加载核对。";
    if (!data) {
      const idle = state.status === 'idle';
      renderNotice(panel, state.status === "error" ? "招聘暂时不可读" : idle ? '等待查询' : "正在读取招聘…", state.recovering ? "数据版本已改变，正在按已提交条件重新读取第一页。" : state.status === "error" ? notice : idle ? '旧查询已停止，请提交当前条件后读取招聘。' : "读取完成后显示当前结果。", { loading: state.status === "loading", error: state.status === "error", note: state.status === "error" ? "不能据此判断学校没有招聘。" : "" });
    } else if (data.items.length && !notice) panel.hidden = true;
    else if (data.items.length) renderNotice(panel, "上次结果，尚未更新", notice, { stale, error: state.status === "error", loading: state.status === "loading" });
    else {
      const [title, message] = EMPTY_RESULTS[data.empty_reason] || ["当前没有可展示的招聘", "当前查询未返回记录；官方覆盖尚未核验。"];
      renderNotice(panel, title, message, { stale, error: state.status === "error", loading: state.status === "loading", note: notice });
    }
    get("pagination").hidden = !data?.total;
    get("previous-page").disabled = !query.canPage() || !data || data.offset === 0;
    get("next-page").disabled = !query.canPage() || !data?.has_more;
    get("page-label").textContent = data ? `第 ${Math.floor(data.offset / data.limit) + 1} 页` : "";
    for (const button of doc.querySelectorAll("[data-view]")) {
      const active = button.dataset.view === state.applied.view;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("is-active", active);
    }
    get("scope-toggle").setAttribute("aria-pressed", String(state.applied.scope === "all"));
    get("scope-toggle").textContent = state.applied.scope === "all" ? "只看电气相关" : "全部招聘";
  }
  function render(key) {
    if (key === "catalog") renderCatalog();
    if (key === "updates") renderUpdates();
    renderResults();
    const loading = Object.values(resources).some(resource => resource.status === "loading");
    get("reload-button").disabled = loading;
    get("reload-button").textContent = loading ? "正在加载…" : "重新加载";
  }
  function readDraft() {
    const values = {};
    for (const key of ["school_key", "campus_id", "kind", "keyword", "date_from", "date_to"]) values[key] = form.elements.namedItem(key)?.value.trim() || "";
    values.campus_unknown = values.campus_id === "__unknown__";
    if (values.campus_unknown) values.campus_id = "";
    return values;
  }
  function reload() { return Promise.allSettled([reader.reload(["catalog", "updates"]), query.reload()]); }
  form.addEventListener("input", event => { if (event.target.tagName === "INPUT") query.editDraft(readDraft()); });
  form.addEventListener("change", event => { query.editDraft(readDraft()); if (event.target === get("school-select")) renderCampuses(); });
  form.addEventListener("submit", event => { event.preventDefault(); query.editDraft(readDraft()); query.submit(); });
  form.addEventListener("reset", event => { event.preventDefault(); for (const control of form.querySelectorAll("input,select")) control.value = ""; query.clear(); renderCampuses(); });
  get("reload-button").addEventListener("click", reload);
  get("previous-page").addEventListener("click", () => query.page(state.page - (state.data?.limit || 20)));
  get("next-page").addEventListener("click", () => query.page(state.page + (state.data?.limit || 20)));
  for (const button of doc.querySelectorAll("[data-view]")) button.addEventListener("click", () => query.setView(button.dataset.view));
  get("scope-toggle").addEventListener("click", () => query.setScope(state.applied.scope === "all" ? "electrical" : "all"));
  reload();
  return { state, resources, reload, query: query.query, renderResults, destroy() { reader.destroy(); query.destroy(); } };
}
