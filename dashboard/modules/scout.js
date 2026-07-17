const WORKFLOW_HINTS = Object.freeze({
  linkedin_multi_fresh: [
    "Recommended daily workflow",
    "Searches the saved query list, skips known jobs, and keeps going when early pages are mostly duplicates.",
  ],
  linkedin_ai_fresh: [
    "AI generated queries (fresh)",
    "Uses AI to dynamically generate a randomized, distinct list of job search queries based on your CV, strategy, and language settings, running in smart fresh mode.",
  ],
  linkedin_ai: [
    "AI generated queries",
    "Uses AI to dynamically generate a randomized, distinct list of job search queries based on your CV, strategy, and language settings.",
  ],
  linkedin_single: [
    "Focused search",
    "Use this when you want one title or phrase only, such as product coordinator or UX designer.",
  ],
  linkedin_process_only: [
    "Score existing collected jobs",
    "Runs the analysis pipeline on saved job records without opening LinkedIn search pages.",
  ],
  indeed_description: [
    "Indeed description extraction",
    "Opens Indeed for manual login and accessible pages only; verification and login stay manual.",
  ],
  validate_boards: [
    "Validation only - no applications",
    "Opens enabled job boards and checks their selectors. This fixed workflow cannot apply to jobs or submit an application.",
  ],
});

export function workflowPresentation(workflow, { runControlAvailable, resumeAvailable }) {
  const validationOnly = workflow === "validate_boards";
  const needsQuery = ["linkedin_single", "indeed_description"].includes(workflow);
  const needsAiQueryCount = ["linkedin_ai_fresh", "linkedin_ai"].includes(workflow);
  const supportsFresh = !["indeed_description", "linkedin_process_only", "validate_boards"].includes(workflow);
  return {
    validationOnly,
    needsQuery,
    needsAiQueryCount,
    supportsFresh,
    disableLocation: validationOnly,
    disablePages: validationOnly,
    disableBrowser: validationOnly,
    disableHumanMode: validationOnly,
    disableResume: validationOnly || !runControlAvailable || !resumeAvailable,
    hint: WORKFLOW_HINTS[workflow] || [
      "Approved workflow",
      "Runs through the local dashboard controller using a fixed safe command template.",
    ],
    startLabel: validationOnly ? "Start validation" : "Start run",
    startIcon: validationOnly ? "search" : "play",
  };
}

export function configuredProviderSummary(aiSettings) {
  const configured = Array.isArray(aiSettings?.providers)
    ? aiSettings.providers.filter((provider) => provider.configured)
    : [];
  return configured.length
    ? `Configured: ${configured.map((provider) => provider.label).join(", ")}.`
    : "No configured AI provider was detected.";
}
