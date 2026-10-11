import { element, safePublicURL } from "../components/dom.js";
import { PAGE_READ_PATHS } from "./routes.js";
import { createPageReader, resourceMessage, renderNotice, setResourceStatus } from "./shared.js";

const EMPTY_RESULTS = {
  empty_database: ["尚未收录招聘", "当前新库没有招聘记录；这不代表学校没有招聘。"],
  school_not_collected: ["该校暂未收录", "该校当前没有入库记录，不能据此判断官方没有招聘。"],
  no_undated_matches: ["没有日期未知的记录", "当前条件下未找到日期未知的记录。"],
  no_matches: ["没有匹配结果", "可以调整条件，或查看其他日期视图。"],
};
const VIEW_LABELS = { recent: "近期", upcoming: "临近活动", history: "历史", undated: "日期未知" };

export function basicResultCard(item) {
  const heading = element("h3");
  const id = String(item.id ?? "");
  if (/^[1-9]\d*$/.test(id)) heading.append(element("a", { href: `/opportunities/${id}`, text: item.title || "标题尚未取得" }));
  else heading.textContent = item.title || "标题尚未取得";
  const card = element("article", { className: "opportunity-card" }, [element("p", { className: "card-school", text: item.school_name || "学校归属待核实" }), heading]);
  const original = safePublicURL(item.source_url);
  if (original) card.append(element("a", { className: "original-link", href: original, target: "_blank", rel: "noopener noreferrer", text: "官方原文 ↗" }));
  return card;
}

