import { resolvePage } from "./routes.js";
import { mountHome } from "./home.js";
import { mountSources } from "./sources.js";
import { mountReview } from "./review.js";
import { mountDetail } from "./detail.js";
import { mountMaintenance } from "./maintenance.js";

export function mountPage(pathname, options = {}) {
  const route = resolvePage(pathname);
  const mount = { home: mountHome, sources: mountSources, review: mountReview, detail: mountDetail, maintenance: mountMaintenance }[route?.page];
  if (!mount) return null;
  return mount({ ...options, opportunityId: route.opportunityId });
}

if (typeof document !== "undefined" && typeof location !== "undefined") {
  mountPage(location.pathname);
}
