export const URLS = Object.freeze({
  dataFile: "recommended_jobs_dashboard_data.json",
  dashboardData: "/api/dashboard-data",
  jobs: "/api/jobs",
  jobStatus: "/api/job-status",
  runControl: "/api/run-control",
  profile: "/api/profile",
  strategy: "/api/strategy",
  aiSettings: "/api/ai-settings",
  boardSettings: "/api/board-settings",
  applications: "/api/applications",
  assistant: "/api/application-assistant",
  maintenance: "/api/maintenance",
  legacyTools: "/api/legacy-tools",
});

export const POLL_MS = 4000;
export const THEME_STORAGE_KEY = "jobDashboardTheme";

export function initialTheme(root = document.documentElement) {
  return root.dataset.theme === "dark" ? "dark" : "light";
}

export function safe(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function numeric(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function labelize(value) {
  return safe(value)
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatDateTime(value) {
  const cleaned = safe(value);
  return cleaned ? cleaned.slice(0, 16).replace("T", " ") : "";
}
