import { readJSON } from "../api/client.js";
import { displayTime, element, safePublicURL } from "../components/dom.js";
import { createReadState, datasetConsistency, RESOURCE_PATHS } from "../state/store.js";

const state = createReadState();
let generation = 0;
let activeRead = null;
const get = (id) => document.getElementById(id);

const sourceLabels = {
  not_checked: "尚未检查",
  pending: "尚未核验",
  healthy: "检查正常",
  success: "已取得材料",
  partial: "部分完成",
  failed: "检查失败",
  restricted: "访问受限",
  stale: "最近检查已陈旧",
  paused: "已暂停",
};

function isStale(resource) {
  return Boolean(resource.data && resource.status !== "ready");
}

function resourceMessage(resource, loadingText) {
  if (resource.status === "loading") return resource.data ? "正在重新读取；暂显示上次结果。" : loadingText;
  if (resource.status === "error") return `${resource.error.message}${resource.data ? " 上次结果，尚未更新。" : " 当前状态尚未取得。"}`;
  return "";
}

function renderCatalog() {
  const resource = state.catalog;
  const select = get("school-select");
  const status = get("catalog-status");
  if (resource.data) {
    const schools = resource.data.schools || [];
    select.replaceChildren(element("option", { value: "", text: "全部学校" }), ...schools.map((school) => element("option", { value: school.school_key, text: school.name })));
    status.textContent = resourceMessage(resource, "正在连接学校目录…") || `${schools.length} 所学校已登记；官方来源和校区尚未核验。`;
  } else {
    select.replaceChildren(element("option", { text: resource.status === "error" ? "学校目录暂不可读" : "正在读取学校目录…" }));
    status.textContent = resourceMessage(resource, "正在连接学校目录…");
  }
  status.classList.toggle("is-error", resource.status === "error");
}

function renderUpdates() {
  const resource = state.updates;
  const data = resource.data;
  get("new-count").textContent = data?.today?.newly_collected ?? "—";
  get("change-count").textContent = data?.today?.official_changes ?? "—";
  get("update-message").textContent = resourceMessage(resource, "正在读取最近检查情况…") || (
    data?.check_status === "not_checked" ? "尚未检查，新增与变化数量暂不可确认。" : (data?.message || "检查情况暂不可确认。")
  );
  get("update-message").classList.toggle("is-error", resource.status === "error");
}

function renderOpportunities() {
  const resource = state.opportunities;
  const panel = get("opportunity-status");
  const data = resource.data;
  let heading;
  let message;
  let extra = "";
  if (resource.status === "loading" && !data) {
    heading = "正在连接招聘数据…";
    message = "读取完成后会显示当前数据状态。";
  } else if (resource.status === "error" && !data) {
    heading = "招聘数据暂时不可读";
    message = resource.error.message;
    extra = "尚未取得结果，不能据此判断学校没有招聘。";
  } else if (!datasetConsistency(state)) {
    heading = "数据身份需要重新核对";
    message = "当前页面收到的数据版本不一致，请重新加载后再核验。";
    extra = "暂不将不同版本组合为本次结果。";
  } else if (data?.items?.length) {
    heading = "当前数据超出 M0 核验范围";
    message = "本版本仅核验空库骨架，不展示尚未完成核验的招聘卡片。";
    extra = "请核对本次交付包的数据模式和版本。";
  } else if (data?.data_mode === "empty" && data?.empty_reason === "empty_database") {
    heading = "新库尚未收录招聘";
    message = "当前为空库，尚未执行学校真实采集。";
    extra = "这不代表学校没有招聘。下一阶段将接入华工与广工的官方公告。";
  } else {
    heading = "当前没有可展示的招聘";
    message = "此结果仅说明当前查询没有返回记录，官方覆盖尚未核验。";
  }
  if (isStale(resource)) extra = `${resourceMessage(resource, "正在重新读取…")} ${extra}`;
  const illustration = element("span", { className: "state-illustration", "aria-hidden": "true" }, [element("span", { className: "paper-line" }), element("span", { className: "paper-line" }), element("span", { className: "paper-line short" })]);
  panel.replaceChildren(illustration, element("h3", { text: heading }), element("p", { text: message }), ...(extra ? [element("p", { className: "state-note", text: extra })] : []));
  panel.classList.toggle("is-loading", resource.status === "loading" && !data);
  panel.classList.toggle("is-error", resource.status === "error");
  panel.classList.toggle("is-stale", isStale(resource));
  panel.setAttribute("aria-busy", String(resource.status === "loading"));
}

