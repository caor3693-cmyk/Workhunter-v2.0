export const PAGE_ASSET_ROUTES = Object.freeze({
  "/": "/index.html",
  "/sources": "/frontend/pages/sources.html",
  "/review": "/frontend/pages/review.html",
  "/maintenance": "/frontend/pages/maintenance.html",
});

export const PAGE_READ_PATHS = Object.freeze({
  home: Object.freeze({ catalog: "/api/catalog", opportunities: "/api/opportunities" }),
  sources: Object.freeze({ catalog: "/api/catalog", sources: "/api/sources/status" }),
  review: Object.freeze({ health: "/health", version: "/version" }),
});

export function resolvePage(pathname) {
  if (pathname === "/") return { page: "home", asset: PAGE_ASSET_ROUTES[pathname] };
  if (pathname === "/sources") return { page: "sources", asset: PAGE_ASSET_ROUTES[pathname] };
  if (pathname === "/review") return { page: "review", asset: PAGE_ASSET_ROUTES[pathname] };
  if (pathname === "/maintenance") return { page: "maintenance", asset: PAGE_ASSET_ROUTES[pathname] };
  const detail = /^\/opportunities\/([1-9]\d*)$/.exec(pathname);
  return detail ? { page: "detail", asset: "/frontend/pages/detail.html", opportunityId: detail[1] } : null;
}
