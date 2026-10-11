import { opportunityPath } from "../components/dom.js";
import { detailContent } from "../components/cards.js";
import { createPageReader, resourceMessage } from "./shared.js";

export function mountDetail({ document: doc = globalThis.document, read, opportunityId } = {}) {
  const get = id => doc.getElementById(id);
  const path = opportunityPath(opportunityId, "/api/opportunities/");
  const article = get("detail-content");
  article.dataset.opportunityId = opportunityId;
  const button = get("reload-button");
  button.hidden = false;
  if (!path) {
    get("detail-status").textContent = "公告编号无效，当前详情不可读。请返回招聘发现。";
    button.hidden = true;
    return { opportunityId, destroy() {} };
  }
  const reader = createPageReader({ detail: path }, () => {
    const resource = reader.resources.detail;
    button.disabled = resource.status === "loading";
    button.textContent = resource.status === "loading" ? "正在加载…" : "重新加载";
    get("detail-status").textContent = resourceMessage(resource, "正在读取本条公告…") || "以下事实与材料仅适用于本条学校公告。";
    get("detail-status").classList.toggle("is-error", resource.status === "error");
    article.hidden = !resource.data;
    article.classList.toggle("is-stale", resource.status !== "ready");
    if (resource.data) {
      get("page-title").textContent = resource.data.title || "标题尚未取得";
      doc.title = `${resource.data.title || "简要详情"} · Workhunter`;
      article.replaceChildren(detailContent(resource.data));
    }
  }, read);
  const reload = () => reader.load("detail");
  button.addEventListener("click", reload);
  reload();
  return { opportunityId, resources: reader.resources, reload, destroy: reader.destroy };
}
