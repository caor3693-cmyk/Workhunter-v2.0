import { displayTime, element } from "../components/dom.js";
import { PAGE_READ_PATHS } from "./routes.js";
import { createPageReader, pageDatasetsAgree, resourceMessage } from "./shared.js";

export function feedbackTemplate(stage, identity = {}) {
  const count = stage === "M1" ? 8 : 7;
  return [
    `阶段：${stage}；入口：${identity.url || "填写当前Site链接"}`,
    `前端：${identity.frontend || "尚未取得"}；后端：${identity.backend || "尚未取得"}`,
    `数据模式：${identity.mode || "尚未取得"}；数据集：${identity.dataset || "尚未取得"}`,
    ...Array.from({ length: count }, (_, index) => `${stage}-0${index + 1}：通过 / 失败 / 阻塞 / 未测；实际看到：`),
    "失败或阻塞的操作位置：", "截图或原文链接（可选）：",
  ].join("\n");
}

export function assessReadIdentity(health, version, frontendCommit) {
  if (!health || !version) return { verified: false, message: "当前身份尚未取得。" };
  if (health.project !== "Workhunter-v2.0" || version.project !== "Workhunter-v2.0") return { verified: false, message: "当前响应的项目身份需要核对。" };
  for (const key of ["project", "backend_commit", "version", "data_mode", "dataset_id"]) {
    if (typeof health[key] !== "string" || !health[key] || health[key] !== version[key]) return { verified: false, message: "健康与版本响应的构建或数据身份不一致，请重新核对。" };
  }
  const sha = /^[0-9a-f]{40}$/i;
  if (!sha.test(version.backend_commit) || ("build_id" in version && !sha.test(version.build_id)) || ("build_id" in health && !sha.test(health.build_id))) return { verified: false, message: "后端构建尚未固定为干净提交，请核对运行版本。" };
  if (health.build_id !== version.build_id) return { verified: false, message: "健康与版本返回的构建身份不一致。" };
  if (!sha.test(frontendCommit || "") || frontendCommit !== version.backend_commit) return { verified: false, message: "前端与后端源码提交尚未核对为同一候选；请对照下方分别记录的身份。" };
  if (health.status !== "ok" || health.database !== "readable") return { verified: false, message: "当前数据库尚未核对为可读。" };
  return { verified: true, message: "已读取同一 Workhunter v2 构建，数据库可读；学校覆盖和用户验收另行核对。" };
}

export function mountReview({ document: doc = globalThis.document, read } = {}) {
  const get = id => doc.getElementById(id);
  const reader = createPageReader(PAGE_READ_PATHS.review, render, read);
  const metaCommit = doc.querySelector('meta[name="workhunter-frontend-commit"]')?.content;
  const frontend = metaCommit && !metaCommit.startsWith("__") ? metaCommit : "本地工作区，尚未固定提交";
  function row(label, value, resource) {
    const stale = resource?.data && resource.status !== "ready" ? "（上次结果，尚未更新）" : "";
    return element("div", {}, [element("dt", { text: label }), element("dd", { text: `${value || "尚未取得"}${stale}` })]);
  }
  function render() {
    const { health, version } = reader.resources;
    const backend = version.data;
    const status = get("connection-status");
    const ready = health.status === "ready" && version.status === "ready";
    const identity = assessReadIdentity(health.data, version.data, frontend);
    const valid = ready && pageDatasetsAgree(reader.resources) && identity.verified;
    if (health.status === "error" || version.status === "error") {
      status.textContent = `连接核对未完成：${resourceMessage(health.status === "error" ? health : version)}`;
    } else if (!ready) status.textContent = "仍在读取，当前连接和身份尚未完整核对。";
    else status.textContent = identity.message;
    status.classList.toggle("is-error", (ready && !valid) || health.status === "error" || version.status === "error");
    status.classList.toggle("is-connected", valid);
    const observedAt = version.observedAt && health.observedAt ? (version.observedAt > health.observedAt ? version.observedAt : health.observedAt) : null;
    get("build-identity").replaceChildren(
      row("后端项目 / 版本", backend ? `${backend.project || "未提供"} / ${backend.version || "未提供"}` : null, version),
      row("后端阶段", backend?.stage, version),
      row("前端源码提交", frontend), row("后端源码提交", backend?.backend_commit, version),
      row("后端构建身份", backend?.build_id || backend?.backend_commit, version),
      row("数据模式", backend?.data_mode, version), row("数据集", backend?.dataset_id, version),
      row("数据库状态", health.data?.database, health),
      row("本次页面读取", observedAt ? `${displayTime(observedAt)}（北京时间）` : null),
    );
  }
  async function reload() {
    const button = get("reload-button");
    button.disabled = true;
    button.textContent = "正在核对…";
    await reader.reload();
    button.disabled = false;
    button.textContent = "重新核对";
  }
  async function copy(stage) {
    const version = reader.resources.version;
    const identity = version.status === "ready" ? version.data : {};
    const template = feedbackTemplate(stage, { url: doc.location?.href, frontend, backend: identity.backend_commit, mode: identity.data_mode, dataset: identity.dataset_id });
    const text = get("feedback-template");
    text.value = template;
    try {
      await globalThis.navigator.clipboard.writeText(template);
      get("copy-status").textContent = `${stage} 反馈模板已复制，请填写实际结果后发送。`;
    } catch {
      text.hidden = false;
      text.focus();
      text.select();
      get("copy-status").textContent = "浏览器未允许自动复制，请复制下方已选中的模板。";
    }
  }
  get("reload-button").addEventListener("click", reload);
  get("copy-feedback").addEventListener("click", () => copy("M0"));
  get("copy-m1-feedback")?.addEventListener("click", () => copy("M1"));
  reload();
  return { resources: reader.resources, reload, destroy: reader.destroy };
}
