import { displayTime, element, safePublicURL } from "../components/dom.js";
import { PAGE_READ_PATHS } from "./routes.js";
import { createPageReader, pageDatasetsAgree, resourceMessage, setResourceStatus } from "./shared.js";

const SOURCE_LABELS = { not_checked: "尚未检查", pending: "尚未核验", healthy: "检查正常", success: "已取得材料", partial: "部分完成", failed: "检查失败", restricted: "访问受限", stale: "最近检查已陈旧", paused: "已暂停" };

export function mountSources({ document: doc = globalThis.document, read } = {}) {
  const get = id => doc.getElementById(id);
  const reader = createPageReader(PAGE_READ_PATHS.sources, render, read);
  function render() {
    const { catalog, sources } = reader.resources;
    const schools = catalog.data?.schools || [];
    setResourceStatus(get("catalog-status"), catalog, "正在读取学校目录…", `${schools.length} 所学校已登记，不因失败或零条目移除。`);
    setResourceStatus(get("source-status"), sources, "正在读取来源状态…", "以下状态来自当前服务，不等同于完整自动覆盖。");
    const schedule = sources.data?.schedule;
    if (sources.status === 'ready' && schedule) {
      const plan = schedule.status === 'scheduled' && schedule.next_run_at ? `已登记下次检查：${displayTime(schedule.next_run_at)}（北京时间）` :
        schedule.status === 'running' ? '定时检查正在运行；完整性以逐源结果为准。' :
        schedule.status === 'overdue' ? '定时计划已逾期，尚未核实触发；保留上次可靠结果。' :
        schedule.status === 'disabled' ? '自动检查已停用；页面只读取已有记录。' : '自动检查宿主状态尚未核实。';
      get('source-status').textContent = `以下状态来自当前服务，不等同于完整自动覆盖。${plan}`;
    }
    if (!pageDatasetsAgree(reader.resources)) {
      get("source-status").textContent = "目录与来源数据身份不一致，请重新加载；当前内容尚未核对为同一版本。";
      get("source-status").classList.add("is-error");
    }
    const records = sources.data?.sources || [];
    const groups = schools.length ? schools : [...new Set(records.map(item => item.school_key))].map(school_key => ({ school_key, name: records.find(item => item.school_key === school_key)?.school_name || "学校名称尚未取得" }));
    get("source-list").replaceChildren(...groups.map(school => {
      const card = element("article", { className: "source-school" }, [element("h2", { text: school.name })]);
      if (school.availability_message) card.append(element('p', { className: 'source-message', text: school.availability_message }));
      if (school.scope_note) card.append(element('p', { className: 'source-message', text: school.scope_note }));
      const entries = records.filter(item => item.school_key === school.school_key);
      if (!entries.length) card.append(element("p", { className: "source-message", text: sources.status === "ready" ? "来源状态尚未取得，不能判断覆盖情况。" : resourceMessage(sources, "来源状态仍在读取…") }));
      for (const source of entries) {
        const row = element("div", { className: "source-row" }, [element("span", { className: `source-state${source.status === "restricted" || source.status === "failed" ? " is-warning" : ""}`, text: SOURCE_LABELS[source.status] || "状态待核实" })]);
        const url = safePublicURL(source.official_entry_url);
        row.append(url ? element("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: `${source.name || "官方入口"} ↗`, "aria-label": `${school.name} ${source.name || "官方入口"}，在新标签页打开` }) : element("span", { text: source.name || "来源入口尚未核验" }));
        card.append(row);
        if (source.message) card.append(element("p", { className: "source-message", text: source.message }));
        if (source.last_success_at) card.append(element("p", { className: "source-message", text: `最近成功：${displayTime(source.last_success_at)}（北京时间）` }));
        else if (!source.message) card.append(element("p", { className: "source-message", text: "尚未取得可用材料；目录登记不代表采集成功。" }));
        if (source.last_attempt_at) card.append(element('p', { className: 'source-message', text: `最近尝试：${displayTime(source.last_attempt_at)}（北京时间）` }));
        if (source.stale) card.append(element('p', { className: 'source-message', text: '最近成功已超过 48 小时，材料陈旧，当前情况待核实。' }));
        else if (source.review_due) card.append(element('p', { className: 'source-message', text: '最近成功已超过 24 小时，等待复核。' }));
      }
      return card;
    }));
    const loading = catalog.status === 'loading' || sources.status === 'loading';
    get('reload-button').disabled = loading;
    get('reload-button').textContent = loading ? '正在加载…' : '重新加载';
  }
  const reload = () => reader.reload();
  get("reload-button").addEventListener("click", reload);
  reload();
  return { resources: reader.resources, reload, destroy: reader.destroy };
}
