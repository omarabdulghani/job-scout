export function resolvePage(pageId, pages, fallback = "jobs") {
  const allowed = new Set(pages.map((page) => page.dataset.pageId));
  return allowed.has(pageId) ? pageId : fallback;
}

export function workspaceLabel(activeButton, pageId, labelize) {
  return activeButton ? String(activeButton.textContent || "").trim() : labelize(pageId);
}

export function pageDocumentTitle(pageId, labelize) {
  return pageId === "jobs" ? "Job Scout - Jobs" : `Job Scout - ${labelize(pageId)}`;
}
