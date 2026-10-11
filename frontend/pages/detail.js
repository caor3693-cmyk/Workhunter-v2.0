export function mountDetail({ document: doc = globalThis.document, opportunityId } = {}) {
  const article = doc.getElementById("detail-content");
  article.dataset.opportunityId = opportunityId;
  return { opportunityId, article };
}
