import { readJSON } from "../api/client.js";
import { element } from "../components/dom.js";

export function createPageReader(paths, onChange, read = readJSON) {
  const resources = Object.fromEntries(Object.keys(paths).map(key => [key, { status: "loading", data: null, error: null, observedAt: null }]));
  const pending = new Map();
  let destroyed = false;
  async function load(key, overridePath) {
    if (!(key in resources)) throw new Error("Unknown page resource");
    pending.get(key)?.abort();
    const controller = new AbortController();
    pending.set(key, controller);
    const resource = resources[key];
    resource.status = "loading";
    resource.error = null;
    onChange(key, resources);
    try {
      const data = await read(overridePath || paths[key], { signal: controller.signal });
      if (destroyed || pending.get(key) !== controller) return;
      resources[key] = { status: "ready", data, error: null, observedAt: new Date().toISOString() };
    } catch (error) {
      if (destroyed || controller.signal.aborted || pending.get(key) !== controller) return;
      resource.status = "error";
      resource.error = error;
    } finally {
      if (!destroyed && pending.get(key) === controller) {
        pending.delete(key);
        onChange(key, resources);
      }
    }
  }
  return {
    resources,
    load,
    reload: (keys = Object.keys(paths)) => Promise.allSettled(keys.map(key => load(key))),
    destroy() { destroyed = true; for (const controller of pending.values()) controller.abort(); pending.clear(); },
  };
}

export function resourceMessage(resource, loadingText = "正在读取…") {
  if (resource.status === "loading") return resource.data ? "正在重新读取；暂显示上次结果。" : loadingText;
  if (resource.status === "error") return `${resource.error?.message || "当前数据暂不可读。"}${resource.data ? " 上次结果，尚未更新。" : " 尚未取得当前结果。"}`;
  return "";
}

export function pageDatasetsAgree(resources) {
  const ids = Object.values(resources).filter(resource => resource.data?.dataset_id).map(resource => resource.data.dataset_id);
  return new Set(ids).size <= 1;
}

export function renderNotice(panel, heading, message, { loading = false, error = false, stale = false, note = "" } = {}) {
  const illustration = element("span", { className: "state-illustration", "aria-hidden": "true" }, [element("span", { className: "paper-line" }), element("span", { className: "paper-line" }), element("span", { className: "paper-line short" })]);
  panel.hidden = false;
  panel.replaceChildren(illustration, element("h3", { text: heading }), element("p", { text: message }), ...(note ? [element("p", { className: "state-note", text: note })] : []));
  panel.classList.toggle("is-loading", loading);
  panel.classList.toggle("is-error", error);
  panel.classList.toggle("is-stale", stale);
  panel.setAttribute("aria-busy", String(loading));
}

export function setResourceStatus(node, resource, loadingText, readyText) {
  node.textContent = resourceMessage(resource, loadingText) || readyText;
  node.classList.toggle("is-error", resource.status === "error");
}
