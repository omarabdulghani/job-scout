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

let deps = {};

/**
 * Initialize the applications module and wire up DOM events.
 */
export function initApplications(dependencies) {
  deps = dependencies;
  const { state, els } = deps;

  els.refreshApplicationsButton.addEventListener("click", () => reloadApplications());

  els.applicationSearch.addEventListener("input", () => {
    state.applicationFilters.search = els.applicationSearch.value;
    window.clearTimeout(state.applicationSearchTimer);
    state.applicationSearchTimer = window.setTimeout(() => reloadApplications(), 250);
  });

  els.applicationStageFilter.addEventListener("change", () => {
    state.applicationFilters.stage = els.applicationStageFilter.value;
    reloadApplications();
  });

  els.loadMoreApplicationsButton.addEventListener("click", () => {
    reloadApplications({ append: true });
  });
}

/**
 * Public export to trigger an applications data reload.
 */
export async function reloadApplications({ append = false } = {}) {
  await loadApplications({ append });
}

async function loadApplications({ append = false } = {}) {
  const { state, safe, apiUrls } = deps;
  state.applicationsLoading = true;
  setApplicationsStatus("Loading applications...");
  try {
    const existing = append && Array.isArray(state.applicationsPayload?.applications)
      ? state.applicationsPayload.applications
      : [];
    const parameters = buildApplicationsQuery(
      state.applicationFilters,
      existing.length
    );
    const response = await fetch(apiUrls.applications + "?" + parameters, { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const payload = await response.json();
    state.applicationsPayload = {
      ...payload,
      applications: append
        ? [...existing, ...(payload.applications || [])]
        : (payload.applications || [])
    };
    renderApplications();
    setApplicationsStatus("Application progress is saved locally and survives future scout runs.");
  } catch (error) {
    setApplicationsStatus("Applications could not be loaded: " + (safe(error.message) || "unknown error"), "error");
  } finally {
    state.applicationsLoading = false;
  }
}

function renderApplications() {
  const { state, els, numeric } = deps;
  const payload = state.applicationsPayload || {};
  const all = Array.isArray(payload.applications) ? payload.applications : [];
  const counts = payload.by_stage || {};
  const summary = applicationStageSummary(counts);

  els.applicationStatTotal.textContent = String(summary.total);
  els.applicationStatPreparing.textContent = String(summary.preparing);
  els.applicationStatApplied.textContent = String(summary.applied);
  els.applicationStatInterview.textContent = String(summary.interview);
  els.applicationStatOffer.textContent = String(summary.offer);

  els.applicationsTableBody.replaceChildren();
  all.forEach((record) => els.applicationsTableBody.append(applicationRow(record)));

  els.applicationsEmpty.classList.toggle("hidden", all.length > 0);
  els.applicationsTableBody.parentElement.classList.toggle("hidden", all.length === 0);
  els.applicationsTableFooter.classList.toggle("hidden", all.length === 0);
  
  els.applicationsVisibleCount.textContent = `Showing ${all.length} of ${numeric(payload.total)} matching applications`;
  els.loadMoreApplicationsButton.classList.toggle("hidden", !payload.has_more);
  els.loadMoreApplicationsButton.textContent = `Show ${Math.min(50, numeric(payload.total) - all.length)} more`;
}

function applicationRow(record) {
  const { safe, formatDateTime } = deps;
  const row = document.createElement("tr");
  
  const jobCell = document.createElement("td");
  jobCell.dataset.label = "Job";
  const title = document.createElement("div");
  title.className = "application-job-title";
  const titleLink = document.createElement(record.url ? "a" : "span");
  titleLink.textContent = safe(record.title) || "Untitled job";
  if (record.url) {
    titleLink.href = record.url;
    titleLink.target = "_blank";
    titleLink.rel = "noopener";
  }
  const meta = document.createElement("span");
  meta.className = "subline";
  meta.textContent = [safe(record.company), safe(record.location)].filter(Boolean).join(" - ");
  title.append(titleLink, meta);
  jobCell.append(title);

  const stageCell = document.createElement("td");
  stageCell.dataset.label = "Stage and follow-up";
  const edit = document.createElement("div");
  edit.className = "application-edit";
  const stage = document.createElement("select");
  stage.setAttribute("aria-label", "Application stage for " + (safe(record.title) || "job"));
  [
    ["preparing", "Preparing"],
    ["applied", "Applied"],
    ["interview", "Interview"],
    ["offer", "Offer"],
    ["rejected", "Rejected"],
    ["withdrawn", "Withdrawn"]
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === record.application_stage;
    stage.append(option);
  });
  
  const followUp = document.createElement("input");
  followUp.type = "date";
  followUp.value = safe(record.follow_up_at).slice(0, 10);
  followUp.setAttribute("aria-label", "Follow-up date for " + (safe(record.title) || "job"));
  edit.append(stage, followUp);
  stageCell.append(edit);

  const notesCell = document.createElement("td");
  notesCell.dataset.label = "Notes";
  const notes = document.createElement("textarea");
  notes.className = "application-row-note";
  notes.rows = 3;
  notes.value = record.notes || record.application_notes || "";
  notes.placeholder = "Interview details, contact, next step...";
  notes.setAttribute("aria-label", "Application notes for " + (safe(record.title) || "job"));
  notesCell.append(notes);

  const updatedCell = document.createElement("td");
  updatedCell.dataset.label = "Updated";
  updatedCell.textContent = formatDateTime(record.application_updated_at || record.updated_at) || "-";

  const actionCell = document.createElement("td");
  actionCell.dataset.label = "Action";
  const saveButton = document.createElement("button");
  saveButton.type = "button";
  saveButton.className = "button secondary";
  saveButton.textContent = "Save";
  saveButton.setAttribute("aria-label", "Save application changes for " + (safe(record.title) || "job"));
  
  saveButton.addEventListener("click", () => saveApplicationRecord(record, {
    stage: stage.value,
    follow_up_at: followUp.value,
    notes: notes.value
  }, saveButton));
  
  actionCell.append(saveButton);
  row.append(jobCell, stageCell, notesCell, updatedCell, actionCell);
  
  return row;
}

async function saveApplicationRecord(record, updates, button) {
  const { safe, loadData, apiUrls } = deps;
  button.disabled = true;
  setApplicationsStatus("Saving application...");
  try {
    const response = await fetch("/api/application", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: record, ...updates })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error(result.error || "Application save failed");
    
    await reloadApplications();
    if (loadData) await loadData();
    
    setApplicationsStatus("Application updated.", "success");
  } catch (error) {
    setApplicationsStatus(safe(error.message) || "Application could not be saved.", "error");
  } finally {
    button.disabled = false;
  }
}

function setApplicationsStatus(message, kind = "") {
  const { els } = deps;
  if (!els.applicationsStatus) return;
  els.applicationsStatus.textContent = message;
  els.applicationsStatus.className = "profile-status" + (kind ? " " + kind : "");
}
