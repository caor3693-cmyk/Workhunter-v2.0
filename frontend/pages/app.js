import { resolvePage } from "./routes.js";
import { mountHome } from "./home.js";
import { mountSources } from "./sources.js";
import { mountReview } from "./review.js";
import { mountDetail } from "./detail.js";

export function mountPage(pathname, options = {}) {
  const route = resolvePage(pathname);
  const mount = { home: mountHome, sources: mountSources, review: mountReview, detail: mountDetail }[route?.page];
  if (!mount) return null;
  return mount({ ...options, opportunityId: route.opportunityId });
}

if (typeof document !== "undefined" && typeof location !== "undefined") {
  mountPage(location.pathname);
}
