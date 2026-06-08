export function buildApplicationsQuery(filters, offset, now = Date.now()) {
  return new URLSearchParams({
    limit: "50",
    offset: String(offset),
    search: String(filters.search || "").trim(),
    stage: filters.stage === "all" ? "" : filters.stage,
    t: String(now),
  });
}

export function applicationStageSummary(byStage = {}) {
  return {
    total: Object.values(byStage).reduce((sum, value) => sum + Number(value || 0), 0),
    preparing: Number(byStage.preparing || 0),
    applied: Number(byStage.applied || 0),
    interview: Number(byStage.interview || 0),
    offer: Number(byStage.offer || 0),
  };
}
