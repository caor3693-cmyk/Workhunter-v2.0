const PUBLIC_PATHS = new Set([
  "/api/catalog",
  "/api/opportunities",
  "/api/updates/summary",
  "/api/sources/status",
  "/version",
  "/health",
]);

export class ReadError extends Error {
  constructor(message, status = 0, code = "connection_failed") {
    super(message);
    this.name = "ReadError";
    this.status = status;
    this.code = typeof code === "string" ? code : "connection_failed";
  }
}

function statusMessage(status, code) {
  if (code === "service_unauthorized" || code === "loopback_only") return "数据连接授权配置需要检查，请稍后重新加载。";
  if (code === "database_unavailable") return "开发数据暂不可读，请稍后重新加载。";
  if (code === "development_api_unconfigured") return "开发环境尚未连接，请稍后重新加载。";
  if (code === "development_api_timeout") return "数据连接超时，请重新加载。";
  if (code === "development_api_unavailable") return "暂时无法连接开发数据，请重新加载。";
  if (status === 401 || status === 403) return "当前验收入口无访问权限，请确认已登录本次 Site。";
  if (status === 404) return "当前版本尚未提供这个读取入口。";
  if (status === 409) return "数据版本已改变，请重新加载。";
  if (status === 422) return "读取条件暂不可用，请重新加载。";
  if (status === 503) return "开发数据暂不可用，服务或新数据库尚未就绪。";
  if (status >= 500) return "开发服务暂时出错，请稍后重新加载。";
  return "本次读取失败，请重新加载。";
}

function validateResponse(path, data) {
  let valid = typeof data.dataset_id === "string" && data.dataset_id.length > 0 && typeof data.data_mode === "string";
  if (path === "/api/catalog") valid &&= Array.isArray(data.schools);
  if (path === "/api/opportunities") valid &&= Array.isArray(data.items) && Number.isInteger(data.total) && typeof data.applied_filters === "object";
  if (path === "/api/updates/summary") valid &&= typeof data.check_status === "string" && data.today !== null && typeof data.today === "object";
  if (path === "/api/sources/status") valid &&= Array.isArray(data.sources);
  if (path === "/version") valid &&= typeof data.project === "string" && typeof data.version === "string" && typeof data.backend_commit === "string";
  if (path === "/health") valid &&= typeof data.status === "string" && typeof data.database === "string";
  if (!valid) throw new ReadError("当前数据与本阶段接口约定不一致，读取尚未完成。", 200, "invalid_contract");
}

function errorCode(data) {
  const code = data?.detail?.code ?? data?.error?.code ?? data?.error;
  return typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : "http_error";
}

export async function readJSON(path, { signal, timeout = 15000 } = {}) {
  if (!PUBLIC_PATHS.has(path)) throw new ReadError("读取路径不在本阶段公开接口范围。", 0, "unsupported_path");
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeout);
  try {
    const response = await fetch(path, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    let data;
    try {
      data = await response.json();
    } catch (error) {
      if (timedOut || signal?.aborted || controller.signal.aborted) throw error;
      if (!response.ok) throw new ReadError(statusMessage(response.status), response.status, "http_error");
      throw new ReadError("入口未返回可读的数据，当前连接尚未核验。", response.status, "invalid_response");
    }
    if (timedOut) throw new ReadError("读取超时，请重新加载。", 0, "timeout");
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (!response.ok) {
      const code = errorCode(data);
      throw new ReadError(statusMessage(response.status, code), response.status, code);
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new ReadError("数据格式暂不可读，请重新加载。", response.status, "invalid_response");
    validateResponse(path, data);
    return data;
  } catch (error) {
    if (timedOut) throw new ReadError("读取超时，请重新加载。", 0, "timeout");
    if (signal?.aborted) throw error;
    if (error instanceof ReadError) throw error;
    throw new ReadError("无法连接当前开发数据，请检查网络后重新加载。", 0, "connection_failed");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