function renderSources() {
  const resource = state.sources;
  const list = get("source-list");
  const status = get("source-status");
  status.textContent = resourceMessage(resource, "正在读取来源状态…") || "以下状态来自当前服务，不表示全校自动覆盖。";
  status.classList.toggle("is-error", resource.status === "error");
  if (!resource.data) {
    list.replaceChildren();
    return;
  }
  const schools = state.catalog.data?.schools || [];
  const sources = resource.data.sources || [];
  const groups = schools.length ? schools.map((school) => ({
    key: school.school_key,
    name: school.name,
    sources: sources.filter((source) => source.school_key === school.school_key),
  })) : [...new Set(sources.map((source) => source.school_key))].map((key) => ({
    key,
    name: sources.find((source) => source.school_key === key)?.school_name || "学校名称暂未取得",
    sources: sources.filter((source) => source.school_key === key),
  }));
  list.replaceChildren(...groups.map((school) => {
    const card = element("article", { className: "source-school" }, [element("h3", { text: school.name })]);
    if (!school.sources.length) card.append(element("p", { className: "source-message", text: "来源状态暂未取得，不能判断覆盖情况。" }));
    for (const source of school.sources) {
      const stateName = sourceLabels[source.status] || "状态待核实";
      const row = element("div", { className: "source-row" }, [element("span", { className: "source-state", text: stateName })]);
      const url = safePublicURL(source.official_entry_url);
      if (url) row.append(element("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: `${source.name || "官方入口"} ↗`, "aria-label": `${school.name} ${source.name || "官方入口"}，在新标签页打开` }));
      else row.append(element("span", { className: "source-name", text: source.name || "来源入口待核验" }));
      card.append(row);
      if (source.last_success_at) card.append(element("p", { className: "source-message", text: `最近成功：${displayTime(source.last_success_at)}（北京时间）` }));
      else card.append(element("p", { className: "source-message", text: source.message || "尚未取得可用材料；目录登记不代表采集成功。" }));
    }
    return card;
  }));
}

function identityRow(label, value) {
  return element("div", {}, [element("dt", { text: label }), element("dd", { text: value })]);
}

function renderIdentity() {
  const version = state.version;
  const health = state.health;
  const backend = version.data;
  const frontendCommit = document.querySelector('meta[name="workhunter-frontend-commit"]').content;
  const currentDataset = state.opportunities.data?.dataset_id;
  const mode = state.opportunities.data?.data_mode;
  const identity = get("build-identity");
  const consistent = datasetConsistency(state);
  const exactVersion = backend?.project === "Workhunter-v2.0";
  const healthy = health.status === "ready" && health.data?.status === "ok" && health.data?.database === "readable";
  const allReady = Object.values(state).every((resource) => resource.status === "ready");
  const connection = get("connection-status");
  if (state.version.status === "error" || state.health.status === "error") {
    connection.textContent = `连接核对未完成：${(version.error || health.error).message}${backend ? " 上次构建信息，尚未更新。" : ""}`;
    connection.className = "connection-status is-error";
  } else if (!allReady) {
    connection.textContent = "仍有数据正在读取或未读成功；本次完整连接核对尚未完成。";
    connection.className = "connection-status";
  } else if (!consistent || !exactVersion || !healthy) {
    connection.textContent = "当前构建或数据身份尚未核对一致，请重新加载并查看交付包。";
    connection.className = "connection-status is-error";
  } else {
    connection.textContent = "已读取 Workhunter v2 后端，新数据库可读；这不代表学校采集或持续维护已完成。";
    connection.className = "connection-status is-connected";
  }
  identity.replaceChildren(
    identityRow("本次阶段", backend?.stage || "M0 / W00 · 工程骨架"),
    identityRow("用户核验", "M0 · 未通过，问题修复后按原编号复验；最新结果见阶段 Issue"),
    identityRow("数据模式", mode === "empty" ? "空库（empty）· 无招聘演示" : mode ? `${mode} · 请对照当前核验包` : "尚未取得，不能判断"),
    identityRow("数据集", currentDataset || "尚未取得"),
    identityRow("后端项目 / 版本", backend ? `${backend.project || "未提供"} / ${backend.version || "未提供"}${isStale(version) ? "（上次结果，尚未更新）" : ""}` : "尚未取得"),
    identityRow("前端提交", frontendCommit && !frontendCommit.startsWith("__") ? frontendCommit : "本地工作区，尚未固定提交"),
    identityRow("后端提交", backend?.backend_commit || "尚未取得"),
    identityRow("本次读取时间", state.opportunities.observedAt ? `${displayTime(state.opportunities.observedAt)}（北京时间，页面读取时间）` : "尚未读取成功"),
  );
}

function render() {
  renderCatalog();
  renderUpdates();
  renderOpportunities();
  renderSources();
  renderIdentity();
}

async function reload() {
  const requestGeneration = ++generation;
  activeRead?.abort();
  activeRead = new AbortController();
  const signal = activeRead.signal;
  for (const resource of Object.values(state)) {
    resource.status = "loading";
    resource.error = null;
  }
  get("reload-button").disabled = true;
  get("reload-button").textContent = "正在加载…";
  render();
  await Promise.allSettled(Object.entries(RESOURCE_PATHS).map(async ([key, path]) => {
    try {
      const data = await readJSON(path, { signal });
      if (requestGeneration !== generation) return;
      state[key] = { status: "ready", data, error: null, observedAt: new Date().toISOString() };
    } catch (error) {
      if (requestGeneration !== generation || signal.aborted) return;
      state[key].status = "error";
      state[key].error = error;
    }
    render();
  }));
  if (requestGeneration !== generation) return;
  get("reload-button").disabled = false;
  get("reload-button").replaceChildren(element("span", { "aria-hidden": "true", text: "↻" }), document.createTextNode(" 重新加载"));
}

get("reload-button").addEventListener("click", reload);
get("search-form").addEventListener("submit", (event) => event.preventDefault());
get("sources-nav").addEventListener("click", () => { get("sources-details").open = true; });

const feedbackTemplate = [
  "阶段：M0；本次 Site／构建：填写实际入口和构建",
  ...Array.from({ length: 7 }, (_, index) => `M0-0${index + 1}：通过／失败／阻塞／未测；实际看到：`),
  "失败或阻塞的操作位置：",
  "截图或原文链接（可选）：",
].join("\n");
get("feedback-template").value = feedbackTemplate;
get("copy-feedback").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(feedbackTemplate);
    get("copy-status").textContent = "反馈模板已复制。请逐项填写后发到当前对话或 M0 Issue。";
  } catch {
    get("feedback-template").hidden = false;
    get("feedback-template").focus();
    get("feedback-template").select();
    get("copy-status").textContent = "浏览器未允许自动复制。请复制下方已选中的模板。";
  }
});

if (location.hash === "#sources") get("sources-details").open = true;
reload();
