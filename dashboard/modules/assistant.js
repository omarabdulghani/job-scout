let deps = {};

/**
 * Initialize the assistant module and wire up DOM events.
 */
export function initAssistant(dependencies) {
  deps = dependencies;
  const { els } = deps;

  els.saveAssistantKnowledgeButton.addEventListener("click", saveAssistantKnowledge);
  els.findAssistantAnswerButton.addEventListener("click", findAssistantAnswer);
  els.createLocalDraftButton.addEventListener("click", () => generateAssistantDraft("local"));
  els.createAiDraftButton.addEventListener("click", () => generateAssistantDraft("ai"));
  els.copyAssistantDraftButton.addEventListener("click", copyAssistantDraft);
  els.downloadAssistantDraftButton.addEventListener("click", downloadAssistantDraft);
  els.addApplicationAnswerButton.addEventListener("click", () => addAnswerEditorRow(els.applicationAnswersEditor, "", "", "application"));
  els.addLearnedAnswerButton.addEventListener("click", () => addAnswerEditorRow(els.learnedAnswersEditor, "", "", "learned"));
}

/**
 * Public export to trigger an assistant data load.
 */
export async function loadAssistant() {
  const { state, safe, apiUrls } = deps;
  state.assistantLoading = true;
  setAssistantStatus("Loading application knowledge...");
  try {
    const response = await fetch(apiUrls.assistant + "?t=" + Date.now(), { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    state.assistantPayload = await response.json();
    renderAssistant();
    setAssistantStatus("Answers are stored in your private workspace. Final submission remains manual.");
  } catch (error) {
    setAssistantStatus("Application assistant could not be loaded: " + (safe(error.message) || "unknown error"), "error");
  } finally {
    state.assistantLoading = false;
  }
}

function renderAssistant() {
  const { state, els, numeric } = deps;
  const payload = state.assistantPayload || {};
  
  renderAnswerMapping(els.applicationAnswersEditor, payload.application_answers || {}, "application");
  renderAnswerMapping(els.learnedAnswersEditor, payload.learned_answers || {}, "learned");
  
  els.assistantCoverStyle.value = payload.cover_letter_style || "";
  els.assistantJobSelect.replaceChildren();
  
  const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
  if (!jobs.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No dashboard jobs available";
    els.assistantJobSelect.append(option);
  } else {
    jobs.forEach((job, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${job.title || "Untitled"} - ${job.company || "Unknown company"} (${numeric(job.score)})`;
      els.assistantJobSelect.append(option);
    });
  }
  
  els.createAiDraftButton.disabled = !payload.ai_document_configured || !jobs.length;
  els.createLocalDraftButton.disabled = !jobs.length;
  
  els.assistantAiNote.textContent = payload.ai_document_configured
    ? "Claude is configured. AI improvement runs only when you click the button."
    : "Claude is not configured. Free local drafts remain available.";
}

function renderAnswerMapping(container, mapping, kind) {
  container.replaceChildren();
  Object.entries(mapping || {}).forEach(([key, value]) => {
    addAnswerEditorRow(container, key, answerEditorValue(value), kind);
  });
  if (!container.children.length) {
    addAnswerEditorRow(container, "", "", kind);
  }
}

function addAnswerEditorRow(container, key = "", value = "", kind = "application") {
  const row = document.createElement("div");
  row.className = "answer-editor";
  row.dataset.answerKind = kind;
  
  const keyInput = document.createElement("input");
  keyInput.value = key;
  keyInput.placeholder = kind === "application" ? "Profile field or question key" : "Normalized question";
  keyInput.setAttribute("aria-label", kind === "application" ? "Application answer key" : "Learned question");
  
  const answer = document.createElement("textarea");
  answer.value = value;
  answer.placeholder = "Truthful answer";
  answer.setAttribute("aria-label", "Saved answer");
  
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-item-button";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => row.remove());
  
  row.append(keyInput, answer, remove);
  container.append(row);
}

function answerEditorValue(value) {
  if (value && typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value ?? "");
}

function collectAnswerMapping(container, { parseJson = false } = {}) {
  const { safe } = deps;
  const output = {};
  container.querySelectorAll(".answer-editor").forEach((row) => {
    const key = safe(row.querySelector("input")?.value);
    const raw = String(row.querySelector("textarea")?.value || "").trim();
    if (!key || !raw) return;
    
    if (parseJson && /^[\\[{]/.test(raw)) {
      try {
        output[key] = JSON.parse(raw);
        return;
      } catch (_error) {
        // Keep user-authored text when it is not valid JSON.
      }
    }
    output[key] = raw;
  });
  return output;
}

async function saveAssistantKnowledge() {
  const { els, state, apiUrls, safe } = deps;
  const payload = {
    application_answers: collectAnswerMapping(els.applicationAnswersEditor, { parseJson: true }),
    learned_answers: collectAnswerMapping(els.learnedAnswersEditor),
    cover_letter_style: els.assistantCoverStyle.value
  };
  
  els.saveAssistantKnowledgeButton.disabled = true;
  setAssistantStatus("Saving answer library...");
  
  try {
    const response = await fetch(apiUrls.assistant, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error(result.error || "Answer library save failed");
    
    const existingJobs = state.assistantPayload?.jobs || [];
    state.assistantPayload = { ...result.data, jobs: result.data.jobs?.length ? result.data.jobs : existingJobs };
    renderAssistant();
    setAssistantStatus("Answer library saved.", "success");
  } catch (error) {
    setAssistantStatus(safe(error.message) || "Answer library could not be saved.", "error");
  } finally {
    els.saveAssistantKnowledgeButton.disabled = false;
  }
}

function selectedAssistantJob() {
  const { state, els, numeric } = deps;
  const jobs = Array.isArray(state.assistantPayload?.jobs) ? state.assistantPayload.jobs : [];
  return jobs[numeric(els.assistantJobSelect.value)] || null;
}

async function generateAssistantDraft(mode) {
  const { els, state, apiUrls, safe } = deps;
  const job = selectedAssistantJob();
  
  if (!job) {
    setAssistantStatus("Choose a job before creating a draft.", "error");
    return;
  }
  
  const button = mode === "ai" ? els.createAiDraftButton : els.createLocalDraftButton;
  button.disabled = true;
  setAssistantStatus(mode === "ai" ? "Improving draft with Claude..." : "Creating local draft...");
  
  try {
    const response = await fetch(apiUrls.assistant + "/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job, mode })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error(result.error || "Draft generation failed");
    
    els.assistantDraft.value = result.data?.draft || "";
    setAssistantStatus(mode === "ai" ? "Claude draft created. Review every claim before using it." : "Free local draft created.", "success");
  } catch (error) {
    setAssistantStatus(safe(error.message) || "Draft could not be created.", "error");
  } finally {
    button.disabled = mode === "ai" && !state.assistantPayload?.ai_document_configured;
  }
}

async function findAssistantAnswer() {
  const { els, apiUrls, safe } = deps;
  const question = els.assistantQuestion.value.trim();
  
  if (!question) {
    setAssistantStatus("Enter an application question first.", "error");
    return;
  }
  
  els.findAssistantAnswerButton.disabled = true;
  els.assistantAnswerResult.textContent = "Checking saved profile facts...";
  
  try {
    const response = await fetch(apiUrls.assistant + "/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        context: els.assistantQuestionContext.value
      })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error(result.error || "Answer lookup failed");
    
    const data = result.data || {};
    els.assistantAnswerResult.textContent = data.answer || data.message || "No saved answer found.";
    setAssistantStatus(data.needs_ai ? "No deterministic answer found. Human review is required." : "Answer found in saved profile data.", data.needs_ai ? "" : "success");
  } catch (error) {
    els.assistantAnswerResult.textContent = safe(error.message) || "Answer lookup failed.";
    setAssistantStatus("Answer lookup failed.", "error");
  } finally {
    els.findAssistantAnswerButton.disabled = false;
  }
}

async function copyAssistantDraft() {
  const { els } = deps;
  const text = els.assistantDraft.value.trim();
  if (!text) return;
  
  await navigator.clipboard.writeText(text);
  setAssistantStatus("Draft copied to clipboard.", "success");
}

function downloadAssistantDraft() {
  const { els, safe } = deps;
  const text = els.assistantDraft.value.trim();
  if (!text) return;
  
  const job = selectedAssistantJob() || {};
  const filename = `${safe(job.company) || "company"}-${safe(job.title) || "cover-letter"}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) + ".txt";
    
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text + "\n"], { type: "text/plain;charset=utf-8" }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function setAssistantStatus(message, kind = "") {
  const { els } = deps;
  if (!els.assistantStatus) return;
  els.assistantStatus.textContent = message;
  els.assistantStatus.className = "profile-status" + (kind ? " " + kind : "");
}