export function mountHome({ document: doc = globalThis.document, read, queryEnabled = false, renderCard = basicResultCard } = {}) {
  const get = id => doc.getElementById(id);
  const form = get("search-form");
  const state = { applied: { view: "recent", scope: "electrical" }, displayed: null, offset: 0 };
  const reader = createPageReader(PAGE_READ_PATHS.home, (key) => render(key), read);
  const resources = reader.resources;
  form.hidden = !queryEnabled;
  get("query-navigation").hidden = !queryEnabled;

  function renderCatalog() {
    const resource = resources.catalog;
    const schools = resource.data?.schools || [];
    const select = get("school-select");
    const previous = select.value;
    select.replaceChildren(element("option", { value: "", text: "全部学校" }), ...schools.map(school => element("option", { value: school.school_key, text: school.name })));
    if (schools.some(school => school.school_key === previous)) select.value = previous;
    setResourceStatus(get("catalog-status"), resource, "正在读取学校目录…", `${schools.length} 所学校已登记 · 采集情况见来源状态`);
  }
  function renderUpdates() {
    const resource = resources.updates;
    get("new-count").textContent = resource.data?.today?.newly_collected ?? "—";
    get("change-count").textContent = resource.data?.today?.official_changes ?? "—";
    setResourceStatus(get("update-message"), resource, "正在读取检查情况…", resource.data?.message || (resource.data?.check_status === "not_checked" ? "尚未检查，数量暂不可确认。" : "检查情况暂不可确认。"));
  }
  function scopeText(filters) {
    const school = resources.catalog.data?.schools.find(item => item.school_key === filters.school_key);
    return [school?.name || "全部学校", VIEW_LABELS[filters.view] || "近期", filters.scope === "all" ? "全部招聘" : "电气相关与相关性未知", filters.keyword ? `关键词：${filters.keyword}` : ""].filter(Boolean).join(" · ");
  }
  function renderResults() {
    const resource = resources.opportunities;
    const data = resource.data;
    const panel = get("opportunity-status");
    const list = get("result-list");
    const stale = Boolean(data && resource.status !== "ready");
    get("result-scope").textContent = scopeText(state.displayed?.filters || state.applied);
    get("result-count").textContent = data ? `${data.total} 条结果${stale ? " · 上次结果，尚未更新" : ""}` : "";
    if (!data) {
      list.replaceChildren();
      renderNotice(panel, resource.status === "error" ? "招聘暂时不可读" : "正在读取招聘…", resource.status === "error" ? resourceMessage(resource) : "读取完成后显示当前结果。", { loading: resource.status === "loading", error: resource.status === "error", note: resource.status === "error" ? "不能据此判断学校没有招聘。" : "" });
    } else {
      list.replaceChildren(...data.items.map(renderCard));
      const notice = resourceMessage(resource);
      if (data.items.length && !notice) panel.hidden = true;
      else if (data.items.length) renderNotice(panel, "上次结果，尚未更新", notice, { stale, error: resource.status === "error" });
      else {
        const [title, message] = EMPTY_RESULTS[data.empty_reason] || ["当前没有可展示的招聘", "当前查询未返回记录；官方覆盖尚未核验。"];
        renderNotice(panel, title, message, { stale, error: resource.status === "error", note: notice });
      }
    }
    const pagination = get("pagination");
    pagination.hidden = !queryEnabled || !data?.total;
    get("previous-page").disabled = !data || data.offset === 0 || resource.status === "loading";
    get("next-page").disabled = !data?.has_more || resource.status === "loading";
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
    if (key === "opportunities" || key === "catalog") renderResults();
  }
  function draftQuery() {
    const entries = [...new FormData(form)].filter(([, value]) => String(value).trim());
    return { view: state.applied.view, scope: state.applied.scope, ...Object.fromEntries(entries.map(([key, value]) => [key, String(value).trim()])) };
  }
  async function query(filters, offset = 0) {
    if (!queryEnabled) return reader.load("opportunities");
    const parameters = new URLSearchParams({ ...filters, offset: String(offset), limit: "20" });
    if (offset && resources.opportunities.data) {
      parameters.set("dataset_id", resources.opportunities.data.dataset_id);
      if (resources.opportunities.data.as_of) parameters.set("as_of", resources.opportunities.data.as_of);
    }
    state.applied = { ...filters };
    state.offset = offset;
    await reader.load("opportunities", `/api/opportunities?${parameters}`);
    if (resources.opportunities.status === "ready") state.displayed = { filters: { ...filters }, offset, dataset_id: resources.opportunities.data.dataset_id };
    renderResults();
  }
  async function reload() {
    const button = get("reload-button");
    button.disabled = true;
    button.textContent = "正在加载…";
    await Promise.allSettled([reader.reload(["catalog", "updates"]), query(state.applied, state.offset)]);
    button.disabled = false;
    button.textContent = "重新加载";
  }
  function renderCampuses() {
    const school = resources.catalog.data?.schools.find(item => item.school_key === get("school-select").value);
    get("campus-select").replaceChildren(element("option", { value: "", text: "全部校区" }), ...(school?.campuses || []).map(campus => element("option", { value: campus.id, text: campus.name })));
  }
  form.addEventListener("submit", event => { event.preventDefault(); query(draftQuery()); });
  form.addEventListener("reset", event => { event.preventDefault(); form.querySelectorAll("input,select").forEach(control => { control.value = ""; }); renderCampuses(); query({ view: state.applied.view, scope: state.applied.scope }); });
  get("school-select").addEventListener("change", renderCampuses);
  get("reload-button").addEventListener("click", reload);
  get("previous-page").addEventListener("click", () => query(state.applied, Math.max(0, resources.opportunities.data.offset - resources.opportunities.data.limit)));
  get("next-page").addEventListener("click", () => query(state.applied, resources.opportunities.data.offset + resources.opportunities.data.limit));
  for (const button of doc.querySelectorAll("[data-view]")) button.addEventListener("click", () => query({ ...state.applied, view: button.dataset.view }));
  get("scope-toggle").addEventListener("click", () => query({ ...state.applied, scope: state.applied.scope === "all" ? "electrical" : "all" }));
  reload();
  return { state, resources, reload, query, renderResults, destroy: reader.destroy };
}
