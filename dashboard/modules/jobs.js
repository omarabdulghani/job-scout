export const DECISIONS = [
  ["APPLY_FIRST", "APPLY FIRST"],
  ["GOOD_OPTIONS", "GOOD OPTIONS"],
  ["LOW_PROBABILITY", "LOW PROBABILITY"],
  ["REJECTED", "REJECTED"],
];

export const MANUAL_STATUSES = [
  ["unreviewed", "Unreviewed"],
  ["applied", "Applied"],
  ["irrelevant", "Irrelevant"],
];

export const APPLY_METHODS = [
  ["easy_apply", "Easy Apply"],
  ["external_apply", "External Apply"],
  ["unknown", "Unknown"],
];

export const QUICK_PRESETS = [
  ["needs_action", "Actionable"],
  ["current_run", "Current Run"],
  ["apply_first", "Apply First"],
  ["good_options", "Good Options"],
  ["easy_apply", "Easy Apply"],
  ["dutch_risk", "Dutch Risk"],
  ["remote_hybrid", "Remote/Hybrid"],
  ["remote_only", "Remote Only"],
  ["hybrid_only", "Hybrid Only"],
  ["applied", "Applied"],
  ["irrelevant", "Irrelevant"],
];

export const QUICK_PRESET_ICONS = Object.freeze({
  needs_action: "target",
  current_run: "activity",
  apply_first: "star",
  good_options: "check-circle",
  easy_apply: "briefcase",
  dutch_risk: "filter",
  remote_hybrid: "activity",
  remote_only: "activity",
  hybrid_only: "activity",
  applied: "check",
  irrelevant: "archive",
});

export const SUMMARY_ICONS = Object.freeze({
  Fresh: "briefcase",
  "Apply first": "star",
  Apply: "star",
  "Good+": "check-circle",
  Good: "check-circle",
  "Known skipped": "archive",
  Skipped: "archive",
  "AI calls": "activity",
  AI: "activity",
  Queries: "search",
  Stop: "ban",
});

export const DECISION_ICONS = Object.freeze({
  APPLY_FIRST: "star",
  GOOD_OPTIONS: "check-circle",
  LOW_PROBABILITY: "trending-down",
  REJECTED: "x-circle",
});

export function buildJobsQuery(filters, offset, now = Date.now()) {
  return new URLSearchParams({
    search: String(filters.search || "").trim(),
    decision: filters.decision !== "all"
      ? filters.decision
      : (filters.actionScope === "needs_action" ? "APPLY_FIRST,GOOD_OPTIONS" : ""),
    run: filters.run === "all" ? "" : filters.run,
    domain: filters.domain === "all" ? "" : filters.domain,
    search_group: filters.searchGroup === "all" ? "" : filters.searchGroup,
    career_lane: filters.careerLane === "all" ? "" : filters.careerLane,
    search_market: filters.searchMarket === "all" ? "" : filters.searchMarket,
    employment_type: filters.employmentType === "all" ? "" : filters.employmentType,
    flexible_hours: filters.flexibleHours === "all" ? "" : filters.flexibleHours,
    sponsorship_status: filters.sponsorshipStatus === "all" ? "" : filters.sponsorshipStatus,
    platform: filters.platform === "all" ? "" : filters.platform,
    flag: filters.flag === "all" ? "" : filters.flag,
    apply_method: filters.applyMethod === "all" ? "" : filters.applyMethod,
    status: filters.actionScope === "needs_action"
      ? "unreviewed"
      : (filters.manualStatus === "all" ? "" : filters.manualStatus),
    preset: ["dutch_risk", "remote_hybrid"].includes(filters.quickPreset)
      ? filters.quickPreset
      : "",
    sort: filters.sort,
    limit: filters.viewMode === "board" && filters.decision === "all" ? "1500" : "100",
    offset: String(offset),
    t: String(now),
  });
}
