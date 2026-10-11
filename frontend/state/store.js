export const RESOURCE_PATHS = {
  catalog: "/api/catalog",
  opportunities: "/api/opportunities",
  updates: "/api/updates/summary",
  sources: "/api/sources/status",
  version: "/version",
  health: "/health",
};

export function createReadState() {
  return Object.fromEntries(Object.keys(RESOURCE_PATHS).map((key) => [key, {
    status: "loading",
    data: null,
    error: null,
    observedAt: null,
  }]));
}

export function datasetConsistency(state) {
  const ready = Object.values(state).filter((resource) => resource.status === "ready" && resource.data?.dataset_id);
  return new Set(ready.map((resource) => resource.data.dataset_id)).size <= 1;
}
