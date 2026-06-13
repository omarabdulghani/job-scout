import {
  URLS,
  POLL_MS,
  THEME_STORAGE_KEY,
  initialTheme,
  safe,
  numeric,
  labelize,
  formatDateTime,
} from "./modules/core.js";
import {
  DECISIONS,
  MANUAL_STATUSES,
  APPLY_METHODS,
  QUICK_PRESETS,
  QUICK_PRESET_ICONS,
  SUMMARY_ICONS,
  DECISION_ICONS,
  buildJobsQuery,
} from "./modules/jobs.js";
import {
  resolvePage,
  workspaceLabel,
  pageDocumentTitle,
} from "./modules/navigation.js";
import {
  PROFILE_EXPERIENCE_FIELDS,
  PROFILE_EDUCATION_FIELDS,
  PROFILE_LANGUAGE_FIELDS,
  PROFILE_READINESS_LABELS,
} from "./modules/profile.js";
import {
  workflowPresentation,
  configuredProviderSummary,
} from "./modules/scout.js";
import {
  buildApplicationsQuery,
  applicationStageSummary,
} from "./modules/applications.js";
import { boardDefaults, providerStatus } from "./modules/settings.js";
import { diagnosticOverview } from "./modules/maintenance.js?v=20260613-interrupted-lifecycle";
import {
  listEditorText,
  splitListEditor,
} from "./modules/list-editor.js";

const DATA_URL = URLS.dataFile;
const API_DATA_URL = URLS.dashboardData;
const API_JOBS_URL = URLS.jobs;
const API_STATUS_URL = URLS.jobStatus;
const API_RUN_CONTROL_URL = URLS.runControl;
const API_PROFILE_URL = URLS.profile;
const API_STRATEGY_URL = URLS.strategy;
const API_AI_SETTINGS_URL = URLS.aiSettings;
const API_BOARD_SETTINGS_URL = URLS.boardSettings;
const API_APPLICATIONS_URL = URLS.applications;
const API_ASSISTANT_URL = URLS.assistant;
const API_MAINTENANCE_URL = URLS.maintenance;
const API_LEGACY_TOOLS_URL = URLS.legacyTools;
const DEFAULT_THEME = initialTheme();

    const state = {
      data: emptyData(),
      apiAvailable: false,
      runControlAvailable: false,
      runControl: null,
      jobsLoading: false,
      jobsTotal: 0,
      jobsHasMore: false,
      jobsByDecision: {},
      jobsRequestId: 0,
      jobsSearchTimer: null,
      profilePayload: null,
      profileLoading: false,
      strategyPayload: null,
      strategyLoading: false,
      aiSettingsPayload: null,
      aiSettingsLoading: false,
      boardSettingsPayload: null,
      boardSettingsLoading: false,
      applicationsPayload: null,
      applicationsLoading: false,
      applicationFilters: { search: "", stage: "all" },
      applicationSearchTimer: null,
      assistantPayload: null,
      assistantLoading: false,
      maintenancePayload: null,
      maintenanceLoading: false,
      legacyToolsPayload: null,
      legacyToolsLoading: false,
      selectedLogText: "",
      savingJobKey: "",
      toastTimer: null,
      manualUndoStack: [],
      expandedFreshRuns: new Set(),
      runHistoryExpanded: false,
      lastFocusedBeforeModal: null,
      mobileNavLastFocus: null,
      theme: DEFAULT_THEME,
      currentPage: localStorage.getItem("jobScoutCurrentPage") || "jobs",
      filters: {
        search: "",
        actionScope: "needs_action",
        run: "all",
        decision: "all",
        domain: "all",
        flag: "all",
        applyMethod: "all",
        manualStatus: "all",
        sort: "newest",
        viewMode: "board",
        quickPreset: ""
      }
    };

    const els = {
      appSidebar: document.getElementById("appSidebar"),
      appNavigation: document.getElementById("appNavigation"),
      appNavButtons: Array.from(document.querySelectorAll("[data-app-page]")),
      appPages: Array.from(document.querySelectorAll("[data-page-id]")),
      mobileNavBackdrop: document.getElementById("mobileNavBackdrop"),
      mobileNavToggle: document.getElementById("mobileNavToggle"),
      mobileWorkspaceTitle: document.getElementById("mobileWorkspaceTitle"),
      homeSetupHealth: document.getElementById("homeSetupHealth"),
      homeSetupValue: document.getElementById("homeSetupValue"),
      openProfileSetupButton: document.getElementById("openProfileSetupButton"),
      homeStartScoutButton: document.getElementById("homeStartScoutButton"),
      homeReviewJobsButton: document.getElementById("homeReviewJobsButton"),
      homeApplicationsButton: document.getElementById("homeApplicationsButton"),
      homeRunDetailsButton: document.getElementById("homeRunDetailsButton"),
      homeTrackApplicationsButton: document.getElementById("homeTrackApplicationsButton"),
      homeRunsButton: document.getElementById("homeRunsButton"),
      homeFocusTitle: document.getElementById("homeFocusTitle"),
      homeFocusCopy: document.getElementById("homeFocusCopy"),
      homeActionableCount: document.getElementById("homeActionableCount"),
      homeApplyCount: document.getElementById("homeApplyCount"),
      homeGoodCount: document.getElementById("homeGoodCount"),
      homeRunBadge: document.getElementById("homeRunBadge"),
      homeRunTitle: document.getElementById("homeRunTitle"),
      homeRunCopy: document.getElementById("homeRunCopy"),
      homeAppliedValue: document.getElementById("homeAppliedValue"),
      homeAppliedCopy: document.getElementById("homeAppliedCopy"),
      homeLatestRunValue: document.getElementById("homeLatestRunValue"),
      homeLatestRunCopy: document.getElementById("homeLatestRunCopy"),
      saveProfileButton: document.getElementById("saveProfileButton"),
      profileStatus: document.getElementById("profileStatus"),
      profileForm: document.getElementById("profileForm"),
      profileReadinessRing: document.getElementById("profileReadinessRing"),
      profileReadinessList: document.getElementById("profileReadinessList"),
      activeCvName: document.getElementById("activeCvName"),
      activeCvSize: document.getElementById("activeCvSize"),
      cvUploadInput: document.getElementById("cvUploadInput"),
      uploadCvButton: document.getElementById("uploadCvButton"),
      openCvPreview: document.getElementById("openCvPreview"),
      cvExtractedText: document.getElementById("cvExtractedText"),
      addExperienceButton: document.getElementById("addExperienceButton"),
      experienceRepeater: document.getElementById("experienceRepeater"),
      addEducationButton: document.getElementById("addEducationButton"),
      educationRepeater: document.getElementById("educationRepeater"),
      addLanguageButton: document.getElementById("addLanguageButton"),
      languageRepeater: document.getElementById("languageRepeater"),
      saveStrategyButton: document.getElementById("saveStrategyButton"),
      strategyForm: document.getElementById("strategyForm"),
      strategyStatus: document.getElementById("strategyStatus"),
      strategyQueryCount: document.getElementById("strategyQueryCount"),
      strategyQueryLearningSummary: document.getElementById("strategyQueryLearningSummary"),
      openScoutWorkspaceRunButton: document.getElementById("openScoutWorkspaceRunButton"),
      startRecommendedScoutButton: document.getElementById("startRecommendedScoutButton"),
      openSearchStrategyButton: document.getElementById("openSearchStrategyButton"),
      openAiSettingsButton: document.getElementById("openAiSettingsButton"),
      resumeScoutButton: document.getElementById("resumeScoutButton"),
      scoutWorkspaceEyebrow: document.getElementById("scoutWorkspaceEyebrow"),
      scoutWorkspaceStatus: document.getElementById("scoutWorkspaceStatus"),
      scoutWorkspaceDetail: document.getElementById("scoutWorkspaceDetail"),
      scoutWorkspaceBadge: document.getElementById("scoutWorkspaceBadge"),
      scoutQueryCount: document.getElementById("scoutQueryCount"),
      scoutLocationSummary: document.getElementById("scoutLocationSummary"),
      scoutAiBackend: document.getElementById("scoutAiBackend"),
      scoutAiFallbacks: document.getElementById("scoutAiFallbacks"),
      scoutResumeStatus: document.getElementById("scoutResumeStatus"),
      refreshLegacyStatsButton: document.getElementById("refreshLegacyStatsButton"),
      legacyToolsStatus: document.getElementById("legacyToolsStatus"),
      legacyApplicationCount: document.getElementById("legacyApplicationCount"),
      legacyTodayCount: document.getElementById("legacyTodayCount"),
      legacyReviewCount: document.getElementById("legacyReviewCount"),
      legacySeenCount: document.getElementById("legacySeenCount"),
      validateBoardsButton: document.getElementById("validateBoardsButton"),
      saveAiSettingsButton: document.getElementById("saveAiSettingsButton"),
      aiSettingsStatus: document.getElementById("aiSettingsStatus"),
      aiBackend: document.getElementById("aiBackend"),
      aiRateLimitCooldown: document.getElementById("aiRateLimitCooldown"),
      aiEnvironmentStatus: document.getElementById("aiEnvironmentStatus"),
      aiSecurityNote: document.getElementById("aiSecurityNote"),
      aiFallbackOrder: document.getElementById("aiFallbackOrder"),
      aiProviderGrid: document.getElementById("aiProviderGrid"),
      saveBoardSettingsButton: document.getElementById("saveBoardSettingsButton"),
      boardSettingsStatus: document.getElementById("boardSettingsStatus"),
      boardLinkedinEnabled: document.getElementById("boardLinkedinEnabled"),
      boardLinkedinEasyApplyOnly: document.getElementById("boardLinkedinEasyApplyOnly"),
      boardLinkedinDistance: document.getElementById("boardLinkedinDistance"),
      boardLinkedinCollect: document.getElementById("boardLinkedinCollect"),
      boardIndeedEnabled: document.getElementById("boardIndeedEnabled"),
      boardIndeedUrl: document.getElementById("boardIndeedUrl"),
      boardIndeedRadius: document.getElementById("boardIndeedRadius"),
      boardIndeedCollect: document.getElementById("boardIndeedCollect"),
      boardDefaultBrowser: document.getElementById("boardDefaultBrowser"),
      boardDefaultLocation: document.getElementById("boardDefaultLocation"),
      boardDefaultAiBudget: document.getElementById("boardDefaultAiBudget"),
      boardDefaultHuman: document.getElementById("boardDefaultHuman"),
      boardDefaultFresh: document.getElementById("boardDefaultFresh"),
      behaviorPauseSubmit: document.getElementById("behaviorPauseSubmit"),
      behaviorSkipApplied: document.getElementById("behaviorSkipApplied"),
      behaviorCoverLetter: document.getElementById("behaviorCoverLetter"),
      behaviorGenerateCoverLetter: document.getElementById("behaviorGenerateCoverLetter"),
      behaviorQuestions: document.getElementById("behaviorQuestions"),
      behaviorPauseUnknown: document.getElementById("behaviorPauseUnknown"),
      behaviorHumanDelays: document.getElementById("behaviorHumanDelays"),
      limitApplicationsRun: document.getElementById("limitApplicationsRun"),
      limitJobsRun: document.getElementById("limitJobsRun"),
      limitApplicationsDay: document.getElementById("limitApplicationsDay"),
      refreshApplicationsButton: document.getElementById("refreshApplicationsButton"),
      applicationsStatus: document.getElementById("applicationsStatus"),
      applicationStatTotal: document.getElementById("applicationStatTotal"),
      applicationStatPreparing: document.getElementById("applicationStatPreparing"),
      applicationStatApplied: document.getElementById("applicationStatApplied"),
      applicationStatInterview: document.getElementById("applicationStatInterview"),
      applicationStatOffer: document.getElementById("applicationStatOffer"),
      applicationSearch: document.getElementById("applicationSearch"),
      applicationStageFilter: document.getElementById("applicationStageFilter"),
      applicationsTableBody: document.getElementById("applicationsTableBody"),
      applicationsEmpty: document.getElementById("applicationsEmpty"),
      applicationsTableFooter: document.getElementById("applicationsTableFooter"),
      applicationsVisibleCount: document.getElementById("applicationsVisibleCount"),
      loadMoreApplicationsButton: document.getElementById("loadMoreApplicationsButton"),
      saveAssistantKnowledgeButton: document.getElementById("saveAssistantKnowledgeButton"),
      assistantStatus: document.getElementById("assistantStatus"),
      addApplicationAnswerButton: document.getElementById("addApplicationAnswerButton"),
      applicationAnswersEditor: document.getElementById("applicationAnswersEditor"),
      addLearnedAnswerButton: document.getElementById("addLearnedAnswerButton"),
      learnedAnswersEditor: document.getElementById("learnedAnswersEditor"),
      assistantQuestion: document.getElementById("assistantQuestion"),
      assistantQuestionContext: document.getElementById("assistantQuestionContext"),
      findAssistantAnswerButton: document.getElementById("findAssistantAnswerButton"),
      assistantAnswerResult: document.getElementById("assistantAnswerResult"),
      assistantJobSelect: document.getElementById("assistantJobSelect"),
      assistantCoverStyle: document.getElementById("assistantCoverStyle"),
      createLocalDraftButton: document.getElementById("createLocalDraftButton"),
      createAiDraftButton: document.getElementById("createAiDraftButton"),
      assistantAiNote: document.getElementById("assistantAiNote"),
      assistantDraft: document.getElementById("assistantDraft"),
      copyAssistantDraftButton: document.getElementById("copyAssistantDraftButton"),
      downloadAssistantDraftButton: document.getElementById("downloadAssistantDraftButton"),
      refreshMaintenanceButton: document.getElementById("refreshMaintenanceButton"),
      maintenanceStatus: document.getElementById("maintenanceStatus"),
      diagnosticWorkspace: document.getElementById("diagnosticWorkspace"),
      diagnosticDatabase: document.getElementById("diagnosticDatabase"),
      diagnosticResume: document.getElementById("diagnosticResume"),
      diagnosticPersistence: document.getElementById("diagnosticPersistence"),
      diagnosticLogs: document.getElementById("diagnosticLogs"),
      diagnosticRuns: document.getElementById("diagnosticRuns"),
      latestRunIncident: document.getElementById("latestRunIncident"),
      latestDiagnosticError: document.getElementById("latestDiagnosticError"),
      latestPersistenceWarning: document.getElementById("latestPersistenceWarning"),
      maintenanceLogList: document.getElementById("maintenanceLogList"),
      createBackupButton: document.getElementById("createBackupButton"),
      pruneLogsButton: document.getElementById("pruneLogsButton"),
      maintenanceBackupList: document.getElementById("maintenanceBackupList"),
      selectedLogTitle: document.getElementById("selectedLogTitle"),
      selectedLogMeta: document.getElementById("selectedLogMeta"),
      copyLogButton: document.getElementById("copyLogButton"),
      maintenanceLogViewer: document.getElementById("maintenanceLogViewer"),
      maintenanceRunList: document.getElementById("maintenanceRunList"),
      themeToggle: document.getElementById("themeToggle"),
      themeToggleIcon: document.getElementById("themeToggleIcon"),
      themeToggleText: document.getElementById("themeToggleText"),
      runScoutButton: document.getElementById("runScoutButton"),
      statusDot: document.getElementById("statusDot"),
      statusText: document.getElementById("statusText"),
      updatedAt: document.getElementById("updatedAt"),
      statTotal: document.getElementById("statTotal"),
      statActive: document.getElementById("statActive"),
      statApply: document.getElementById("statApply"),
      statGood: document.getElementById("statGood"),
      statLow: document.getElementById("statLow"),
      statRejected: document.getElementById("statRejected"),
      statUnreviewed: document.getElementById("statUnreviewed"),
      statApplied: document.getElementById("statApplied"),
      statIrrelevant: document.getElementById("statIrrelevant"),
      freshPanel: document.getElementById("freshPanel"),
      freshTitle: document.getElementById("freshTitle"),
      freshStatus: document.getElementById("freshStatus"),
      freshRunLabel: document.getElementById("freshRunLabel"),
      freshCompleteSummary: document.getElementById("freshCompleteSummary"),
      freshApply: document.getElementById("freshApply"),
      freshApplyBar: document.getElementById("freshApplyBar"),
      freshGood: document.getElementById("freshGood"),
      freshGoodBar: document.getElementById("freshGoodBar"),
      freshJobs: document.getElementById("freshJobs"),
      freshJobsBar: document.getElementById("freshJobsBar"),
      freshKnownSkipped: document.getElementById("freshKnownSkipped"),
      freshKnownBar: document.getElementById("freshKnownBar"),
      freshQuery: document.getElementById("freshQuery"),
      freshPage: document.getElementById("freshPage"),
      freshQueries: document.getElementById("freshQueries"),
      freshPagesScanned: document.getElementById("freshPagesScanned"),
      freshPages: document.getElementById("freshPages"),
      bestNextPanel: document.getElementById("bestNextPanel"),
      bestNextCount: document.getElementById("bestNextCount"),
      bestNextList: document.getElementById("bestNextList"),
      runHistoryPanel: document.getElementById("runHistoryPanel"),
      toggleRunHistoryButton: document.getElementById("toggleRunHistoryButton"),
      runHistoryList: document.getElementById("runHistoryList"),
      quickPresets: document.getElementById("quickPresets"),
      filterHint: document.getElementById("filterHint"),
      searchInput: document.getElementById("searchInput"),
      actionFilter: document.getElementById("actionFilter"),
      runFilter: document.getElementById("runFilter"),
      decisionFilter: document.getElementById("decisionFilter"),
      domainFilter: document.getElementById("domainFilter"),
      flagFilter: document.getElementById("flagFilter"),
      applyMethodFilter: document.getElementById("applyMethodFilter"),
      manualStatusFilter: document.getElementById("manualStatusFilter"),
      sortFilter: document.getElementById("sortFilter"),
      boardViewButton: document.getElementById("boardViewButton"),
      listViewButton: document.getElementById("listViewButton"),
      undoButton: document.getElementById("undoButton"),
      refreshButton: document.getElementById("refreshButton"),
      boardView: document.getElementById("boardView"),
      compactList: document.getElementById("compactList"),
      jobsTableFooter: document.getElementById("jobsTableFooter"),
      jobsVisibleCount: document.getElementById("jobsVisibleCount"),
      loadMoreJobsButton: document.getElementById("loadMoreJobsButton"),
      listApply: document.getElementById("listApply"),
      listGood: document.getElementById("listGood"),
      listLow: document.getElementById("listLow"),
      listRejected: document.getElementById("listRejected"),
      countApply: document.getElementById("countApply"),
      countGood: document.getElementById("countGood"),
      countLow: document.getElementById("countLow"),
      countRejected: document.getElementById("countRejected"),
      toast: document.getElementById("toast"),
      runScoutOverlay: document.getElementById("runScoutOverlay"),
      closeRunScoutButton: document.getElementById("closeRunScoutButton"),
      runControlNotice: document.getElementById("runControlNotice"),
      runWorkflowHint: document.getElementById("runWorkflowHint"),
      runWorkflow: document.getElementById("runWorkflow"),
      runLocation: document.getElementById("runLocation"),
      runQuery: document.getElementById("runQuery"),
      runMaxPages: document.getElementById("runMaxPages"),
      runBrowser: document.getElementById("runBrowser"),
      runHumanMode: document.getElementById("runHumanMode"),
      runFreshMode: document.getElementById("runFreshMode"),
      runAiBudgetMode: document.getElementById("runAiBudgetMode"),
      runResumeMode: document.getElementById("runResumeMode"),
      startRunButton: document.getElementById("startRunButton"),
      refreshRunControlButton: document.getElementById("refreshRunControlButton"),
      runStatusText: document.getElementById("runStatusText"),
      runStatusBadge: document.getElementById("runStatusBadge"),
      stopAfterJobButton: document.getElementById("stopAfterJobButton"),
      stopAfterPageButton: document.getElementById("stopAfterPageButton"),
      stopNowButton: document.getElementById("stopNowButton"),
      runLogTail: document.getElementById("runLogTail")
    };

    function usesMobileNavigation() {
      return window.matchMedia("(max-width: 900px)").matches;
    }

    function openMobileNavigation() {
      if (!usesMobileNavigation()) return;
      state.mobileNavLastFocus = document.activeElement;
      els.appSidebar.classList.add("mobile-open");
      els.mobileNavBackdrop.classList.add("visible");
      els.mobileNavToggle.setAttribute("aria-expanded", "true");
      els.mobileNavToggle.setAttribute("aria-label", "Close workspace navigation");
      els.appSidebar.removeAttribute("aria-hidden");
      document.body.classList.add("mobile-nav-open");
      const active = els.appNavButtons.find((button) => button.classList.contains("active"))
        || els.appNavButtons[0];
      if (active) active.focus();
    }

    function closeMobileNavigation({ restoreFocus = true } = {}) {
      els.appSidebar.classList.remove("mobile-open");
      els.mobileNavBackdrop.classList.remove("visible");
      els.mobileNavToggle.setAttribute("aria-expanded", "false");
      els.mobileNavToggle.setAttribute("aria-label", "Open workspace navigation");
      document.body.classList.remove("mobile-nav-open");
      if (usesMobileNavigation()) {
        els.appSidebar.setAttribute("aria-hidden", "true");
      } else {
        els.appSidebar.removeAttribute("aria-hidden");
      }
      if (restoreFocus && state.mobileNavLastFocus && typeof state.mobileNavLastFocus.focus === "function") {
        state.mobileNavLastFocus.focus();
      }
      state.mobileNavLastFocus = null;
    }

    function trapMobileNavigationFocus(event) {
      if (event.key !== "Tab" || !els.appSidebar.classList.contains("mobile-open")) return;
      const candidates = Array.from(
        els.appSidebar.querySelectorAll(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => !element.hidden && element.offsetParent !== null);
      if (!candidates.length) {
        event.preventDefault();
        return;
      }
      const first = candidates[0];
      const last = candidates[candidates.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    function syncMobileNavigation() {
      if (usesMobileNavigation()) {
        if (!els.appSidebar.classList.contains("mobile-open")) {
          els.appSidebar.setAttribute("aria-hidden", "true");
        }
      } else {
        closeMobileNavigation({ restoreFocus: false });
      }
    }

    function navigateToPage(pageId, { persist = true } = {}) {
      const resolvedPage = resolvePage(pageId, els.appPages);
      const mobileNavigationWasOpen = els.appSidebar.classList.contains("mobile-open");
      state.currentPage = resolvedPage;
      for (const page of els.appPages) {
        page.hidden = page.dataset.pageId !== resolvedPage;
      }
      for (const button of els.appNavButtons) {
        const active = button.dataset.appPage === resolvedPage;
        button.classList.toggle("active", active);
        if (active) {
          button.setAttribute("aria-current", "page");
        } else {
          button.removeAttribute("aria-current");
        }
      }
      const activeButton = els.appNavButtons.find((button) => button.dataset.appPage === resolvedPage);
      if (els.mobileWorkspaceTitle) {
        els.mobileWorkspaceTitle.textContent = workspaceLabel(activeButton, resolvedPage, labelize);
      }
      if (mobileNavigationWasOpen) {
        closeMobileNavigation({ restoreFocus: false });
        const currentHeading = els.appPages
          .find((page) => page.dataset.pageId === resolvedPage)
          ?.querySelector("h1");
        if (currentHeading) {
          currentHeading.setAttribute("tabindex", "-1");
          currentHeading.focus();
        }
      }
      if (persist) {
        localStorage.setItem("jobScoutCurrentPage", resolvedPage);
      }
      document.title = pageDocumentTitle(resolvedPage, labelize);
      if (resolvedPage === "profile" && !state.profilePayload && !state.profileLoading) {
        loadProfileData();
      }
      if (resolvedPage === "home" && !state.profilePayload && !state.profileLoading) {
        loadProfileData();
      }
      if (resolvedPage === "strategy" && !state.strategyPayload && !state.strategyLoading) {
        loadStrategyData();
      }
      if (resolvedPage === "settings" && !state.aiSettingsPayload && !state.aiSettingsLoading) {
        loadAiSettings();
      }
      if (resolvedPage === "settings" && !state.boardSettingsPayload && !state.boardSettingsLoading) {
        loadBoardSettings();
      }
      if (resolvedPage === "applications" && !state.applicationsLoading) {
        loadApplications();
      }
      if (resolvedPage === "assistant" && !state.assistantPayload && !state.assistantLoading) {
        loadAssistant();
      }
      if (resolvedPage === "runs" && !state.maintenanceLoading) {
        loadMaintenance();
      }
      if (resolvedPage === "scout") {
        loadRunControl();
        if (!state.strategyPayload && !state.strategyLoading) loadStrategyData();
        if (!state.aiSettingsPayload && !state.aiSettingsLoading) loadAiSettings();
        if (!state.legacyToolsPayload && !state.legacyToolsLoading) loadLegacyTools();
        renderScoutWorkspace();
      }
      if (resolvedPage === "home") {
        renderHome();
      }
    }

    async function loadProfileData() {
      state.profileLoading = true;
      setProfileStatus("Loading your private profile...");
      try {
        const response = await fetch(API_PROFILE_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.profilePayload = await response.json();
        renderProfileEditor();
      } catch (error) {
        setProfileStatus("Profile could not be loaded: " + (safe(error.message) || "unknown error"), "error");
      } finally {
        state.profileLoading = false;
      }
      renderHome();
    }

    function renderProfileEditor() {
      const payload = state.profilePayload || {};
      const profile = payload.profile || {};
      const personal = profile.personal || {};
      const location = personal.location || {};
      const salary = profile.salary || {};
      const availability = profile.availability || {};
      const authorization = profile.work_authorization || {};

      setFieldValue("profileFirstName", personal.first_name);
      setFieldValue("profileLastName", personal.last_name);
      setFieldValue("profileGender", personal.gender);
      setFieldValue("profileEmail", personal.email);
      setFieldValue("profilePhone", personal.phone);
      setFieldValue("profilePostalCode", location.postal_code);
      setFieldValue("profileCity", location.city);
      setFieldValue("profileCountry", location.country);
      setFieldValue("profileAbout", profile.about_me);
      setFieldValue("profileLinkedin", personal.linkedin_url);
      setFieldValue("profilePortfolio", personal.portfolio_url);
      setFieldValue("profileGithub", personal.github_url);
      setFieldValue("profileCoverLetterStyle", profile.cover_letter_style);
      setFieldValue("profileSkills", listEditorText(profile.skills));
      setFieldValue("profileTools", listEditorText(profile.tools));
      setFieldValue("profileCertifications", listEditorText(profile.certifications));
      setFieldValue("profileSalaryMinimum", salary.minimum);
      setFieldValue("profileSalaryTarget", salary.target);
      setFieldValue("profileSalaryCurrency", salary.currency || "EUR");
      setFieldValue("profileStartDate", availability.start_date);
      setFieldValue("profileNoticeWeeks", availability.notice_period_weeks);
      setFieldValue("profileVisaStatus", authorization.visa_status);
      setFieldValue("profileWorkAuthorization", authorization.summary);

      renderStructuredRepeater(
        els.experienceRepeater,
        profile.work_experience || [],
        "experience",
        PROFILE_EXPERIENCE_FIELDS
      );
      renderStructuredRepeater(
        els.educationRepeater,
        profile.education || [],
        "education",
        PROFILE_EDUCATION_FIELDS
      );
      renderStructuredRepeater(
        els.languageRepeater,
        profile.languages || [],
        "language",
        PROFILE_LANGUAGE_FIELDS
      );
      renderProfileReadiness(payload.readiness || {});
      renderCv(payload.cv || {});
      setProfileStatus("Changes are stored only in your private local workspace.");
    }

    function renderProfileReadiness(readiness) {
      const percent = numeric(readiness.percent);
      els.profileReadinessRing.style.setProperty("--readiness", percent + "%");
      els.profileReadinessRing.dataset.label = percent + "%";
      els.profileReadinessList.replaceChildren();
      for (const [key, label] of Object.entries(PROFILE_READINESS_LABELS)) {
        const complete = Boolean((readiness.checks || {})[key]);
        const item = document.createElement("li");
        item.className = complete ? "complete" : "";
        const name = document.createElement("span");
        name.textContent = label;
        const value = document.createElement("strong");
        value.textContent = complete ? "Ready" : "Missing";
        item.append(name, value);
        els.profileReadinessList.append(item);
      }
      if (els.homeSetupHealth) {
        els.homeSetupHealth.textContent = readiness.ready
          ? "Your profile and CV are ready for scoring."
          : `${readiness.completed || 0} of ${readiness.total || 0} profile checks are complete.`;
      }
    }

    function renderCv(cv) {
      const available = Boolean(cv.available);
      els.activeCvName.textContent = available ? safe(cv.filename) : "No CV selected";
      els.activeCvSize.textContent = available ? formatFileSize(cv.size_bytes) : "Upload a PDF to enable CV-aware scoring.";
      els.openCvPreview.classList.toggle("hidden", !available);
      els.cvExtractedText.textContent = safe(cv.extracted_text) || "No readable CV text is available.";
    }

    function renderStructuredRepeater(container, items, kind, fields) {
      container.replaceChildren();
      for (const item of items) {
        container.append(createRepeaterItem(kind, item, fields));
      }
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "subline";
        empty.textContent = "No entries yet.";
        container.append(empty);
      }
    }

    function createRepeaterItem(kind, item, fields) {
      const wrapper = document.createElement("article");
      wrapper.className = "repeater-item";
      wrapper.dataset.repeaterKind = kind;
      const head = document.createElement("div");
      head.className = "repeater-item-head";
      const title = document.createElement("strong");
      title.textContent = labelize(kind);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove-item-button";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => wrapper.remove());
      head.append(title, remove);
      wrapper.append(head);

      const grid = document.createElement("div");
      grid.className = "form-grid";
      for (const [key, label, fieldType] of fields) {
        const field = document.createElement("div");
        field.className = "field" + (fieldType === "textarea" ? " full" : "");
        const fieldLabel = document.createElement("label");
        fieldLabel.textContent = label;
        const input = document.createElement(fieldType === "textarea" ? "textarea" : "input");
        input.dataset.profileField = key;
        input.value = safe(item[key]);
        field.append(fieldLabel, input);
        grid.append(field);
      }
      wrapper.append(grid);
      return wrapper;
    }

    function collectRepeater(container) {
      return Array.from(container.querySelectorAll(".repeater-item")).map((item) => {
        const record = {};
        for (const input of item.querySelectorAll("[data-profile-field]")) {
          record[input.dataset.profileField] = safe(input.value);
        }
        return record;
      });
    }

    function addRepeaterEntry(container, kind, fields) {
      const empty = container.querySelector(".subline");
      if (empty) empty.remove();
      container.append(createRepeaterItem(kind, {}, fields));
    }

    async function saveProfile() {
      if (!state.profilePayload || !els.profileForm.reportValidity()) return;
      const profile = JSON.parse(JSON.stringify(state.profilePayload.profile || {}));
      profile.personal = profile.personal || {};
      profile.personal.location = profile.personal.location || {};
      profile.personal.first_name = fieldValue("profileFirstName");
      profile.personal.last_name = fieldValue("profileLastName");
      profile.personal.gender = fieldValue("profileGender");
      profile.personal.email = fieldValue("profileEmail");
      profile.personal.phone = fieldValue("profilePhone");
      profile.personal.location.postal_code = fieldValue("profilePostalCode");
      profile.personal.location.city = fieldValue("profileCity");
      profile.personal.location.country = fieldValue("profileCountry");
      profile.personal.linkedin_url = fieldValue("profileLinkedin");
      profile.personal.portfolio_url = fieldValue("profilePortfolio");
      profile.personal.github_url = fieldValue("profileGithub");
      profile.about_me = fieldValue("profileAbout");
      profile.cover_letter_style = fieldValue("profileCoverLetterStyle");
      profile.work_experience = collectRepeater(els.experienceRepeater);
      profile.education = collectRepeater(els.educationRepeater);
      profile.languages = collectRepeater(els.languageRepeater);
      profile.skills = splitListEditor(fieldValue("profileSkills"));
      profile.tools = splitListEditor(fieldValue("profileTools"));
      profile.certifications = splitListEditor(fieldValue("profileCertifications"));
      profile.salary = profile.salary || {};
      profile.salary.minimum = numeric(fieldValue("profileSalaryMinimum"));
      profile.salary.target = numeric(fieldValue("profileSalaryTarget"));
      profile.salary.currency = fieldValue("profileSalaryCurrency") || "EUR";
      profile.availability = profile.availability || {};
      profile.availability.start_date = fieldValue("profileStartDate");
      profile.availability.notice_period_weeks = numeric(fieldValue("profileNoticeWeeks"));
      profile.work_authorization = profile.work_authorization || {};
      profile.work_authorization.visa_status = fieldValue("profileVisaStatus");
      profile.work_authorization.summary = fieldValue("profileWorkAuthorization");

      els.saveProfileButton.disabled = true;
      setProfileStatus("Saving profile...");
      try {
        const response = await fetch(API_PROFILE_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "Profile save failed");
        state.profilePayload = result.data;
        renderProfileEditor();
        setProfileStatus("Profile saved. The scout will use these details on its next run.", "success");
      } catch (error) {
        setProfileStatus(safe(error.message) || "Profile could not be saved.", "error");
      } finally {
        els.saveProfileButton.disabled = false;
      }
    }

    async function uploadCv() {
      const file = els.cvUploadInput.files && els.cvUploadInput.files[0];
      if (!file) {
        setProfileStatus("Choose a PDF before uploading.", "error");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setProfileStatus("CV must be 10 MB or smaller.", "error");
        return;
      }
      els.uploadCvButton.disabled = true;
      setProfileStatus("Uploading CV...");
      try {
        const dataUrl = await readFileAsDataUrl(file);
        const response = await fetch(API_PROFILE_URL + "/cv", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: file.name,
            content_base64: dataUrl.split(",", 2)[1] || ""
          })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "CV upload failed");
        state.profilePayload = result.data;
        renderProfileEditor();
        els.cvUploadInput.value = "";
        setProfileStatus("CV uploaded and selected for future scoring.", "success");
      } catch (error) {
        setProfileStatus(safe(error.message) || "CV upload failed.", "error");
      } finally {
        els.uploadCvButton.disabled = false;
      }
    }

    function setProfileStatus(message, kind = "") {
      if (!els.profileStatus) return;
      els.profileStatus.textContent = message;
      els.profileStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    function setFieldValue(id, value) {
      const field = document.getElementById(id);
      if (field) field.value = value ?? "";
    }

    function fieldValue(id) {
      const field = document.getElementById(id);
      return field ? String(field.value || "").trim() : "";
    }

    function formatFileSize(bytes) {
      const size = numeric(bytes);
      if (!size) return "";
      if (size < 1024) return size + " bytes";
      if (size < 1024 * 1024) return Math.round(size / 1024) + " KB";
      return (size / (1024 * 1024)).toFixed(1) + " MB";
    }

    function readFileAsDataUrl(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("Could not read the selected file"));
        reader.readAsDataURL(file);
      });
    }

    async function loadStrategyData() {
      state.strategyLoading = true;
      setStrategyStatus("Loading job strategy...");
      try {
        const response = await fetch(API_STRATEGY_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.strategyPayload = await response.json();
        renderStrategyEditor();
      } catch (error) {
        setStrategyStatus("Strategy could not be loaded: " + (safe(error.message) || "unknown error"), "error");
      } finally {
        state.strategyLoading = false;
      }
    }

    function renderStrategyEditor() {
      const payload = state.strategyPayload || {};
      const career = payload.career_strategy || {};
      const preferences = payload.preferences || {};
      const fresh = preferences.fresh_scout || {};
      const learning = preferences.query_learning || {};

      setFieldValue("strategyCoreGoal", career.core_goal);
      setFieldValue("strategyOpenness", career.openness);
      setFieldValue("strategyPrimaryPaths", listEditorText(career.primary_paths));
      setFieldValue("strategyBridgeRoles", listEditorText(career.strong_bridge_roles));
      setFieldValue("strategyFallbackRoles", listEditorText(career.fallback_roles_for_income));
      setFieldValue("strategyHardBlockers", listEditorText(preferences.hard_exclude_keywords));
      setFieldValue("strategySoftRisks", listEditorText(preferences.soft_negative_keywords));
      setFieldValue("strategyFallbackKeywords", listEditorText(preferences.fallback_keywords));
      setFieldValue("strategyLocations", listEditorText(preferences.locations));
      setFieldValue("strategyCompanyBlacklist", listEditorText(preferences.companies_blacklist));
      setFieldValue("strategyCompanyWhitelist", listEditorText(preferences.companies_whitelist));
      setFieldValue("strategyApplyScore", preferences.min_match_score);
      setFieldValue("strategyReviewScore", preferences.human_review_score_min);
      setFieldValue("strategyDistance", preferences.distance_miles);
      setFieldValue("strategyPreferredSalary", preferences.salary_preferred_monthly_full_time);
      setFieldValue("strategyBridgeSalary", preferences.salary_bridge_minimum_monthly_full_time);
      setFieldValue("strategyHourlySalary", preferences.salary_part_time_hourly_minimum);
      setFieldValue("strategyCompanyLimit", preferences.max_active_applications_per_company_14_days);
      setCheckedValue("strategyAvoidUnrelated", preferences.avoid_multiple_unrelated_roles_same_company);
      setFieldValue("strategyQueries", listEditorText(payload.queries));
      setCheckedValue("strategyQueryLearningEnabled", learning.enabled !== false);
      setFieldValue("strategyExplorationInterval", learning.exploration_interval || 5);
      setFieldValue("strategyFreshMaxPages", fresh.max_pages_per_query || 4);
      setFieldValue("strategyKnownContinue", ratioPercent(fresh.known_ratio_continue_threshold, 80));
      setFieldValue("strategyDuplicateStop", ratioPercent(fresh.duplicate_heavy_stop_threshold, 90));
      setFieldValue("strategyTargetApply", fresh.target_apply_first_jobs || 8);
      setFieldValue("strategyTargetGood", fresh.target_good_or_better_jobs || 20);
      setFieldValue("strategyFreshCap", fresh.global_new_jobs_soft_cap || 140);
      setFieldValue("strategyFullText", payload.strategy_text);
      setFieldValue("strategyPortfolioNotes", payload.portfolio_notes);
      renderQueryLearningSummary(payload.query_learning || {});
      updateStrategyQueryCount();
      setStrategyStatus("Strategy changes are versioned in your private workspace.");
      renderScoutWorkspace();
    }

    function renderQueryLearningSummary(learning) {
      els.strategyQueryLearningSummary.replaceChildren();
      const title = document.createElement("strong");
      title.textContent = learning.enabled === false ? "Query learning is disabled" : "Query learning is active";
      const description = document.createElement("span");
      const top = Array.isArray(learning.top_queries) ? learning.top_queries.slice(0, 5) : [];
      description.textContent = top.length
        ? "Current leaders: " + top.map((item) => `${item.query} (${numeric(item.score)})`).join(", ")
        : safe(learning.reason) || "The app needs more completed runs before it can rank queries.";
      els.strategyQueryLearningSummary.append(title, description);
    }

    function updateStrategyQueryCount() {
      const queries = splitListEditor(fieldValue("strategyQueries"));
      els.strategyQueryCount.textContent = `${queries.length} quer${queries.length === 1 ? "y" : "ies"}`;
    }

    async function saveStrategy() {
      if (!state.strategyPayload || !els.strategyForm.reportValidity()) return;
      const payload = JSON.parse(JSON.stringify(state.strategyPayload));
      payload.career_strategy = payload.career_strategy || {};
      payload.career_strategy.core_goal = fieldValue("strategyCoreGoal");
      payload.career_strategy.openness = fieldValue("strategyOpenness");
      payload.career_strategy.primary_paths = splitListEditor(fieldValue("strategyPrimaryPaths"));
      payload.career_strategy.strong_bridge_roles = splitListEditor(fieldValue("strategyBridgeRoles"));
      payload.career_strategy.fallback_roles_for_income = splitListEditor(fieldValue("strategyFallbackRoles"));
      payload.preferences = payload.preferences || {};
      payload.preferences.hard_exclude_keywords = splitListEditor(fieldValue("strategyHardBlockers"));
      payload.preferences.soft_negative_keywords = splitListEditor(fieldValue("strategySoftRisks"));
      payload.preferences.fallback_keywords = splitListEditor(fieldValue("strategyFallbackKeywords"));
      payload.preferences.locations = splitListEditor(fieldValue("strategyLocations"));
      payload.preferences.companies_blacklist = splitListEditor(fieldValue("strategyCompanyBlacklist"));
      payload.preferences.companies_whitelist = splitListEditor(fieldValue("strategyCompanyWhitelist"));
      payload.preferences.min_match_score = numeric(fieldValue("strategyApplyScore"));
      payload.preferences.human_review_score_min = numeric(fieldValue("strategyReviewScore"));
      payload.preferences.distance_miles = numeric(fieldValue("strategyDistance"));
      payload.preferences.salary_preferred_monthly_full_time = numeric(fieldValue("strategyPreferredSalary"));
      payload.preferences.salary_bridge_minimum_monthly_full_time = numeric(fieldValue("strategyBridgeSalary"));
      payload.preferences.salary_part_time_hourly_minimum = numeric(fieldValue("strategyHourlySalary"));
      payload.preferences.max_active_applications_per_company_14_days = numeric(fieldValue("strategyCompanyLimit"));
      payload.preferences.avoid_multiple_unrelated_roles_same_company = checkedValue("strategyAvoidUnrelated");
      payload.preferences.query_learning = payload.preferences.query_learning || {};
      payload.preferences.query_learning.enabled = checkedValue("strategyQueryLearningEnabled");
      payload.preferences.query_learning.exploration_interval = numeric(fieldValue("strategyExplorationInterval")) || 5;
      payload.preferences.fresh_scout = payload.preferences.fresh_scout || {};
      payload.preferences.fresh_scout.max_pages_per_query = numeric(fieldValue("strategyFreshMaxPages")) || 4;
      payload.preferences.fresh_scout.known_ratio_continue_threshold = numeric(fieldValue("strategyKnownContinue")) / 100;
      payload.preferences.fresh_scout.duplicate_heavy_stop_threshold = numeric(fieldValue("strategyDuplicateStop")) / 100;
      payload.preferences.fresh_scout.target_apply_first_jobs = numeric(fieldValue("strategyTargetApply")) || 8;
      payload.preferences.fresh_scout.target_good_or_better_jobs = numeric(fieldValue("strategyTargetGood")) || 20;
      payload.preferences.fresh_scout.global_new_jobs_soft_cap = numeric(fieldValue("strategyFreshCap")) || 140;
      payload.queries = splitListEditor(fieldValue("strategyQueries"));
      payload.strategy_text = document.getElementById("strategyFullText").value;
      payload.portfolio_notes = document.getElementById("strategyPortfolioNotes").value;

      els.saveStrategyButton.disabled = true;
      setStrategyStatus("Saving strategy...");
      try {
        const response = await fetch(API_STRATEGY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "Strategy save failed");
        state.strategyPayload = result.data;
        renderStrategyEditor();
        setStrategyStatus("Strategy saved. New scout runs will use these rules and queries.", "success");
      } catch (error) {
        setStrategyStatus(safe(error.message) || "Strategy could not be saved.", "error");
      } finally {
        els.saveStrategyButton.disabled = false;
      }
    }

    function setStrategyStatus(message, kind = "") {
      els.strategyStatus.textContent = message;
      els.strategyStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    function setCheckedValue(id, value) {
      const field = document.getElementById(id);
      if (field) field.checked = Boolean(value);
    }

    function checkedValue(id) {
      const field = document.getElementById(id);
      return Boolean(field && field.checked);
    }

    function ratioPercent(value, fallback) {
      const number = Number(value);
      if (!Number.isFinite(number)) return fallback;
      return Math.round((number <= 1 ? number * 100 : number));
    }

    async function loadAiSettings() {
      state.aiSettingsLoading = true;
      setAiSettingsStatus("Loading AI settings...");
      try {
        const response = await fetch(API_AI_SETTINGS_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.aiSettingsPayload = await response.json();
        renderAiSettings();
      } catch (error) {
        setAiSettingsStatus("AI settings could not be loaded: " + (safe(error.message) || "unknown error"), "error");
      } finally {
        state.aiSettingsLoading = false;
      }
      renderScoutWorkspace();
    }

    function renderAiSettings() {
      const payload = state.aiSettingsPayload || {};
      els.aiBackend.value = payload.backend || "auto";
      els.aiRateLimitCooldown.value = numeric(payload.rate_limit_cooldown_seconds) || 90;
      els.aiEnvironmentStatus.replaceChildren();
      const envTitle = document.createElement("strong");
      envTitle.textContent = payload.env_exists ? "Local .env is active" : "No .env file yet";
      const envCopy = document.createElement("span");
      envCopy.textContent = payload.env_exists
        ? "Secrets remain on this computer."
        : "Saving a provider will create the local file.";
      els.aiEnvironmentStatus.append(envTitle, envCopy);
      els.aiSecurityNote.textContent = payload.security_note || "Stored API keys are never returned to the browser.";
      renderAiFallbackOrder();
      renderAiProviderCards();
      setAiSettingsStatus("AI settings are local. Existing key values stay hidden.");
    }

    function renderAiFallbackOrder() {
      els.aiFallbackOrder.replaceChildren();
      const payload = state.aiSettingsPayload || {};
      const providers = Array.isArray(payload.providers) ? payload.providers : [];
      const currentOrder = Array.isArray(payload.backend_order) ? payload.backend_order : [];
      providers.forEach((provider, index) => {
        const position = currentOrder.indexOf(provider.id);
        const row = document.createElement("label");
        row.className = "fallback-order-row";
        const number = document.createElement("strong");
        number.textContent = position >= 0 ? String(position + 1) : "-";
        const copy = document.createElement("span");
        copy.textContent = provider.label;
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.checked = position >= 0;
        toggle.dataset.aiOrderProvider = provider.id;
        toggle.dataset.aiOrderRank = String(position >= 0 ? position : index + providers.length);
        toggle.setAttribute("aria-label", "Use " + provider.label + " in automatic fallback");
        toggle.addEventListener("change", renderAiFallbackOrderNumbers);
        row.append(number, copy, toggle);
        els.aiFallbackOrder.append(row);
      });
    }

    function renderAiFallbackOrderNumbers() {
      const rows = Array.from(els.aiFallbackOrder.querySelectorAll(".fallback-order-row"));
      let rank = 0;
      rows.forEach((row) => {
        const toggle = row.querySelector("input");
        const number = row.querySelector("strong");
        if (toggle && toggle.checked) {
          rank += 1;
          number.textContent = String(rank);
          toggle.dataset.aiOrderRank = String(rank - 1);
        } else {
          number.textContent = "-";
        }
      });
    }

    function renderAiProviderCards() {
      els.aiProviderGrid.replaceChildren();
      const providers = Array.isArray(state.aiSettingsPayload?.providers)
        ? state.aiSettingsPayload.providers
        : [];
      providers.forEach((provider) => {
        const status = providerStatus(provider);
        const card = document.createElement("article");
        card.className = "provider-card";
        card.dataset.providerId = provider.id;
        card.dataset.configured = String(status.configured);

        const head = document.createElement("div");
        head.className = "provider-card-head";
        const titleWrap = document.createElement("div");
        const title = document.createElement("h2");
        title.textContent = provider.label;
        const copy = document.createElement("div");
        copy.className = "provider-copy";
        copy.textContent = provider.description;
        titleWrap.append(title, copy);
        const badge = document.createElement("span");
        badge.className = "provider-status " + (status.configured ? "configured" : "");
        badge.textContent = status.label;
        head.append(titleWrap, badge);

        const grid = document.createElement("div");
        grid.className = "form-grid";
        grid.append(
          createAiField(provider, "model", "Model", provider.model || "", "text"),
          createAiField(provider, "base_url", "Base URL", provider.base_url || "", "url", !provider.base_url && provider.id !== "gemini" && provider.id !== "claude")
        );
        if (!provider.base_url && ["gemini", "claude"].includes(provider.id)) {
          grid.lastElementChild.remove();
          grid.firstElementChild.classList.add("full");
        }
        if (provider.requires_key) {
          const keyField = createAiField(provider, "api_key", "API key", "", "password");
          keyField.classList.add("full");
          const input = keyField.querySelector("input");
          input.placeholder = provider.configured ? "Configured - enter a new key to replace it" : "Enter API key";
          const note = document.createElement("span");
          note.className = "secret-field-note";
          note.textContent = provider.configured
            ? "The existing key is hidden. Leave blank to keep it."
            : "The key will be stored only in the local .env file.";
          keyField.append(note);
          grid.append(keyField);
        }

        const advanced = document.createElement("details");
        advanced.className = "form-section";
        advanced.style.padding = "12px";
        const summary = document.createElement("summary");
        summary.textContent = "Advanced provider settings";
        advanced.append(summary);
        const extrasGrid = document.createElement("div");
        extrasGrid.className = "form-grid";
        extrasGrid.style.marginTop = "12px";
        Object.entries(provider.extra || {}).forEach(([name, value]) => {
          const isBoolean = ["structured_outputs", "reasoning_enabled"].includes(name);
          extrasGrid.append(createAiField(provider, "extra_" + name, labelize(name), value, isBoolean ? "checkbox" : "text"));
        });
        if (provider.requires_key) {
          const remove = document.createElement("label");
          remove.className = "check-row";
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.dataset.aiProviderField = "remove_key";
          remove.append(checkbox, document.createTextNode("Remove stored API key"));
          extrasGrid.append(remove);
        }
        advanced.append(extrasGrid);

        const actions = document.createElement("div");
        actions.className = "provider-actions";
        const testButton = document.createElement("button");
        testButton.type = "button";
        testButton.className = "button secondary";
        testButton.textContent = "Test connection";
        testButton.dataset.testAiProvider = provider.id;
        testButton.addEventListener("click", () => testAiProvider(provider.id, testButton));
        const result = document.createElement("span");
        result.className = "provider-test-result";
        result.dataset.aiTestResult = provider.id;
        renderAiTestResult(result, provider.last_test || {});
        actions.append(testButton, result);
        card.append(head, grid, advanced, actions);
        els.aiProviderGrid.append(card);
      });
    }

    function createAiField(provider, fieldName, labelText, value, type = "text") {
      const wrapper = document.createElement("div");
      wrapper.className = "field";
      const label = document.createElement("label");
      const id = "ai-" + provider.id + "-" + fieldName.replaceAll("_", "-");
      label.htmlFor = id;
      label.textContent = labelText;
      const input = document.createElement("input");
      input.id = id;
      input.dataset.aiProviderField = fieldName;
      input.type = type;
      if (type === "checkbox") {
        input.checked = String(value).toLowerCase() === "true";
      } else {
        input.value = value ?? "";
      }
      wrapper.append(label, input);
      return wrapper;
    }

    function renderAiTestResult(element, result) {
      element.className = "provider-test-result";
      if (!result || !result.tested_at) {
        element.textContent = "Not tested from this dashboard yet.";
        return;
      }
      element.classList.add(result.ok ? "success" : "error");
      element.textContent = safe(result.message) + " - " + (formatDateTime(result.tested_at) || "recently");
    }

    async function saveAiSettings() {
      if (!state.aiSettingsPayload) return;
      const providerCards = Array.from(els.aiProviderGrid.querySelectorAll("[data-provider-id]"));
      const providers = providerCards.map((card) => {
        const provider = { id: card.dataset.providerId, extra: {} };
        card.querySelectorAll("[data-ai-provider-field]").forEach((input) => {
          const name = input.dataset.aiProviderField;
          const value = input.type === "checkbox" ? input.checked : input.value;
          if (name.startsWith("extra_")) {
            provider.extra[name.slice(6)] = value;
          } else {
            provider[name] = value;
          }
        });
        return provider;
      });
      const backendOrder = Array.from(els.aiFallbackOrder.querySelectorAll("[data-ai-order-provider]"))
        .filter((input) => input.checked)
        .sort((a, b) => numeric(a.dataset.aiOrderRank) - numeric(b.dataset.aiOrderRank))
        .map((input) => input.dataset.aiOrderProvider);
      if (!backendOrder.length) {
        setAiSettingsStatus("Enable at least one provider in the fallback order.", "error");
        return;
      }
      const payload = {
        backend: els.aiBackend.value,
        backend_order: backendOrder,
        rate_limit_cooldown_seconds: numeric(els.aiRateLimitCooldown.value) || 90,
        providers
      };
      els.saveAiSettingsButton.disabled = true;
      setAiSettingsStatus("Saving AI settings...");
      try {
        const response = await fetch(API_AI_SETTINGS_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "AI settings save failed");
        state.aiSettingsPayload = result.data;
        renderAiSettings();
        setAiSettingsStatus("AI settings saved. New scout processes will use them.", "success");
      } catch (error) {
        setAiSettingsStatus(safe(error.message) || "AI settings could not be saved.", "error");
      } finally {
        els.saveAiSettingsButton.disabled = false;
      }
      renderScoutWorkspace();
    }

    async function testAiProvider(providerId, button) {
      button.disabled = true;
      const resultElement = els.aiProviderGrid.querySelector(`[data-ai-test-result="${providerId}"]`);
      resultElement.textContent = "Testing connection...";
      resultElement.className = "provider-test-result";
      try {
        const response = await fetch(API_AI_SETTINGS_URL + "/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: providerId })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Connection test failed");
        renderAiTestResult(resultElement, payload.data);
        const provider = (state.aiSettingsPayload.providers || []).find((item) => item.id === providerId);
        if (provider) provider.last_test = payload.data;
      } catch (error) {
        renderAiTestResult(resultElement, { ok: false, message: safe(error.message), tested_at: new Date().toISOString() });
      } finally {
        button.disabled = false;
      }
    }

    function setAiSettingsStatus(message, kind = "") {
      if (!els.aiSettingsStatus) return;
      els.aiSettingsStatus.textContent = message;
      els.aiSettingsStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    async function loadBoardSettings() {
      state.boardSettingsLoading = true;
      setBoardSettingsStatus("Loading job-board settings...");
      try {
        const response = await fetch(API_BOARD_SETTINGS_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.boardSettingsPayload = await response.json();
        renderBoardSettings();
      } catch (error) {
        setBoardSettingsStatus("Job-board settings could not be loaded: " + (safe(error.message) || "unknown error"), "error");
      } finally {
        state.boardSettingsLoading = false;
      }
    }

    function renderBoardSettings() {
      const payload = state.boardSettingsPayload || {};
      const normalized = boardDefaults(payload);
      const boards = normalized.boards;
      const linkedin = boards.linkedin || {};
      const indeed = boards.indeed || {};
      const behavior = normalized.behavior;
      const limits = normalized.limits;
      const defaults = normalized.defaults;
      els.boardLinkedinEnabled.checked = linkedin.enabled !== false;
      els.boardLinkedinEasyApplyOnly.checked = Boolean(linkedin.easy_apply_only);
      els.boardLinkedinDistance.value = numeric(linkedin.distance_miles) || 25;
      els.boardLinkedinCollect.value = numeric(linkedin.max_jobs_to_collect) || 25;
      const levels = new Set(Array.isArray(linkedin.experience_levels) ? linkedin.experience_levels : []);
      document.querySelectorAll("[data-linkedin-level]").forEach((input) => {
        input.checked = levels.has(input.dataset.linkedinLevel);
      });
      els.boardIndeedEnabled.checked = Boolean(indeed.enabled);
      els.boardIndeedUrl.value = indeed.search_url || "";
      els.boardIndeedRadius.value = numeric(indeed.radius_km) || 25;
      els.boardIndeedCollect.value = numeric(indeed.max_jobs_to_collect) || 25;
      els.boardDefaultBrowser.value = defaults.browser || "chromium";
      els.boardDefaultLocation.value = defaults.location || "Amstelveen";
      els.boardDefaultAiBudget.value = defaults.ai_budget_mode || "smart";
      els.boardDefaultHuman.checked = defaults.human_mode !== false;
      els.boardDefaultFresh.checked = defaults.fresh_mode !== false;
      els.behaviorPauseSubmit.checked = true;
      els.behaviorSkipApplied.checked = behavior.skip_if_already_applied !== false;
      els.behaviorCoverLetter.checked = behavior.submit_cover_letter !== false;
      els.behaviorGenerateCoverLetter.checked = behavior.generate_cover_letter_with_ai !== false;
      els.behaviorQuestions.checked = behavior.answer_screening_questions !== false;
      els.behaviorPauseUnknown.checked = behavior.pause_on_unknown_question !== false;
      els.behaviorHumanDelays.checked = behavior.add_human_like_delays !== false;
      els.limitApplicationsRun.value = numeric(limits.max_applications_per_run) || 1;
      els.limitJobsRun.value = numeric(limits.max_jobs_to_try_per_run) || 5;
      els.limitApplicationsDay.value = numeric(limits.max_applications_per_day) || 10;
      applyBoardDefaultsToRunModal();
      setBoardSettingsStatus("Final application submission remains paused for human review.");
    }

    function applyBoardDefaultsToRunModal() {
      const defaults = state.boardSettingsPayload?.dashboard_defaults || {};
      if (defaults.browser) els.runBrowser.value = defaults.browser;
      if (defaults.location) els.runLocation.value = defaults.location;
      if (defaults.ai_budget_mode) els.runAiBudgetMode.value = defaults.ai_budget_mode;
      els.runHumanMode.checked = defaults.human_mode !== false;
      els.runFreshMode.checked = defaults.fresh_mode !== false;
      updateWorkflowFields();
    }

    async function saveBoardSettings() {
      const payload = {
        job_boards: {
          linkedin: {
            enabled: els.boardLinkedinEnabled.checked,
            easy_apply_only: els.boardLinkedinEasyApplyOnly.checked,
            distance_miles: numeric(els.boardLinkedinDistance.value),
            max_jobs_to_collect: numeric(els.boardLinkedinCollect.value),
            experience_levels: Array.from(document.querySelectorAll("[data-linkedin-level]"))
              .filter((input) => input.checked)
              .map((input) => input.dataset.linkedinLevel)
          },
          indeed: {
            enabled: els.boardIndeedEnabled.checked,
            search_url: els.boardIndeedUrl.value,
            radius_km: numeric(els.boardIndeedRadius.value),
            max_jobs_to_collect: numeric(els.boardIndeedCollect.value)
          }
        },
        dashboard_defaults: {
          browser: els.boardDefaultBrowser.value,
          location: els.boardDefaultLocation.value,
          ai_budget_mode: els.boardDefaultAiBudget.value,
          human_mode: els.boardDefaultHuman.checked,
          fresh_mode: els.boardDefaultFresh.checked
        },
        application_behavior: {
          pause_before_final_submit: true,
          skip_if_already_applied: els.behaviorSkipApplied.checked,
          submit_cover_letter: els.behaviorCoverLetter.checked,
          generate_cover_letter_with_ai: els.behaviorGenerateCoverLetter.checked,
          answer_screening_questions: els.behaviorQuestions.checked,
          pause_on_unknown_question: els.behaviorPauseUnknown.checked,
          add_human_like_delays: els.behaviorHumanDelays.checked
        },
        limits: {
          max_applications_per_run: numeric(els.limitApplicationsRun.value),
          max_jobs_to_try_per_run: numeric(els.limitJobsRun.value),
          max_applications_per_day: numeric(els.limitApplicationsDay.value)
        }
      };
      els.saveBoardSettingsButton.disabled = true;
      setBoardSettingsStatus("Saving job-board settings...");
      try {
        const response = await fetch(API_BOARD_SETTINGS_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "Board settings save failed");
        state.boardSettingsPayload = result.data;
        renderBoardSettings();
        setBoardSettingsStatus("Job-board defaults and application safety settings saved.", "success");
      } catch (error) {
        setBoardSettingsStatus(safe(error.message) || "Job-board settings could not be saved.", "error");
      } finally {
        els.saveBoardSettingsButton.disabled = false;
      }
    }

    function setBoardSettingsStatus(message, kind = "") {
      els.boardSettingsStatus.textContent = message;
      els.boardSettingsStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    async function loadApplications({ append = false } = {}) {
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
        const response = await fetch(API_APPLICATIONS_URL + "?" + parameters, { cache: "no-store" });
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
        await loadApplications();
        await loadData();
        setApplicationsStatus("Application updated.", "success");
      } catch (error) {
        setApplicationsStatus(safe(error.message) || "Application could not be saved.", "error");
      } finally {
        button.disabled = false;
      }
    }

    function setApplicationsStatus(message, kind = "") {
      els.applicationsStatus.textContent = message;
      els.applicationsStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    async function loadAssistant() {
      state.assistantLoading = true;
      setAssistantStatus("Loading application knowledge...");
      try {
        const response = await fetch(API_ASSISTANT_URL + "?t=" + Date.now(), { cache: "no-store" });
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
      const payload = {
        application_answers: collectAnswerMapping(els.applicationAnswersEditor, { parseJson: true }),
        learned_answers: collectAnswerMapping(els.learnedAnswersEditor),
        cover_letter_style: els.assistantCoverStyle.value
      };
      els.saveAssistantKnowledgeButton.disabled = true;
      setAssistantStatus("Saving answer library...");
      try {
        const response = await fetch(API_ASSISTANT_URL, {
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
      const jobs = Array.isArray(state.assistantPayload?.jobs) ? state.assistantPayload.jobs : [];
      return jobs[numeric(els.assistantJobSelect.value)] || null;
    }

    async function generateAssistantDraft(mode) {
      const job = selectedAssistantJob();
      if (!job) {
        setAssistantStatus("Choose a job before creating a draft.", "error");
        return;
      }
      const button = mode === "ai" ? els.createAiDraftButton : els.createLocalDraftButton;
      button.disabled = true;
      setAssistantStatus(mode === "ai" ? "Improving draft with Claude..." : "Creating local draft...");
      try {
        const response = await fetch(API_ASSISTANT_URL + "/draft", {
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
      const question = els.assistantQuestion.value.trim();
      if (!question) {
        setAssistantStatus("Enter an application question first.", "error");
        return;
      }
      els.findAssistantAnswerButton.disabled = true;
      els.assistantAnswerResult.textContent = "Checking saved profile facts...";
      try {
        const response = await fetch(API_ASSISTANT_URL + "/answer", {
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
      const text = els.assistantDraft.value.trim();
      if (!text) return;
      await navigator.clipboard.writeText(text);
      setAssistantStatus("Draft copied to clipboard.", "success");
    }

    function downloadAssistantDraft() {
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
      els.assistantStatus.textContent = message;
      els.assistantStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    async function loadMaintenance() {
      state.maintenanceLoading = true;
      setMaintenanceStatus("Loading diagnostics...");
      try {
        const response = await fetch(API_MAINTENANCE_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.maintenancePayload = await response.json();
        renderMaintenance();
        setMaintenanceStatus("Diagnostics refreshed.");
      } catch (error) {
        setMaintenanceStatus("Diagnostics could not be loaded: " + (safe(error.message) || "unknown error"), "error");
      } finally {
        state.maintenanceLoading = false;
      }
    }

    function renderMaintenance() {
      const payload = state.maintenancePayload || {};
      const diagnostics = payload.diagnostics || {};
      const overview = diagnosticOverview(diagnostics);
      els.diagnosticWorkspace.textContent = overview.workspace;
      const database = overview.database;
      els.diagnosticDatabase.textContent = database.exists
        ? `SQLite ready (${formatFileSize(database.size_bytes) || "empty"})`
        : "Not initialized";
      els.diagnosticResume.textContent = overview.resume;
      const persistenceLabels = {
        healthy: "Healthy",
        recovered: `Recovered (${overview.persistenceWarningCount} warning${overview.persistenceWarningCount === 1 ? "" : "s"})`,
        degraded: `Needs attention (${overview.persistenceWarningCount})`
      };
      els.diagnosticPersistence.textContent =
        persistenceLabels[overview.persistenceHealth] || labelize(overview.persistenceHealth);
      els.diagnosticLogs.textContent = `${overview.logCount} (${formatFileSize(overview.logSize) || "0 bytes"})`;
      els.diagnosticRuns.textContent = String(overview.runCount);
      const latestRunIncident = overview.latestRunIncident || {};
      els.latestRunIncident.classList.toggle("hidden", !latestRunIncident.message);
      if (latestRunIncident.message) {
        els.latestRunIncident.replaceChildren();
        els.latestRunIncident.classList.toggle(
          "interrupted",
          latestRunIncident.status === "interrupted"
        );
        const title = document.createElement("strong");
        title.textContent = latestRunIncident.status === "interrupted"
          ? "Latest run was interrupted"
          : "Latest run failed";
        const copy = document.createElement("span");
        copy.textContent = [
          safe(latestRunIncident.run_label),
          formatDateTime(latestRunIncident.timestamp),
          safe(latestRunIncident.message),
          latestRunIncident.resume_available ? "Saved progress can be resumed." : ""
        ].filter(Boolean).join(" - ");
        els.latestRunIncident.append(title, copy);
        if (latestRunIncident.log) {
          const openButton = document.createElement("button");
          openButton.type = "button";
          openButton.className = "button secondary";
          setIconText(openButton, "file", "Open saved log");
          openButton.addEventListener("click", () =>
            openMaintenanceLogByName(latestRunIncident.log)
          );
          els.latestRunIncident.append(openButton);
        }
      }
      const latestError = overview.latestError;
      els.latestDiagnosticError.classList.toggle("hidden", !latestError.message);
      if (latestError.message) {
        els.latestDiagnosticError.replaceChildren();
        const title = document.createElement("strong");
        title.textContent = latestError.resolved
          ? "Resolved diagnostic signal"
          : "Latest diagnostic signal";
        const copy = document.createElement("span");
        copy.textContent = [
          safe(latestError.run_label),
          formatDateTime(latestError.timestamp),
          safe(latestError.message)
        ].filter(Boolean).join(" - ");
        const openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "button secondary";
        setIconText(openButton, "file", "Open saved log");
        openButton.addEventListener("click", () => openMaintenanceLogByName(latestError.log));
        els.latestDiagnosticError.append(title, copy, openButton);
      }
      const latestPersistenceWarning = overview.latestPersistenceWarning || {};
      els.latestPersistenceWarning.classList.toggle("hidden", !latestPersistenceWarning.message);
      if (latestPersistenceWarning.message) {
        els.latestPersistenceWarning.replaceChildren();
        const title = document.createElement("strong");
        title.textContent = latestPersistenceWarning.resolved
          ? "Recovered persistence warning"
          : "Persistence needs attention";
        const copy = document.createElement("span");
        copy.textContent = [
          safe(latestPersistenceWarning.run_label),
          formatDateTime(latestPersistenceWarning.timestamp),
          safe(latestPersistenceWarning.message),
          overview.recoveredTemporaryFiles
            ? `${overview.recoveredTemporaryFiles} temporary file${overview.recoveredTemporaryFiles === 1 ? "" : "s"} recovered`
            : ""
        ].filter(Boolean).join(" - ");
        const openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "button secondary";
        setIconText(openButton, "file", "Open saved log");
        openButton.addEventListener("click", () =>
          openMaintenanceLogByName(latestPersistenceWarning.log)
        );
        els.latestPersistenceWarning.append(title, copy, openButton);
      }
      renderMaintenanceLogs(payload.logs || []);
      renderMaintenanceRuns(payload.lifecycle_runs || payload.runs || []);
      renderBackups(payload.backups || []);
    }

    function renderMaintenanceLogs(logs) {
      els.maintenanceLogList.replaceChildren();
      (Array.isArray(logs) ? logs.slice(0, 100) : []).forEach((record) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "log-list-button";
        button.dataset.logName = record.name;
        const title = document.createElement("strong");
        title.textContent = record.name;
        const meta = document.createElement("span");
        meta.className = "subline";
        meta.textContent = `${labelize(record.kind)} - ${formatFileSize(record.size_bytes)} - ${formatDateTime(record.modified_at)}`;
        button.append(title, meta);
        button.addEventListener("click", () => openMaintenanceLog(record, button));
        els.maintenanceLogList.append(button);
      });
      if (!els.maintenanceLogList.children.length) {
        els.maintenanceLogList.textContent = "No saved logs found.";
      }
    }

    async function openMaintenanceLog(record, button) {
      els.maintenanceLogList.querySelectorAll(".log-list-button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      els.selectedLogTitle.textContent = record.name;
      els.selectedLogMeta.textContent = "Loading log...";
      els.maintenanceLogViewer.textContent = "Loading...";
      try {
        const response = await fetch("/api/log-file?name=" + encodeURIComponent(record.name), { cache: "no-store" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Log could not be loaded");
        state.selectedLogText = payload.text || "";
        els.maintenanceLogViewer.textContent = state.selectedLogText || "This log is empty.";
        els.selectedLogMeta.textContent = `${formatFileSize(payload.size_bytes)}${payload.truncated ? " - showing the latest section" : ""}`;
        els.copyLogButton.disabled = !state.selectedLogText;
      } catch (error) {
        state.selectedLogText = "";
        els.maintenanceLogViewer.textContent = safe(error.message) || "Log could not be loaded.";
        els.copyLogButton.disabled = true;
      }
    }

    function openMaintenanceLogByName(name) {
      const record = (state.maintenancePayload?.logs || []).find((item) => item.name === name);
      const button = Array.from(els.maintenanceLogList.querySelectorAll(".log-list-button"))
        .find((item) => item.dataset.logName === name);
      if (!record || !button) return;
      openMaintenanceLog(record, button);
      els.selectedLogTitle.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function renderMaintenanceRuns(runs) {
      els.maintenanceRunList.replaceChildren();
      (Array.isArray(runs) ? runs.slice(0, 100) : []).forEach((run) => {
        const item = document.createElement("article");
        item.className = "run-list-item";
        const title = document.createElement("strong");
        title.textContent = `${safe(run.run_label || run.query) || "Scout run"} - ${safe(run.location) || "Location unavailable"}`;
        const meta = document.createElement("span");
        meta.className = "subline";
        const stats = run.stats || {};
        meta.textContent = [
          formatDateTime(run.completed_at || run.timestamp || run.started_at),
          labelize(run.status || "completed"),
          `${numeric(stats.processed_jobs ?? run.total_scanned)} processed`,
          `${numeric(stats.apply_first ?? run.new_recommendations)} apply first`,
          `${numeric(stats.good_options)} good options`
        ].filter(Boolean).join(" - ");
        item.append(title, meta);
        els.maintenanceRunList.append(item);
      });
      if (!els.maintenanceRunList.children.length) {
        els.maintenanceRunList.textContent = "No scout history is available.";
      }
    }

    function renderBackups(backups) {
      els.maintenanceBackupList.replaceChildren();
      (Array.isArray(backups) ? backups.slice(0, 12) : []).forEach((backup) => {
        const item = document.createElement("div");
        item.className = "backup-list-item";
        const title = document.createElement("strong");
        title.textContent = backup.name;
        const meta = document.createElement("span");
        meta.className = "subline";
        meta.textContent = `${formatFileSize(backup.size_bytes)} - ${formatDateTime(backup.modified_at)}`;
        const link = document.createElement("a");
        link.className = "job-action";
        link.href = "/api/backup-file?name=" + encodeURIComponent(backup.name);
        link.textContent = "Download backup";
        item.append(title, meta, link);
        els.maintenanceBackupList.append(item);
      });
      if (!els.maintenanceBackupList.children.length) {
        els.maintenanceBackupList.textContent = "No backups created yet.";
      }
    }

    async function createMaintenanceBackup() {
      els.createBackupButton.disabled = true;
      setMaintenanceStatus("Creating secret-free backup...");
      try {
        const response = await fetch(API_MAINTENANCE_URL + "/backup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "Backup failed");
        await loadMaintenance();
        setMaintenanceStatus("Backup created. API keys and browser sessions were excluded.", "success");
      } catch (error) {
        setMaintenanceStatus(safe(error.message) || "Backup could not be created.", "error");
      } finally {
        els.createBackupButton.disabled = false;
      }
    }

    async function pruneMaintenanceLogs() {
      if (!window.confirm("Delete log files older than 90 days while keeping at least the 10 newest logs?")) return;
      els.pruneLogsButton.disabled = true;
      setMaintenanceStatus("Removing old logs...");
      try {
        const response = await fetch(API_MAINTENANCE_URL + "/prune-logs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ older_than_days: 90, keep_latest: 10 })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok === false) throw new Error(result.error || "Log cleanup failed");
        await loadMaintenance();
        setMaintenanceStatus(`Removed ${numeric(result.data?.deleted_count)} old log file(s).`, "success");
      } catch (error) {
        setMaintenanceStatus(safe(error.message) || "Old logs could not be removed.", "error");
      } finally {
        els.pruneLogsButton.disabled = false;
      }
    }

    async function copyMaintenanceLog() {
      if (!state.selectedLogText) return;
      await navigator.clipboard.writeText(state.selectedLogText);
      setMaintenanceStatus("Log copied to clipboard.", "success");
    }

    function setMaintenanceStatus(message, kind = "") {
      els.maintenanceStatus.textContent = message;
      els.maintenanceStatus.className = "profile-status" + (kind ? " " + kind : "");
    }

    function renderScoutWorkspace() {
      const control = state.runControl || {};
      const available = state.runControlAvailable;
      const active = isRunActive();
      const interrupted = control.status === "interrupted";
      if (els.scoutWorkspaceEyebrow) {
        els.scoutWorkspaceEyebrow.textContent = available ? "Local controller connected" : "Local controller unavailable";
        els.scoutWorkspaceStatus.textContent = active
          ? "A scout run is active"
          : (interrupted
            ? "The last run was interrupted"
            : (control.status === "failed" ? "The last run needs attention" : "Ready for the next scout run"));
        els.scoutWorkspaceDetail.textContent = available
          ? runControlStatusText(control)
          : "Start the dashboard with start_dashboard.ps1 to enable run controls.";
        els.scoutWorkspaceBadge.textContent = active ? "Running" : labelize(control.status || "Idle");
        els.scoutWorkspaceBadge.className = "decision-chip " + (
          active ? "APPLY_FIRST" : interrupted ? "INTERRUPTED" : ""
        );
      }
      const queries = Array.isArray(state.strategyPayload?.queries) ? state.strategyPayload.queries : [];
      const locations = Array.isArray(state.strategyPayload?.preferences?.locations)
        ? state.strategyPayload.preferences.locations
        : [];
      if (els.scoutQueryCount) {
        els.scoutQueryCount.textContent = queries.length ? `${queries.length} active queries` : "Queries not loaded";
        els.scoutLocationSummary.textContent = locations.length
          ? `Searching ${locations.slice(0, 4).join(", ")}${locations.length > 4 ? ` and ${locations.length - 4} more` : ""}.`
          : "Add target locations in Job Strategy.";
      }
      const ai = state.aiSettingsPayload || {};
      if (els.scoutAiBackend) {
        els.scoutAiBackend.textContent = ai.backend
          ? (ai.backend === "auto" ? "Automatic fallback" : labelize(ai.backend))
          : "Settings not loaded";
        els.scoutAiFallbacks.textContent = configuredProviderSummary(ai);
      }
      if (els.scoutResumeStatus) {
        els.scoutResumeStatus.textContent = control.resume_available ? "Progress available" : "No interrupted run";
        els.resumeScoutButton.disabled = !available || !control.resume_available || active;
      }
      renderLegacyTools();
    }

    async function loadLegacyTools() {
      state.legacyToolsLoading = true;
      if (els.legacyToolsStatus) {
        els.legacyToolsStatus.textContent = "Loading read-only application statistics...";
        els.legacyToolsStatus.className = "profile-status";
      }
      try {
        const response = await fetch(API_LEGACY_TOOLS_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.legacyToolsPayload = await response.json();
        renderLegacyTools();
      } catch (error) {
        if (els.legacyToolsStatus) {
          els.legacyToolsStatus.textContent = "Legacy statistics could not be loaded: " + (safe(error.message) || "unknown error");
          els.legacyToolsStatus.className = "profile-status error";
        }
      } finally {
        state.legacyToolsLoading = false;
      }
    }

    function renderLegacyTools() {
      if (!els.legacyToolsStatus) return;
      const payload = state.legacyToolsPayload || {};
      const applications = payload.applications || {};
      const reviews = payload.reviews || {};
      els.legacyApplicationCount.textContent = numeric(applications.total);
      els.legacyTodayCount.textContent = numeric(applications.today);
      els.legacyReviewCount.textContent = numeric(reviews.total);
      els.legacySeenCount.textContent = numeric(payload.seen_jobs);
      if (payload.database_available) {
        els.legacyToolsStatus.textContent = "Read-only statistics loaded from " + (safe(payload.database_path) || "the legacy tracker database") + ".";
        els.legacyToolsStatus.className = "profile-status success";
      } else if (!state.legacyToolsLoading) {
        els.legacyToolsStatus.textContent = "No legacy tracker database exists yet. Validation is still available.";
        els.legacyToolsStatus.className = "profile-status";
      }
    }

    function openValidationWorkflow() {
      openScoutModal();
      els.runWorkflow.value = "validate_boards";
      updateWorkflowFields();
    }

    function openScoutModal({ resume = false } = {}) {
      openRunScoutModal();
      if (resume && els.runResumeMode && !els.runResumeMode.disabled) {
        els.runResumeMode.checked = true;
      }
    }

    function emptyData() {
      return {
        schema_version: "live_dashboard.v1",
        dashboard_updated_at: "",
        active_run_id: "",
        runs: [],
        jobs: [],
        summary: { by_decision: {}, by_domain: {}, by_manual_status: {} },
        filter_options: { runs: [], decisions: [], domains: [], flags: [], apply_methods: [], manual_statuses: [] }
      };
    }

    function setStatus(kind, text) {
      els.statusDot.className = "status-dot" + (kind ? " " + kind : "");
      els.statusText.textContent = text;
    }

    async function loadData() {
      try {
        const { payload, apiAvailable } = await fetchDashboardData();
        if (!payload || payload.schema_version !== "live_dashboard.v1") {
          throw new Error("Unsupported dashboard schema");
        }
        state.data = payload;
        state.apiAvailable = apiAvailable;
        if (apiAvailable) {
          await loadJobs({ renderAfter: false });
        } else {
          state.jobsTotal = jobs().length;
          state.jobsHasMore = false;
          state.jobsByDecision = {};
        }
        updateUndoButtonState();
        syncGlobalRunStatus();
        render();
      } catch (error) {
        setStatus("error", "Data unavailable");
        render();
      }
    }

    async function fetchDashboardData() {
      try {
        const apiResponse = await fetch(
          API_DATA_URL + "?include_jobs=false&t=" + Date.now(),
          { cache: "no-store" }
        );
        if (apiResponse.ok) {
          return { payload: withDefaultManualStatus(await apiResponse.json()), apiAvailable: true };
        }
      } catch (_error) {
        // Fall back to the static JSON file when opened with a read-only server.
      }

      const response = await fetch(DATA_URL + "?t=" + Date.now(), { cache: "no-store" });
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      return { payload: withDefaultManualStatus(await response.json()), apiAvailable: false };
    }

    async function loadJobs({ append = false, renderAfter = true } = {}) {
      if (!state.apiAvailable) {
        if (renderAfter) render();
        return;
      }
      const requestId = ++state.jobsRequestId;
      state.jobsLoading = true;
      if (els.loadMoreJobsButton) els.loadMoreJobsButton.disabled = true;
      const existing = append ? jobs() : [];
      const parameters = buildJobsQuery(state.filters, existing.length);
      try {
        const response = await fetch(API_JOBS_URL + "?" + parameters, { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const payload = await response.json();
        if (requestId !== state.jobsRequestId) return;
        const incoming = normalizeJobs(payload.jobs || []);
        state.data.jobs = append ? [...existing, ...incoming] : incoming;
        state.jobsTotal = numeric(payload.total);
        state.jobsHasMore = Boolean(payload.has_more);
        state.jobsByDecision = payload.by_decision || {};
      } catch (error) {
        if (requestId === state.jobsRequestId) {
          setStatus("error", "Jobs could not be loaded");
        }
      } finally {
        if (requestId === state.jobsRequestId) {
          state.jobsLoading = false;
          if (els.loadMoreJobsButton) els.loadMoreJobsButton.disabled = false;
          if (renderAfter) render();
        }
      }
    }

    function normalizeJobs(items) {
      return (Array.isArray(items) ? items : []).map((job) => {
        if (!job.manual_status) {
          job.manual_status = "unreviewed";
          job.manual_status_label = "Unreviewed";
        }
        if (!job.apply_method) {
          job.apply_method = applyMethod(job);
          const found = APPLY_METHODS.find(([value]) => value === job.apply_method);
          job.apply_method_label = found ? found[1] : "Unknown";
        }
        return job;
      });
    }

    function queueJobsReload() {
      window.clearTimeout(state.jobsSearchTimer);
      state.jobsSearchTimer = window.setTimeout(() => loadJobs(), 250);
    }

    function withDefaultManualStatus(payload) {
      const data = payload || emptyData();
      const jobs = normalizeJobs(data.jobs);
      data.summary = data.summary || {};
      if (!data.summary.by_manual_status || jobs.length) {
        data.summary.by_manual_status = manualStatusCounts(jobs);
      }
      data.filter_options = data.filter_options || {};
      data.filter_options.apply_methods = data.filter_options.apply_methods || APPLY_METHODS.map(([value]) => value);
      data.filter_options.manual_statuses = MANUAL_STATUSES.map(([value, label]) => ({ value, label }));
      return data;
    }

    function render() {
      renderThemeToggle();
      renderHome();
      syncFilterOptions();
      renderStats();
      renderFreshProgress();
      renderBestNextJobs();
      renderRunHistory();
      renderQuickPresets();
      renderFilterHint();
      renderJobs();
      renderLayoutMode();
      renderRunControl();
      updateUndoButtonState();
    }

    function applyTheme(theme, persist = true) {
      const nextTheme = theme === "dark" ? "dark" : "light";
      state.theme = nextTheme;
      document.documentElement.dataset.theme = nextTheme;
      if (persist) {
        try {
          localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
        } catch (_error) {
          // Theme still changes for this page even when storage is unavailable.
        }
      }
      renderThemeToggle();
    }

    function toggleTheme() {
      applyTheme(state.theme === "dark" ? "light" : "dark");
    }

    function renderThemeToggle() {
      if (!els.themeToggle || !els.themeToggleText || !els.themeToggleIcon) return;
      const isDark = state.theme === "dark";
      const nextLabel = isDark ? "Light" : "Dark";
      const iconUse = els.themeToggleIcon.querySelector("use");
      if (iconUse) {
        iconUse.setAttribute("href", isDark ? "#icon-sun" : "#icon-moon");
      }
      els.themeToggleText.textContent = nextLabel;
      els.themeToggle.setAttribute("aria-pressed", isDark ? "true" : "false");
      els.themeToggle.setAttribute("title", "Switch to " + nextLabel.toLowerCase() + " mode");
      els.themeToggle.setAttribute("aria-label", "Switch to " + nextLabel.toLowerCase() + " mode");
    }

    function renderHome() {
      if (!els.homeFocusTitle) return;
      const allJobs = jobs();
      const summary = state.data.summary || {};
      const actionableCount = Number.isFinite(Number(summary.actionable_jobs))
        ? numeric(summary.actionable_jobs)
        : allJobs.filter((job) => needsAction(job)).length;
      const applyFirst = Number.isFinite(Number(summary.actionable_apply_first))
        ? numeric(summary.actionable_apply_first)
        : allJobs.filter((job) => needsAction(job) && safe(job.decision_category) === "APPLY_FIRST").length;
      const goodOptions = Number.isFinite(Number(summary.actionable_good_options))
        ? numeric(summary.actionable_good_options)
        : allJobs.filter((job) => needsAction(job) && safe(job.decision_category) === "GOOD_OPTIONS").length;
      const manual = summary.by_manual_status || manualStatusCounts(allJobs);
      const activeRun = isRunActive();
      const interrupted = state.runControl?.status === "interrupted";
      const runs = Array.isArray(state.data.runs) ? state.data.runs : [];
      const latestRun = runs.length ? runs[runs.length - 1] : {};
      const latestStats = latestRun.stats || {};

      els.homeActionableCount.textContent = String(actionableCount);
      els.homeApplyCount.textContent = String(applyFirst);
      els.homeGoodCount.textContent = String(goodOptions);
      if (actionableCount) {
        els.homeFocusTitle.textContent = `${actionableCount} strong job${actionableCount === 1 ? "" : "s"} are waiting for your review.`;
        els.homeFocusCopy.textContent = applyFirst
          ? `Start with ${applyFirst} Apply First role${applyFirst === 1 ? "" : "s"}, then review the strongest Good Options.`
          : "Your Apply First list is clear, so the strongest Good Options are the next useful place to look.";
      } else {
        els.homeFocusTitle.textContent = "Your actionable queue is clear.";
        els.homeFocusCopy.textContent = "Start a fresh scout run to look for new opportunities, or review your application follow-ups.";
      }

      els.homeRunBadge.textContent = activeRun
        ? "Scout running"
        : interrupted
          ? "Scout interrupted"
          : (state.runControlAvailable ? "Scout ready" : "Controller offline");
      els.homeRunBadge.className = "home-card-status" + (
        activeRun ? " APPLY_FIRST" : interrupted ? " INTERRUPTED" : ""
      );
      els.homeRunTitle.textContent = activeRun
        ? safe(state.runControl?.workflow_label) || "A scout run is active"
        : (interrupted
          ? "A previous run was interrupted and can be resumed"
          : (state.runControl?.resume_available ? "A previous run can be resumed" : "Ready for the next scout"));
      els.homeRunCopy.textContent = activeRun
        ? runControlStatusText(state.runControl || {})
        : interrupted
          ? resumeContextText(state.runControl || {})
        : (state.runControlAvailable
          ? "Run controls are connected. Login and verification remain manual."
          : "Launch the dashboard with its desktop shortcut to enable local run controls.");

      const readiness = numeric(state.profilePayload?.readiness?.percent);
      const cvName = safe(state.profilePayload?.cv?.filename);
      els.homeSetupValue.textContent = readiness ? `${readiness}% ready` : (state.profileLoading ? "Checking..." : "Review setup");
      els.homeSetupHealth.textContent = state.profilePayload
        ? `${cvName ? "CV connected" : "Add a CV"}; profile, preferences, and work authorization stay in your private workspace.`
        : "Open Profile & CV to verify the information used for filtering and AI scoring.";

      const applied = numeric(manual.applied);
      els.homeAppliedValue.textContent = `${applied} applied`;
      els.homeAppliedCopy.textContent = applied
        ? "Keep stages, interview notes, and follow-up dates current so promising applications do not disappear from view."
        : "Mark jobs as Applied from the Jobs board, then manage their stages here.";

      const runLabel = safe(latestRun.run_label) || "No completed run";
      els.homeLatestRunValue.textContent = runLabel;
      const accepted = numeric(latestStats.accepted)
        || (numeric(latestStats.apply_first) + numeric(latestStats.good_options));
      const collected = numeric(latestStats.collected) || numeric(latestStats.processed_jobs);
      els.homeLatestRunCopy.textContent = latestRun.run_id
        ? `${collected} collected, ${accepted} accepted. Open Runs & Logs for diagnostics and the saved terminal record.`
        : "Start a scout to build run history and searchable diagnostics.";
    }

    function syncFilterOptions() {
      const selected = {
        run: state.filters.run,
        decision: state.filters.decision,
        domain: state.filters.domain,
        flag: state.filters.flag,
        applyMethod: state.filters.applyMethod,
        manualStatus: state.filters.manualStatus
      };

      setOptions(els.runFilter, [["all", "All runs"], ...runOptions()], selected.run);
      setOptions(els.decisionFilter, [["all", "All decisions"], ...DECISIONS], selected.decision);
      setOptions(els.domainFilter, [["all", "All domains"], ...domainOptions()], selected.domain);
      setOptions(els.flagFilter, [["all", "All flags"], ...flagOptions()], selected.flag);
      setOptions(els.applyMethodFilter, [["all", "All apply methods"], ...applyMethodOptions()], selected.applyMethod);
      setOptions(els.manualStatusFilter, [["all", "All statuses"], ...manualStatusOptions()], selected.manualStatus);
      els.actionFilter.value = state.filters.actionScope;
      els.sortFilter.value = state.filters.sort;
    }

    function setOptions(select, options, selectedValue) {
      const current = new Set([...select.options].map((option) => option.value + "|" + option.textContent));
      const next = new Set(options.map((option) => option[0] + "|" + option[1]));
      const unchanged = current.size === next.size && [...current].every((item) => next.has(item));
      if (!unchanged) {
        select.replaceChildren(...options.map(([value, label]) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          return option;
        }));
      }
      select.value = options.some(([value]) => value === selectedValue) ? selectedValue : "all";
      state.filters[filterNameFor(select)] = select.value;
    }

    function filterNameFor(select) {
      if (select === els.runFilter) return "run";
      if (select === els.decisionFilter) return "decision";
      if (select === els.domainFilter) return "domain";
      if (select === els.flagFilter) return "flag";
      if (select === els.applyMethodFilter) return "applyMethod";
      if (select === els.manualStatusFilter) return "manualStatus";
      return "";
    }

    function runOptions() {
      const runs = Array.isArray(state.data.runs) ? state.data.runs : [];
      return runs.map((run) => [safe(run.run_id), runFilterLabel(run)])
        .filter(([value]) => value);
    }

    function runFilterLabel(run) {
      const label = safe(run.run_label) || safe(run.run_id);
      const stats = run && typeof run.stats === "object" ? run.stats : {};
      const count = numeric(stats.processed_jobs);
      if (!count) return label + " - empty";
      return label + " - " + count + (count === 1 ? " job" : " jobs");
    }

    function domainOptions() {
      const configured = state.data.filter_options && Array.isArray(state.data.filter_options.domains)
        ? state.data.filter_options.domains
        : [];
      if (configured.length) {
        return configured
          .map((domain) => [safe(domain), labelize(domain)])
          .filter(([value]) => value)
          .sort((a, b) => a[1].localeCompare(b[1]));
      }
      const domains = new Map();
      for (const job of jobs()) {
        if (job.domain_category) {
          domains.set(job.domain_category, job.domain_label || labelize(job.domain_category));
        }
      }
      return [...domains.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    }

    function flagOptions() {
      const configured = state.data.filter_options && Array.isArray(state.data.filter_options.flags)
        ? state.data.filter_options.flags
        : [];
      if (configured.length) {
        return configured
          .map((flag) => [safe(flag), labelize(flag)])
          .filter(([value]) => value)
          .sort((a, b) => a[1].localeCompare(b[1]));
      }
      const flags = new Set();
      for (const job of jobs()) {
        for (const flag of Array.isArray(job.flags) ? job.flags : []) {
          if (flag) flags.add(flag);
        }
      }
      return [...flags].sort().map((flag) => [flag, labelize(flag)]);
    }

    function manualStatusOptions() {
      const configured = state.data.filter_options && Array.isArray(state.data.filter_options.manual_statuses)
        ? state.data.filter_options.manual_statuses
        : [];
      const options = configured.map((item) => [safe(item.value), safe(item.label)]).filter(([value]) => value);
      return options.length ? options : MANUAL_STATUSES;
    }

    function applyMethodOptions() {
      const configured = state.data.filter_options && Array.isArray(state.data.filter_options.apply_methods)
        ? state.data.filter_options.apply_methods
        : [];
      const values = configured.length ? configured : APPLY_METHODS.map(([value]) => value);
      const labels = new Map(APPLY_METHODS);
      return values
        .map((value) => [safe(value), labels.get(safe(value)) || labelize(value)])
        .filter(([value]) => value);
    }

    function renderStats() {
      const summary = state.data.summary || {};
      const decisions = summary.by_decision || {};
      const manual = summary.by_manual_status || manualStatusCounts(jobs());
      els.statTotal.textContent = String(summary.total_jobs || jobs().length || 0);
      els.statActive.textContent = String(summary.active_run_jobs || 0);
      els.statApply.textContent = String(decisions.APPLY_FIRST || 0);
      els.statGood.textContent = String(decisions.GOOD_OPTIONS || 0);
      els.statLow.textContent = String(decisions.LOW_PROBABILITY || 0);
      els.statRejected.textContent = String(decisions.REJECTED || 0);
      els.statUnreviewed.textContent = String(
        Number.isFinite(Number(summary.actionable_jobs))
          ? numeric(summary.actionable_jobs)
          : jobs().filter((job) => needsAction(job)).length
      );
      els.statApplied.textContent = String(manual.applied || 0);
      els.statIrrelevant.textContent = String(manual.irrelevant || 0);
      els.updatedAt.textContent = "Updated: " + (formatDateTime(state.data.dashboard_updated_at) || "never");
    }

    function renderFreshProgress() {
      const run = selectedFreshRun();
      const fresh = run && run.fresh_scout && run.fresh_scout.enabled ? run.fresh_scout : null;
      if (!fresh) {
        els.freshPanel.classList.add("hidden");
        return;
      }

      const policy = fresh.policy || {};
      const progress = fresh.progress || {};
      const stats = run.stats || {};
      const apply = numeric(progress.apply_first || stats.apply_first);
      const good = numeric(progress.good_or_better || (numeric(stats.apply_first) + numeric(stats.good_options)));
      const freshJobs = numeric(progress.fresh_jobs_seen);
      const knownSkipped = numeric(progress.known_jobs_skipped);
      const applyTarget = numeric(policy.target_apply_first_jobs);
      const goodTarget = numeric(policy.target_good_or_better_jobs);
      const jobCap = numeric(policy.global_new_jobs_soft_cap);
      const totalQueries = numeric(progress.total_queries || (Array.isArray(run.queries) ? run.queries.length : 0));
      const queryIndex = numeric(progress.current_query_index);
      const maxPages = numeric(policy.max_pages_per_query);
      const currentPage = numeric(progress.current_page_number);
      const stopReason = safe(progress.stop_reason);
      const latestPage = latestFreshPage(fresh);
      const isRunning = run.status === "running";
      const runId = safe(run.run_id);
      const expanded = state.expandedFreshRuns.has(runId);

      els.freshPanel.classList.remove("hidden");
      els.freshPanel.classList.toggle("interrupted", run.status === "interrupted");
      els.freshPanel.classList.toggle("completed", !isRunning);
      els.freshPanel.classList.toggle("expanded", isRunning || expanded);
      els.freshCompleteSummary.classList.toggle("hidden", isRunning);
      setIconText(
        els.freshTitle,
        isRunning ? "activity" : run.status === "interrupted" ? "alert-circle" : "refresh",
        isRunning
          ? "Fresh Scout Progress"
          : run.status === "interrupted"
            ? "Interrupted Fresh Scout Run"
            : "Last Fresh Scout Run"
      );
      els.freshRunLabel.textContent = safe(run.run_label) || "Fresh run";
      els.freshStatus.textContent = freshStatusText(run, progress, stopReason);
      els.freshApply.textContent = metricText(apply, applyTarget);
      els.freshGood.textContent = metricText(good, goodTarget);
      els.freshJobs.textContent = metricText(freshJobs, jobCap);
      els.freshKnownSkipped.textContent = String(knownSkipped);
      els.freshApplyBar.style.width = progressPercent(apply, applyTarget) + "%";
      els.freshGoodBar.style.width = progressPercent(good, goodTarget) + "%";
      els.freshJobsBar.style.width = progressPercent(freshJobs, jobCap) + "%";
      els.freshKnownBar.style.width = progressPercent(knownSkipped, Math.max(knownSkipped + freshJobs, 1)) + "%";
      els.freshQuery.textContent = safe(progress.current_query) || "No active query";
      els.freshPage.textContent = currentPage
        ? ("Page " + currentPage + (maxPages ? " / " + maxPages : ""))
        : (latestPage ? ("Page " + latestPage.page_number + (maxPages ? " / " + maxPages : "")) : "-");
      els.freshQueries.textContent = totalQueries ? (Math.min(queryIndex || 0, totalQueries) + " / " + totalQueries) : "-";
      els.freshPagesScanned.textContent = String(numeric(progress.pages_scanned));
      renderFreshCompleteSummary(run, progress, {
        apply,
        good,
        freshJobs,
        knownSkipped,
        aiScored: numeric(progress.ai_scored),
        queryIndex,
        totalQueries,
        stopReason,
        expanded,
      });
      renderFreshPages(fresh, policy);
    }

    function selectedFreshRun() {
      const runs = Array.isArray(state.data.runs) ? state.data.runs : [];
      const selectedRunId = state.filters.run !== "all" ? state.filters.run : "";
      if (selectedRunId) {
        return runs.find((run) => safe(run.run_id) === selectedRunId && run.fresh_scout && run.fresh_scout.enabled);
      }
      const activeRun = runs.find((run) => safe(run.run_id) === effectiveActiveRunId() && run.fresh_scout && run.fresh_scout.enabled);
      if (activeRun) return activeRun;
      return [...runs].reverse().find((run) => run.fresh_scout && run.fresh_scout.enabled);
    }

    function freshStatusText(run, progress, stopReason) {
      const phase = labelize(progress.phase || "");
      if (run.status === "interrupted") return "Interrupted: progress was saved and can be resumed.";
      if (stopReason && run.status === "completed") return "Completed early: " + conciseStopReason(stopReason);
      if (stopReason) return "Stopped: " + conciseStopReason(stopReason);
      if (run.status === "running") return phase ? ("Running: " + phase) : "Fresh run active.";
      if (run.status === "failed") return "Fresh run ended with an error.";
      if (run.status === "stopped") return "Fresh run stopped before completion.";
      return "Fresh run complete.";
    }

    function renderFreshCompleteSummary(run, progress, values) {
      els.freshCompleteSummary.replaceChildren();
      if (run.status === "running") return;

      const items = [
        ["Fresh jobs", values.freshJobs],
        ["Apply first", values.apply],
        ["Good+", values.good],
        ["Known skipped", values.knownSkipped],
        ["AI calls", values.aiScored],
        ["Queries", values.totalQueries ? Math.min(values.queryIndex || 0, values.totalQueries) + " / " + values.totalQueries : "-"],
      ];
      for (const [label, value] of items) {
        els.freshCompleteSummary.append(freshSummaryChip(label, value));
      }
      if (values.stopReason) {
        const chip = freshSummaryChip(
          run.status === "interrupted" ? "Reason" : "Stop",
          shortStopReason(values.stopReason)
        );
        chip.title = values.stopReason;
        els.freshCompleteSummary.append(chip);
      }

      const filterButton = document.createElement("button");
      filterButton.type = "button";
      filterButton.className = "fresh-action";
      setIconText(filterButton, "filter", "Filter to this run");
      filterButton.addEventListener("click", () => {
        state.filters.run = safe(run.run_id) || "all";
        els.runFilter.value = state.filters.run;
        syncFilterOptions();
        loadJobs();
      });

      const detailsButton = document.createElement("button");
      detailsButton.type = "button";
      detailsButton.className = "fresh-action";
      setIconText(detailsButton, values.expanded ? "archive" : "list", values.expanded ? "Hide details" : "Show details");
      detailsButton.addEventListener("click", () => {
        const runId = safe(run.run_id);
        if (!runId) return;
        if (state.expandedFreshRuns.has(runId)) {
          state.expandedFreshRuns.delete(runId);
        } else {
          state.expandedFreshRuns.add(runId);
        }
        renderFreshProgress();
      });

      els.freshCompleteSummary.append(filterButton, detailsButton);
      if (run.status === "interrupted" && state.runControl?.resume_available) {
        const resumeButton = document.createElement("button");
        resumeButton.type = "button";
        resumeButton.className = "fresh-action interrupted";
        setIconText(resumeButton, "play", "Resume last run");
        resumeButton.addEventListener("click", () => openScoutModal({ resume: true }));
        els.freshCompleteSummary.append(resumeButton);
      }
    }

    function freshSummaryChip(label, value) {
      const chip = document.createElement("span");
      chip.className = "fresh-summary-chip";
      const strong = document.createElement("strong");
      strong.textContent = String(value ?? "");
      chip.append(createIcon(SUMMARY_ICONS[safe(label)] || "bar-chart", "icon icon-sm"), document.createTextNode(safe(label) + ": "), strong);
      return chip;
    }

    function shortStopReason(reason) {
      return conciseStopReason(reason);
    }

    function conciseStopReason(reason) {
      const cleaned = safe(reason);
      if (!cleaned) return "";
      if (/ai budget guard|model call|soft cap/i.test(cleaned)) return "AI budget guard";
      if (/apply first|target apply/i.test(cleaned)) return "Apply target reached";
      if (/good or better|quality target|fresh quality/i.test(cleaned)) return "Quality target guard";
      if (/duplicate/i.test(cleaned)) return "Duplicate-heavy pages";
      if (/rate limit|quota/i.test(cleaned)) return "AI rate limit";
      if (/captcha|verification|human/i.test(cleaned)) return "Manual verification";
      if (/timeout|timed out/i.test(cleaned)) return "Navigation timeout";
      return cleaned.length > 34 ? cleaned.slice(0, 31) + "..." : cleaned;
    }

    function latestFreshPage(fresh) {
      const history = Array.isArray(fresh.page_history) ? fresh.page_history : [];
      return history.length ? history[history.length - 1] : null;
    }

    function metricText(value, target) {
      return target ? (value + " / " + target) : String(value);
    }

    function progressPercent(value, target) {
      if (!target) return 0;
      return Math.max(0, Math.min(100, Math.round((numeric(value) / numeric(target)) * 100)));
    }

    function renderFreshPages(fresh, policy) {
      const history = Array.isArray(fresh.page_history) ? fresh.page_history : [];
      const recent = history.slice(-4).reverse();
      els.freshPages.replaceChildren();
      if (!recent.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Fresh page decisions will appear here while the scout scans.";
        els.freshPages.append(empty);
        return;
      }
      els.freshPages.append(...recent.map((page) => freshPageCard(page, policy)));
    }

    function freshPageCard(page, policy) {
      const card = document.createElement("div");
      const knownRatio = Number(page.known_ratio || 0);
      const newJobs = numeric(page.new_jobs);
      const minNew = numeric(policy.min_new_jobs_per_useful_query);
      const duplicateHeavy = knownRatio >= Number(policy.duplicate_heavy_stop_threshold || 0.9);
      const useful = minNew && newJobs >= minNew;
      card.className = "fresh-page" + (useful ? " useful" : duplicateHeavy ? " duplicate-heavy" : "");

      const title = document.createElement("strong");
      title.append(createIcon(useful ? "check-circle" : duplicateHeavy ? "archive" : "bar-chart", "icon icon-sm"), document.createTextNode((safe(page.query) || "Query") + " - page " + (numeric(page.page_number) || "?")));
      const numbers = document.createElement("span");
      numbers.textContent = [
        numeric(page.cards_seen) + " cards",
        numeric(page.known_jobs) + " known",
        newJobs + " new",
        Math.round(knownRatio * 100) + "% known"
      ].join(" | ");
      const note = document.createElement("span");
      note.textContent = useful
        ? "Useful page"
        : duplicateHeavy
          ? "Duplicate-heavy"
          : "Mixed page";
      card.append(title, numbers, note);
      return card;
    }

    function renderBestNextJobs() {
      const items = bestNextJobs();
      els.bestNextList.replaceChildren();
      setIconText(els.bestNextCount, "target", items.length + (items.length === 1 ? " ready" : " ready"));
      els.bestNextPanel.classList.remove("hidden");
      if (!items.length) {
        els.bestNextList.append(bestNextEmptyState());
        return;
      }
      els.bestNextList.append(...items.map(bestNextCard));
    }

    function bestNextEmptyState() {
      const empty = document.createElement("div");
      empty.className = "best-empty";
      const title = document.createElement("strong");
      title.textContent = "No actionable jobs in this view.";
      const copy = document.createElement("span");
      copy.textContent = "Actionable means unreviewed Apply First and Good Options jobs. Try clearing filters or switching to all jobs if you want to inspect the archive.";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "fresh-action";
      setIconText(button, "filter", "Show all jobs");
      button.addEventListener("click", () => {
        state.filters.actionScope = "all";
        state.filters.decision = "all";
        state.filters.manualStatus = "all";
        state.filters.quickPreset = "";
        syncFilterOptions();
        loadJobs();
      });
      empty.append(title, copy, button);
      return empty;
    }

    function bestNextJobs() {
      const activeRunId = effectiveActiveRunId();
      const latestRun = latestRunId();
      return jobs()
        .filter((job) => needsAction(job))
        .filter((job) => {
          if (state.filters.run !== "all" && job.run_id !== state.filters.run) return false;
          if (state.filters.applyMethod !== "all" && applyMethod(job) !== state.filters.applyMethod) return false;
          if (state.filters.domain !== "all" && job.domain_category !== state.filters.domain) return false;
          if (state.filters.flag !== "all" && !(Array.isArray(job.flags) && job.flags.includes(state.filters.flag))) return false;
          if (state.filters.quickPreset === "dutch_risk" && !hasDutchRisk(job)) return false;
          if (state.filters.quickPreset === "remote_hybrid" && !isRemoteOrHybrid(job)) return false;
          return true;
        })
        .sort((a, b) => {
          const aRunBoost = safe(a.run_id) === activeRunId ? 2 : (safe(a.run_id) === latestRun ? 1 : 0);
          const bRunBoost = safe(b.run_id) === activeRunId ? 2 : (safe(b.run_id) === latestRun ? 1 : 0);
          const aDecision = safe(a.decision_category) === "APPLY_FIRST" ? 1 : 0;
          const bDecision = safe(b.decision_category) === "APPLY_FIRST" ? 1 : 0;
          return (bDecision - aDecision)
            || (bRunBoost - aRunBoost)
            || (numeric(b.score) - numeric(a.score))
            || safe(b.processed_at).localeCompare(safe(a.processed_at));
        })
        .slice(0, 5);
    }

    function bestNextCard(job) {
      const status = manualStatus(job);
      const article = document.createElement("article");
      article.className = "best-card " + safe(job.decision_category) + " manual-" + status;
      article.dataset.jobKey = safe(job.job_key) || jobIdentity(job);

      const title = document.createElement("div");
      title.className = "best-title";
      const link = document.createElement(job.url ? "a" : "span");
      link.textContent = safe(job.title) || "Untitled job";
      if (job.url) {
        link.href = job.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      title.append(link);

      const meta = document.createElement("div");
      meta.className = "best-meta";
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = String(Number.isFinite(Number(job.score)) ? Number(job.score) : 0);
      const run = document.createElement("span");
      run.className = "run-badge";
      run.textContent = shortRunLabel(job) || "Run";
      run.title = safe(job.run_label) || safe(job.run_id);
      const decision = decisionChip(job.decision_category, decisionLabel(job));
      meta.append(score, run, decision);
      const methodBadge = applyMethodBadge(job);
      if (methodBadge) meta.append(methodBadge);

      const subline = document.createElement("div");
      subline.className = "subline";
      subline.textContent = [safe(job.company), safe(job.location), safe(job.query)].filter(Boolean).join(" | ");

      const reason = document.createElement("div");
      reason.className = "reason";
      reason.textContent = safe(job.reason) || safe(job.terminal_status) || "No reason recorded";

      const badges = document.createElement("div");
      badges.className = "badges";
      badges.append(badge(job.domain_label || labelize(job.domain_category), "domain"));
      for (const flag of importantFlags(job).slice(0, 3)) {
        badges.append(badge(labelize(flag), isRiskFlag(flag) ? "risk" : ""));
      }

      article.append(title, meta, subline, reason, badges, actionRow(job, status));
      return article;
    }

    function renderRunHistory() {
      const runs = Array.isArray(state.data.runs) ? [...state.data.runs].reverse() : [];
      els.runHistoryList.replaceChildren();
      els.runHistoryPanel.classList.toggle("hidden", !runs.length);
      els.runHistoryPanel.classList.toggle("compact", !state.runHistoryExpanded);
      if (!runs.length) return;
      const visible = state.runHistoryExpanded ? runs : runs.slice(0, 1);
      setIconText(els.toggleRunHistoryButton, "clock", state.runHistoryExpanded ? "Show fewer" : "Show run history");
      els.toggleRunHistoryButton.disabled = runs.length <= 1;
      els.runHistoryList.append(...visible.map(runHistoryItem));
    }

    function renderFilterHint() {
      if (!els.filterHint) return;
      const parts = [];
      if (state.filters.actionScope === "needs_action") {
        parts.push("Actionable jobs = unreviewed Apply First and Good Options roles.");
      } else {
        parts.push("All jobs view includes low probability, rejected, applied, and irrelevant records.");
      }
      if (state.filters.run !== "all") parts.push("Run filter is active.");
      if (state.filters.applyMethod === "easy_apply") parts.push("Showing LinkedIn jobs where Easy Apply was detected.");
      if (state.filters.manualStatus !== "all") parts.push("Manual status filter is active.");
      els.filterHint.textContent = parts.join(" ");
    }

    function runHistoryItem(run) {
      const item = document.createElement("article");
      item.className = "run-history-item " + safe(run.status);

      const title = document.createElement("div");
      title.className = "run-history-title";
      const label = document.createElement("span");
      label.textContent = safe(run.run_label) || safe(run.run_id) || "Run";
      const status = document.createElement("span");
      status.className = "decision-chip " + (
        run.status === "interrupted" ? "INTERRUPTED" : ""
      );
      status.append(
        createIcon(
          run.status === "completed"
            ? "check-circle"
            : run.status === "running"
              ? "activity"
              : run.status === "interrupted"
                ? "alert-circle"
                : "clock",
          "icon icon-sm"
        ),
        document.createTextNode(labelize(run.status || "unknown"))
      );
      title.append(label, status);

      const stats = run.stats || {};
      const fresh = run.fresh_scout || {};
      const progress = fresh.progress || {};
      const counts = [
        ["Fresh", numeric(progress.fresh_jobs_seen)],
        ["Apply", numeric(progress.apply_first || stats.apply_first)],
        ["Good", numeric(progress.good_or_better || stats.good_options)],
        ["Skipped", numeric(progress.known_jobs_skipped)],
        ["AI", numeric(progress.ai_scored)]
      ];
      const statRow = document.createElement("div");
      statRow.className = "run-history-stats";
      for (const [labelText, value] of counts) {
        statRow.append(freshSummaryChip(labelText, value));
      }

      const meta = document.createElement("div");
      meta.className = "run-history-meta";
      meta.textContent = [
        safe(run.mode),
        safe(run.location),
        safe(progress.stop_reason || ""),
      ].filter(Boolean).join(" | ");

      const filter = document.createElement("button");
      filter.type = "button";
      filter.className = "fresh-action";
      setIconText(filter, "filter", "Filter to this run");
      filter.addEventListener("click", () => {
        state.filters.run = safe(run.run_id) || "all";
        state.filters.actionScope = "all";
        state.filters.quickPreset = "current_run";
        syncFilterOptions();
        loadJobs();
      });

      item.append(title, statRow, meta, filter);
      return item;
    }

    function renderQuickPresets() {
      els.quickPresets.replaceChildren();
      for (const [key, label] of QUICK_PRESETS) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "preset-chip" + (isQuickPresetActive(key) ? " active" : "");
        button.append(createIcon(QUICK_PRESET_ICONS[key] || "filter", "icon icon-sm"), document.createTextNode(label));
        button.addEventListener("click", () => applyQuickPreset(key));
        els.quickPresets.append(button);
      }
    }

    function applyQuickPreset(key) {
      state.filters.quickPreset = key;
      state.filters.search = "";
      els.searchInput.value = "";
      if (key === "needs_action") {
        state.filters.actionScope = "needs_action";
        state.filters.decision = "all";
        state.filters.manualStatus = "all";
      } else if (key === "current_run") {
        state.filters.run = effectiveActiveRunId() || latestRunId() || "all";
        state.filters.actionScope = "all";
      } else if (key === "apply_first") {
        state.filters.actionScope = "needs_action";
        state.filters.decision = "APPLY_FIRST";
        state.filters.manualStatus = "all";
      } else if (key === "good_options") {
        state.filters.actionScope = "needs_action";
        state.filters.decision = "GOOD_OPTIONS";
        state.filters.manualStatus = "all";
      } else if (key === "easy_apply") {
        state.filters.applyMethod = "easy_apply";
        state.filters.actionScope = "needs_action";
      } else if (key === "applied") {
        state.filters.actionScope = "all";
        state.filters.manualStatus = "applied";
      } else if (key === "irrelevant") {
        state.filters.actionScope = "all";
        state.filters.manualStatus = "irrelevant";
      } else {
        state.filters.actionScope = "all";
      }
      syncFilterOptions();
      loadJobs();
    }

    function isQuickPresetActive(key) {
      if (key === "needs_action") return state.filters.actionScope === "needs_action" && state.filters.decision === "all" && state.filters.manualStatus === "all";
      if (key === "current_run") return state.filters.run !== "all" && state.filters.quickPreset === "current_run";
      if (key === "apply_first") return state.filters.decision === "APPLY_FIRST";
      if (key === "good_options") return state.filters.decision === "GOOD_OPTIONS";
      if (key === "easy_apply") return state.filters.applyMethod === "easy_apply";
      if (key === "applied") return state.filters.manualStatus === "applied";
      if (key === "irrelevant") return state.filters.manualStatus === "irrelevant";
      return state.filters.quickPreset === key;
    }

    function renderJobs() {
      const visibleJobs = filteredJobs();
      const grouped = {
        APPLY_FIRST: [],
        GOOD_OPTIONS: [],
        LOW_PROBABILITY: [],
        REJECTED: []
      };
      for (const job of visibleJobs) {
        const category = grouped[job.decision_category] ? job.decision_category : "LOW_PROBABILITY";
        grouped[category].push(job);
      }

      renderList(els.listApply, grouped.APPLY_FIRST, "APPLY_FIRST");
      renderList(els.listGood, grouped.GOOD_OPTIONS, "GOOD_OPTIONS");
      renderList(els.listLow, grouped.LOW_PROBABILITY, "LOW_PROBABILITY");
      renderList(els.listRejected, grouped.REJECTED, "REJECTED");
      renderCompactList(visibleJobs);

      els.countApply.textContent = grouped.APPLY_FIRST.length;
      els.countGood.textContent = grouped.GOOD_OPTIONS.length;
      els.countLow.textContent = grouped.LOW_PROBABILITY.length;
      els.countRejected.textContent = grouped.REJECTED.length;
      if (state.apiAvailable) {
        els.countApply.textContent = numeric(state.jobsByDecision.APPLY_FIRST);
        els.countGood.textContent = numeric(state.jobsByDecision.GOOD_OPTIONS);
        els.countLow.textContent = numeric(state.jobsByDecision.LOW_PROBABILITY);
        els.countRejected.textContent = numeric(state.jobsByDecision.REJECTED);
      }
      if (els.jobsTableFooter) {
        els.jobsTableFooter.classList.toggle("hidden", state.jobsTotal === 0);
        els.jobsVisibleCount.textContent = `Showing ${visibleJobs.length} of ${state.jobsTotal} matching jobs`;
        els.loadMoreJobsButton.classList.toggle("hidden", !state.jobsHasMore);
        els.loadMoreJobsButton.textContent = `Show ${Math.min(100, state.jobsTotal - visibleJobs.length)} more jobs`;
      }

      for (const column of document.querySelectorAll(".column")) {
        const key = column.dataset.column;
        column.classList.toggle("hidden", state.filters.decision !== "all" && state.filters.decision !== key);
      }
    }

    function renderLayoutMode() {
      const listMode = state.filters.viewMode === "list";
      els.boardView.classList.toggle("hidden", listMode);
      els.compactList.classList.toggle("hidden", !listMode);
      els.boardViewButton.classList.toggle("active", !listMode);
      els.listViewButton.classList.toggle("active", listMode);
      els.boardViewButton.setAttribute("aria-pressed", String(!listMode));
      els.listViewButton.setAttribute("aria-pressed", String(listMode));
    }

    function renderList(container, items, decisionKey) {
      container.replaceChildren();
      if (!items.length) {
        container.append(emptyColumnState(decisionKey));
        return;
      }
      container.append(...items.map(jobCard));
    }

    function emptyColumnState(decisionKey) {
      const empty = document.createElement("div");
      empty.className = "empty empty-state";
      const title = document.createElement("strong");
      const copy = document.createElement("p");
      const label = DECISIONS.find(([value]) => value === decisionKey);
      title.textContent = "No " + (label ? label[1].toLowerCase() : "jobs") + " here.";
      copy.textContent = state.filters.actionScope === "needs_action"
        ? "This view only shows unreviewed Apply First and Good Options jobs."
        : "No jobs match the current filters for this column.";
      empty.append(title, copy);
      return empty;
    }

    function renderCompactList(items) {
      els.compactList.replaceChildren();
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "empty empty-state";
        const title = document.createElement("strong");
        title.textContent = "No jobs match these filters.";
        const copy = document.createElement("p");
        copy.textContent = state.filters.actionScope === "needs_action"
          ? "Actionable jobs are unreviewed Apply First and Good Options roles."
          : "Try clearing a search term, status, run, or apply-method filter.";
        empty.append(title, copy);
        els.compactList.append(empty);
        return;
      }
      els.compactList.append(...items.map(compactJobRow));
    }

    function compactJobRow(job) {
      const status = manualStatus(job);
      const article = document.createElement("article");
      article.className = "compact-job " + safe(job.decision_category) + " manual-" + status;
      article.dataset.jobKey = safe(job.job_key) || jobIdentity(job);

      const main = document.createElement("div");
      main.className = "compact-main";

      const titleLine = document.createElement("div");
      titleLine.className = "compact-title";
      const link = document.createElement(job.url ? "a" : "span");
      link.textContent = safe(job.title) || "Untitled job";
      if (job.url) {
        link.href = job.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      titleLine.append(link);

      const pillRow = document.createElement("div");
      pillRow.className = "compact-pills";
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = String(Number.isFinite(Number(job.score)) ? Number(job.score) : 0);
      const run = document.createElement("span");
      run.className = "run-badge";
      run.textContent = shortRunLabel(job) || "Run";
      run.title = safe(job.run_label) || safe(job.run_id);
      const decision = decisionChip(job.decision_category, decisionLabel(job));
      pillRow.append(score, run, decision);
      const methodBadge = applyMethodBadge(job);
      if (methodBadge) {
        pillRow.append(methodBadge);
      }
      if (status !== "unreviewed") {
        pillRow.append(badge(labelize(status), "status " + status));
      }

      const meta = document.createElement("div");
      meta.className = "subline";
      meta.textContent = [
        safe(job.company),
        safe(job.location),
        safe(job.query),
        job.page_number ? "Page " + job.page_number : "",
        job.processed_at ? formatDateTime(job.processed_at) : ""
      ].filter(Boolean).join(" | ");

      const reason = document.createElement("div");
      reason.className = "reason";
      reason.textContent = safe(job.reason) || safe(job.terminal_status) || "No reason recorded";

      const badges = document.createElement("div");
      badges.className = "badges";
      badges.append(badge(job.domain_label || labelize(job.domain_category), "domain"));
      for (const flag of importantFlags(job).slice(0, 5)) {
        badges.append(badge(labelize(flag), isRiskFlag(flag) ? "risk" : ""));
      }

      const actions = document.createElement("div");
      actions.className = "compact-actions";
      actions.append(actionRow(job, status));

      main.append(titleLine, pillRow, meta, reason, badges);
      article.append(main, actions);
      return article;
    }

    function jobCard(job) {
      const article = document.createElement("article");
      const status = manualStatus(job);
      article.className = "job " + safe(job.decision_category) + " manual-" + status;
      article.dataset.jobKey = safe(job.job_key) || jobIdentity(job);

      const titleRow = document.createElement("div");
      titleRow.className = "job-title";
      const titleMain = document.createElement("div");
      titleMain.className = "job-title-main";
      const link = document.createElement(job.url ? "a" : "span");
      link.textContent = safe(job.title) || "Untitled job";
      if (job.url) {
        link.href = job.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      titleMain.append(link);
      const titleMeta = document.createElement("div");
      titleMeta.className = "job-title-meta";
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = String(Number.isFinite(Number(job.score)) ? Number(job.score) : 0);
      const runBadge = document.createElement("span");
      runBadge.className = "run-badge";
      runBadge.textContent = shortRunLabel(job) || "Run";
      runBadge.title = safe(job.run_label) || safe(job.run_id);
      const decision = decisionChip(job.decision_category, decisionLabel(job));
      titleMeta.append(score, runBadge, decision);
      const methodBadge = applyMethodBadge(job);
      if (methodBadge) {
        titleMeta.append(methodBadge);
      }
      titleRow.append(titleMain, titleMeta);

      const subline = document.createElement("div");
      subline.className = "subline";
      subline.textContent = [
        safe(job.company),
        safe(job.location),
        safe(job.query)
      ].filter(Boolean).join(" | ");

      const reason = document.createElement("div");
      reason.className = "reason";
      reason.textContent = safe(job.reason) || safe(job.terminal_status) || "No reason recorded";

      const badges = document.createElement("div");
      badges.className = "badges";
      badges.append(badge(job.domain_label || labelize(job.domain_category), "domain"));
      if (status !== "unreviewed") {
        badges.append(badge(labelize(status), "status " + status));
      }
      for (const flag of importantFlags(job).slice(0, 8)) {
        badges.append(badge(labelize(flag), isRiskFlag(flag) ? "risk" : ""));
      }

      const details = document.createElement("div");
      details.className = "subline";
      details.textContent = [
        job.page_number ? "Page " + job.page_number : "",
        job.processed_at ? formatDateTime(job.processed_at) : "",
        safe(job.source_stage)
      ].filter(Boolean).join(" | ");

      article.append(titleRow, subline, reason, badges, details, actionRow(job, status));
      return article;
    }

    function actionRow(job, status) {
      const row = document.createElement("div");
      row.className = "job-actions";
      row.append(
        openJobButton(job),
        copyLinkButton(job),
        actionButton("Applied", "applied", job, status, "Mark job as applied"),
        actionButton("Irrelevant", "irrelevant", job, status, "Mark job as irrelevant")
      );
      return row;
    }

    function openJobButton(job) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "job-action utility";
      setIconText(button, "external-link", "Open job");
      button.title = "Open the job page in a new tab";
      button.setAttribute("aria-label", "Open job: " + (safe(job.title) || "Untitled job"));
      button.disabled = !safe(job.url);
      button.addEventListener("click", () => {
        if (!safe(job.url)) return;
        window.open(job.url, "_blank", "noopener,noreferrer");
      });
      return button;
    }

    function copyLinkButton(job) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "job-action utility";
      setIconText(button, "copy", "Copy link");
      button.title = "Copy the job URL";
      button.setAttribute("aria-label", "Copy link for: " + (safe(job.title) || "Untitled job"));
      button.disabled = !safe(job.url);
      button.addEventListener("click", () => copyJobLink(job));
      return button;
    }

    function actionButton(label, targetStatus, job, currentStatus, title) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "job-action" + (targetStatus === currentStatus ? " active" : "") + (targetStatus === "irrelevant" ? " danger" : "");
      setIconText(button, targetStatus === "irrelevant" ? "archive" : "check", label);
      const nextStatus = targetStatus === currentStatus ? "unreviewed" : targetStatus;
      button.setAttribute("aria-pressed", String(targetStatus === currentStatus));
      button.setAttribute("aria-label", label + ": " + (safe(job.title) || "Untitled job"));
      button.title = state.apiAvailable
        ? (nextStatus === "unreviewed" ? "Click again to remove this status" : title)
        : "Run python serve_dashboard.py to save status";
      button.disabled = !state.apiAvailable || state.savingJobKey === (safe(job.job_key) || jobIdentity(job));
      button.addEventListener("click", () => saveManualStatus(job, nextStatus, { previousStatus: currentStatus }));
      return button;
    }

    async function copyJobLink(job) {
      const url = safe(job.url);
      if (!url) return;
      try {
        await navigator.clipboard.writeText(url);
        setStatus(state.data.active_run_id ? "live" : "", "Link copied");
      } catch (_error) {
        setStatus("error", "Could not copy link");
      }
    }

    async function saveManualStatus(job, status, options = {}) {
      const key = safe(job.job_key) || jobIdentity(job);
      const previousStatus = options.previousStatus || manualStatus(job);
      state.savingJobKey = key;
      updateUndoButtonState();
      renderJobs();
      try {
        const response = await fetch(API_STATUS_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, job, compact: true })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "Status save failed");
        }
        const savedRecord = payload.record || {};
        const savedKey = safe(payload.job_key) || key;
        for (const currentJob of jobs()) {
          if ((safe(currentJob.job_key) || jobIdentity(currentJob)) !== savedKey) continue;
          currentJob.manual_status = safe(savedRecord.status) || status || "unreviewed";
          currentJob.manual_status_label = safe(savedRecord.status_label) || labelize(currentJob.manual_status);
          currentJob.application_stage = safe(savedRecord.application_stage);
          currentJob.application_stage_label = safe(savedRecord.application_stage_label);
          currentJob.application_updated_at = safe(savedRecord.application_updated_at);
        }
        state.savingJobKey = "";
        state.apiAvailable = true;
        setStatus(state.data.active_run_id ? "live" : "", status === "unreviewed" ? "Status cleared" : "Status saved");
        if (options.trackUndo !== false && previousStatus !== status) {
          pushManualUndo({ job, previousStatus, newStatus: status });
        }
        if (!options.silent) {
          showUndoToast(job, previousStatus, status);
        }
        await loadData();
        return true;
      } catch (error) {
        state.savingJobKey = "";
        updateUndoButtonState();
        setStatus("error", "Run python serve_dashboard.py to save status");
        renderJobs();
        return false;
      }
    }

    function showUndoToast(job, previousStatus, newStatus) {
      if (!els.toast) return;
      window.clearTimeout(state.toastTimer);
      els.toast.textContent = "";
      const message = document.createElement("span");
      const nextLabel = newStatus === "unreviewed" ? "Status cleared" : "Marked " + labelize(newStatus);
      message.textContent = nextLabel + ".";
      const undo = document.createElement("button");
      undo.type = "button";
      undo.textContent = "Undo";
      undo.addEventListener("click", () => {
        hideUndoToast();
        undoLastManualStatus();
      });
      els.toast.append(message, undo);
      els.toast.classList.add("visible");
      state.toastTimer = window.setTimeout(hideUndoToast, 5000);
    }

    function hideUndoToast() {
      if (!els.toast) return;
      window.clearTimeout(state.toastTimer);
      els.toast.classList.remove("visible");
    }

    function pushManualUndo(action) {
      const compactJob = JSON.parse(JSON.stringify(action.job || {}));
      state.manualUndoStack.push({
        job: compactJob,
        previousStatus: action.previousStatus || "unreviewed",
        newStatus: action.newStatus || "unreviewed"
      });
      if (state.manualUndoStack.length > 50) {
        state.manualUndoStack.shift();
      }
      updateUndoButtonState();
    }

    async function undoLastManualStatus() {
      if (!state.manualUndoStack.length || !state.apiAvailable) return;
      const action = state.manualUndoStack.pop();
      updateUndoButtonState();
      const currentJob = findCurrentJob(action.job) || action.job;
      hideUndoToast();
      const saved = await saveManualStatus(currentJob, action.previousStatus || "unreviewed", {
        previousStatus: action.newStatus || manualStatus(currentJob),
        silent: true,
        trackUndo: false
      });
      if (!saved) {
        state.manualUndoStack.push(action);
        updateUndoButtonState();
        return;
      }
      setStatus(state.data.active_run_id ? "live" : "", "Undo applied");
      updateUndoButtonState();
    }

    function updateUndoButtonState() {
      if (!els.undoButton) return;
      const hasUndo = state.manualUndoStack.length > 0;
      els.undoButton.disabled = !state.apiAvailable || !hasUndo || Boolean(state.savingJobKey);
      els.undoButton.title = hasUndo
        ? "Undo the last Applied/Irrelevant status change"
        : "No manual status changes to undo";
    }

    function findCurrentJob(job) {
      const key = safe(job.job_key) || jobIdentity(job);
      return jobs().find((item) => (safe(item.job_key) || jobIdentity(item)) === key);
    }

    function badge(text, extraClass) {
      const span = document.createElement("span");
      span.className = "badge" + (extraClass ? " " + extraClass : "");
      const iconName = extraClass && extraClass.includes("domain")
        ? "briefcase"
        : extraClass && extraClass.includes("risk")
          ? "filter"
          : extraClass && extraClass.includes("status")
            ? (extraClass.includes("irrelevant") ? "archive" : "check")
            : "";
      if (iconName) span.append(createIcon(iconName, "icon icon-sm"));
      span.append(document.createTextNode(text || "Other"));
      return span;
    }

    function decisionChip(category, text) {
      const span = document.createElement("span");
      const normalized = safe(category);
      span.className = "decision-chip " + normalized;
      span.append(createIcon(DECISION_ICONS[normalized] || "bar-chart", "icon icon-sm"), document.createTextNode(text || labelize(normalized)));
      return span;
    }

    function applyMethodBadge(job) {
      const method = applyMethod(job);
      if (method !== "easy_apply") return null;
      const span = document.createElement("span");
      span.className = "apply-method-badge easy";
      span.append(createIcon("briefcase", "icon icon-sm"), document.createTextNode("Easy Apply"));
      span.title = "This LinkedIn job showed an Easy Apply button when scouted";
      return span;
    }

    function createIcon(name, className = "icon") {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", className);
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#icon-" + name);
      svg.append(use);
      return svg;
    }

    function setIconText(element, iconName, text) {
      element.replaceChildren(createIcon(iconName, "icon icon-sm"), document.createTextNode(text));
    }

    function filteredJobs() {
      const text = state.filters.search.trim().toLowerCase();
      let output = jobs().filter((job) => {
        if (state.filters.actionScope === "needs_action" && !needsAction(job)) return false;
        if (state.filters.run !== "all" && job.run_id !== state.filters.run) return false;
        if (state.filters.decision !== "all" && job.decision_category !== state.filters.decision) return false;
        if (state.filters.domain !== "all" && job.domain_category !== state.filters.domain) return false;
        if (state.filters.flag !== "all" && !(Array.isArray(job.flags) && job.flags.includes(state.filters.flag))) return false;
        if (state.filters.applyMethod !== "all" && applyMethod(job) !== state.filters.applyMethod) return false;
        if (state.filters.manualStatus !== "all" && manualStatus(job) !== state.filters.manualStatus) return false;
        if (state.filters.quickPreset === "dutch_risk" && !hasDutchRisk(job)) return false;
        if (state.filters.quickPreset === "remote_hybrid" && !isRemoteOrHybrid(job)) return false;
        if (text && !searchBlob(job).includes(text)) return false;
        return true;
      });

      output = [...output].sort((a, b) => {
        if (state.filters.sort === "score") return numeric(b.score) - numeric(a.score);
        if (state.filters.sort === "company") return safe(a.company).localeCompare(safe(b.company));
        if (state.filters.sort === "location") return safe(a.location).localeCompare(safe(b.location));
        return safe(b.processed_at).localeCompare(safe(a.processed_at));
      });
      return output;
    }

    function needsAction(job) {
      return ["APPLY_FIRST", "GOOD_OPTIONS"].includes(safe(job.decision_category))
        && manualStatus(job) === "unreviewed";
    }

    function latestRunId() {
      const runs = Array.isArray(state.data.runs) ? state.data.runs : [];
      const last = runs.length ? runs[runs.length - 1] : null;
      return last ? safe(last.run_id) : "";
    }

    function importantFlags(job) {
      const flags = Array.isArray(job.flags) ? job.flags : [];
      return flags.slice().sort((a, b) => Number(isRiskFlag(b)) - Number(isRiskFlag(a)));
    }

    function isRiskFlag(flag) {
      return /(risk|dutch|commute|low_pay|seniority|manual_review|contract|sales|technical)/i.test(safe(flag));
    }

    function hasDutchRisk(job) {
      return /dutch|nederlands|taal|language/i.test(searchBlob(job));
    }

    function isRemoteOrHybrid(job) {
      return /remote|hybrid|thuis|from home/i.test(searchBlob(job));
    }

    function jobs() {
      return Array.isArray(state.data.jobs) ? state.data.jobs : [];
    }

    function searchBlob(job) {
      return [
        job.title,
        job.company,
        job.location,
        job.query,
        job.reason,
        job.domain_label,
        job.apply_method_label,
        job.manual_status_label,
        ...(Array.isArray(job.flags) ? job.flags : [])
      ].map(safe).join(" ").toLowerCase();
    }

    function applyMethod(job) {
      const method = safe(job.apply_method).toLowerCase().replace(/[\s-]+/g, "_");
      if (APPLY_METHODS.some(([value]) => value === method)) return method;
      if (job.easy_apply === true || (Array.isArray(job.flags) && job.flags.includes("easy_apply"))) return "easy_apply";
      if (Array.isArray(job.flags) && job.flags.includes("external_apply")) return "external_apply";
      return "unknown";
    }

    function manualStatus(job) {
      const status = safe(job.manual_status).toLowerCase();
      return MANUAL_STATUSES.some(([value]) => value === status) ? status : "unreviewed";
    }

    function manualStatusCounts(items) {
      const counts = { unreviewed: 0, applied: 0, irrelevant: 0 };
      for (const job of Array.isArray(items) ? items : []) {
        counts[manualStatus(job)] += 1;
      }
      return counts;
    }

    function jobIdentity(job) {
      if (job.job_id) return safe(job.board || "linkedin") + ":job_id:" + safe(job.job_id);
      if (job.url) return safe(job.board || "linkedin") + ":url:" + safe(job.url).toLowerCase();
      return [
        safe(job.board || "linkedin"),
        safe(job.title).toLowerCase(),
        safe(job.company).toLowerCase()
      ].join(":");
    }

    function shortRunLabel(job) {
      const label = safe(job.run_label);
      const match = label.match(/Run\s+\d+/i);
      if (match) return match[0].replace(/\s+/, " ");
      return label || safe(job.run_id);
    }

    function decisionLabel(job) {
      const category = safe(job.decision_category);
      const found = DECISIONS.find(([value]) => value === category);
      return found ? found[1] : labelize(category || "LOW_PROBABILITY");
    }

    async function loadRunControl() {
      try {
        const response = await fetch(API_RUN_CONTROL_URL + "?t=" + Date.now(), { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        state.runControl = await response.json();
        state.runControlAvailable = true;
      } catch (_error) {
        state.runControlAvailable = false;
        state.runControl = null;
      }
      renderRunControl();
      renderHome();
    }

    function renderRunControl() {
      const control = state.runControl || {};
      const active = isRunActive();
      const interrupted = control.status === "interrupted";
      const available = state.runControlAvailable;
      if (els.runControlNotice) {
        els.runControlNotice.textContent = available
          ? "Dashboard controller is available. Commands are restricted to approved scout workflows."
          : "Run python serve_dashboard.py to start scout runs from this dashboard.";
      }
      if (els.runStatusBadge) {
        setIconText(els.runStatusBadge, active ? "activity" : "clock", active ? "Running" : labelize(control.status || "Idle"));
        els.runStatusBadge.className = "decision-chip " + (
          active ? "APPLY_FIRST" : interrupted ? "INTERRUPTED" : ""
        );
      }
      if (els.runStatusText) {
        els.runStatusText.textContent = available
          ? runControlStatusText(control)
          : "Controller unavailable from this page.";
      }
      if (els.runLogTail) {
        els.runLogTail.textContent = safe(control.log_tail) || "No run log yet.";
      }
      if (els.runResumeMode) {
        els.runResumeMode.disabled = !available || !control.resume_available;
        els.runResumeMode.title = control.resume_available ? "Resume saved scout progress" : "No resumable scout progress found";
      }
      if (els.startRunButton) {
        els.startRunButton.disabled = !available || active;
      }
      for (const button of [els.stopAfterJobButton, els.stopAfterPageButton, els.stopNowButton]) {
        if (button) button.disabled = !available || !active;
      }
      updateWorkflowFields();
      syncGlobalRunStatus();
      renderScoutWorkspace();
      renderHome();
    }

    function runControlStatusText(control) {
      if (control.active) {
        const detached = control.detached
          ? " Monitoring continued after the dashboard restarted."
          : "";
        return "Running " + (safe(control.workflow_label) || "scout") + " since " + (formatDateTime(control.started_at) || "now") + "." + detached;
      }
      if (control.status === "interrupted") return "Last run was interrupted. " + resumeContextText(control);
      if (control.status === "failed") return "Last run failed. Review the log tail before resuming.";
      if (control.status === "stopped") return "Last run was stopped. Resume is available when scout progress exists.";
      if (control.status === "completed") return "Last run completed.";
      return "No active scout run.";
    }

    function isRunActive() {
      if (state.runControlAvailable) return Boolean(state.runControl?.active);
      return Boolean(state.data.active_run_id);
    }

    function effectiveActiveRunId() {
      if (state.runControlAvailable) {
        return state.runControl?.active
          ? safe(state.runControl.run_id || state.data.active_run_id)
          : "";
      }
      return safe(state.data.active_run_id);
    }

    function resumeContextText(control) {
      const context = control.resume_context || {};
      const queryPosition = numeric(context.current_query_index) && numeric(context.total_queries)
        ? `Query ${numeric(context.current_query_index)} of ${numeric(context.total_queries)}`
        : "";
      const query = safe(context.current_query);
      const page = numeric(context.current_page_number)
        ? `page ${numeric(context.current_page_number)}`
        : "";
      const checkpoint = [queryPosition, query, page].filter(Boolean).join(": ");
      return [
        checkpoint ? `Saved at ${checkpoint}.` : "Saved progress is available.",
        safe(context.restart_note)
      ].filter(Boolean).join(" ");
    }

    function syncGlobalRunStatus() {
      if (isRunActive()) {
        setStatus("live", state.runControl?.detached ? "Run active (monitored)" : "Run active");
      } else if (state.runControlAvailable && state.runControl?.status === "interrupted") {
        setStatus("interrupted", "Run interrupted");
      } else {
        setStatus("", state.apiAvailable ? "Ready" : "Read-only");
      }
    }

    function openRunScoutModal() {
      state.lastFocusedBeforeModal = document.activeElement;
      els.runScoutOverlay.classList.remove("hidden");
      const modal = els.runScoutOverlay.querySelector(".modal");
      if (modal) modal.scrollTop = 0;
      updateWorkflowFields();
      loadRunControl();
      els.runWorkflow.focus();
    }

    function closeRunScoutModal() {
      els.runScoutOverlay.classList.add("hidden");
      if (state.lastFocusedBeforeModal && typeof state.lastFocusedBeforeModal.focus === "function") {
        state.lastFocusedBeforeModal.focus();
      }
    }

    function trapRunScoutFocus(event) {
      if (event.key !== "Tab" || els.runScoutOverlay.classList.contains("hidden")) return;
      const candidates = Array.from(
        els.runScoutOverlay.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => !element.hidden && element.offsetParent !== null);
      if (!candidates.length) {
        event.preventDefault();
        return;
      }
      const first = candidates[0];
      const last = candidates[candidates.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    function updateWorkflowFields() {
      const workflow = els.runWorkflow.value;
      const presentation = workflowPresentation(workflow, {
        runControlAvailable: state.runControlAvailable,
        resumeAvailable: Boolean(state.runControl?.resume_available),
      });
      els.runQuery.disabled = !presentation.needsQuery;
      els.runQuery.title = presentation.needsQuery
        ? "Search query for this workflow"
        : "Not used here; multi-query runs read search_queries.txt.";
      els.runLocation.disabled = presentation.disableLocation;
      els.runMaxPages.disabled = presentation.disablePages;
      els.runBrowser.disabled = presentation.disableBrowser;
      els.runHumanMode.disabled = presentation.disableHumanMode;
      els.runResumeMode.disabled = presentation.disableResume;
      els.runFreshMode.disabled = !presentation.supportsFresh;
      if (workflow === "linkedin_multi_fresh") {
        els.runFreshMode.checked = true;
      }
      if (!presentation.supportsFresh) {
        els.runFreshMode.checked = false;
      }
      if (els.runAiBudgetMode) {
        els.runAiBudgetMode.disabled = !presentation.supportsFresh || !els.runFreshMode.checked;
        els.runAiBudgetMode.title = presentation.supportsFresh
          ? "Smart Guard stops low-yield runs early, Deep Search continues longer, Off disables AI budget stops."
          : "AI budget mode only applies to fresh LinkedIn scouting.";
      }
      if (els.runWorkflowHint) {
        els.runWorkflowHint.replaceChildren();
        const title = document.createElement("strong");
        title.textContent = presentation.hint[0];
        const copy = document.createElement("span");
        copy.textContent = presentation.hint[1];
        els.runWorkflowHint.append(title, copy);
      }
      if (els.startRunButton) {
        setIconText(els.startRunButton, presentation.startIcon, presentation.startLabel);
      }
    }

    async function startDashboardRun() {
      if (!state.runControlAvailable) return;
      const payload = {
        workflow: els.runWorkflow.value,
        query: els.runQuery.value,
        location: els.runLocation.value,
        max_pages: els.runMaxPages.value,
        browser: els.runBrowser.value,
        ai_budget_mode: els.runAiBudgetMode ? els.runAiBudgetMode.value : "smart",
        human_mode: els.runHumanMode.checked,
        fresh: els.runFreshMode.checked,
        resume: els.runResumeMode.checked
      };
      await postRunControl("start", payload);
    }

    async function stopDashboardRun(mode) {
      await postRunControl("stop", { mode });
    }

    async function postRunControl(action, payload) {
      try {
        const response = await fetch(API_RUN_CONTROL_URL + "/" + action, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload || {})
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || "Run control request failed");
        }
        state.runControl = data.state || data;
        state.runControlAvailable = true;
        setStatus(state.data.active_run_id ? "live" : "", action === "start" ? "Scout started" : "Stop requested");
      } catch (error) {
        setStatus("error", safe(error.message) || "Run control failed");
      }
      renderRunControl();
    }

    function bindControls() {
      els.mobileNavToggle.addEventListener("click", () => {
        if (els.appSidebar.classList.contains("mobile-open")) {
          closeMobileNavigation();
        } else {
          openMobileNavigation();
        }
      });
      els.mobileNavBackdrop.addEventListener("click", () => closeMobileNavigation());
      window.addEventListener("resize", syncMobileNavigation);
      for (const button of els.appNavButtons) {
        button.addEventListener("click", () => navigateToPage(button.dataset.appPage));
      }
      els.openProfileSetupButton.addEventListener("click", () => navigateToPage("profile"));
      els.homeStartScoutButton.addEventListener("click", () => openScoutModal());
      els.homeReviewJobsButton.addEventListener("click", () => navigateToPage("jobs"));
      els.homeApplicationsButton.addEventListener("click", () => navigateToPage("applications"));
      els.homeRunDetailsButton.addEventListener("click", () => navigateToPage("scout"));
      els.homeTrackApplicationsButton.addEventListener("click", () => navigateToPage("applications"));
      els.homeRunsButton.addEventListener("click", () => navigateToPage("runs"));
      els.saveProfileButton.addEventListener("click", saveProfile);
      els.profileForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveProfile();
      });
      els.uploadCvButton.addEventListener("click", uploadCv);
      els.addExperienceButton.addEventListener("click", () => {
        addRepeaterEntry(els.experienceRepeater, "experience", PROFILE_EXPERIENCE_FIELDS);
      });
      els.addEducationButton.addEventListener("click", () => {
        addRepeaterEntry(els.educationRepeater, "education", PROFILE_EDUCATION_FIELDS);
      });
      els.addLanguageButton.addEventListener("click", () => {
        addRepeaterEntry(els.languageRepeater, "language", PROFILE_LANGUAGE_FIELDS);
      });
      els.saveStrategyButton.addEventListener("click", saveStrategy);
      els.strategyForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveStrategy();
      });
      document.getElementById("strategyQueries").addEventListener("input", updateStrategyQueryCount);
      els.openScoutWorkspaceRunButton.addEventListener("click", () => openScoutModal());
      els.startRecommendedScoutButton.addEventListener("click", () => openScoutModal());
      els.openSearchStrategyButton.addEventListener("click", () => navigateToPage("strategy"));
      els.openAiSettingsButton.addEventListener("click", () => navigateToPage("settings"));
      els.resumeScoutButton.addEventListener("click", () => openScoutModal({ resume: true }));
      els.refreshLegacyStatsButton.addEventListener("click", loadLegacyTools);
      els.validateBoardsButton.addEventListener("click", openValidationWorkflow);
      els.saveAiSettingsButton.addEventListener("click", saveAiSettings);
      els.saveBoardSettingsButton.addEventListener("click", saveBoardSettings);
      els.refreshApplicationsButton.addEventListener("click", loadApplications);
      els.applicationSearch.addEventListener("input", () => {
        state.applicationFilters.search = els.applicationSearch.value;
        window.clearTimeout(state.applicationSearchTimer);
        state.applicationSearchTimer = window.setTimeout(() => loadApplications(), 250);
      });
      els.applicationStageFilter.addEventListener("change", () => {
        state.applicationFilters.stage = els.applicationStageFilter.value;
        loadApplications();
      });
      els.loadMoreApplicationsButton.addEventListener("click", () => {
        loadApplications({ append: true });
      });
      els.saveAssistantKnowledgeButton.addEventListener("click", saveAssistantKnowledge);
      els.addApplicationAnswerButton.addEventListener("click", () => addAnswerEditorRow(els.applicationAnswersEditor, "", "", "application"));
      els.addLearnedAnswerButton.addEventListener("click", () => addAnswerEditorRow(els.learnedAnswersEditor, "", "", "learned"));
      els.findAssistantAnswerButton.addEventListener("click", findAssistantAnswer);
      els.createLocalDraftButton.addEventListener("click", () => generateAssistantDraft("local"));
      els.createAiDraftButton.addEventListener("click", () => generateAssistantDraft("ai"));
      els.copyAssistantDraftButton.addEventListener("click", copyAssistantDraft);
      els.downloadAssistantDraftButton.addEventListener("click", downloadAssistantDraft);
      els.refreshMaintenanceButton.addEventListener("click", loadMaintenance);
      els.createBackupButton.addEventListener("click", createMaintenanceBackup);
      els.pruneLogsButton.addEventListener("click", pruneMaintenanceLogs);
      els.copyLogButton.addEventListener("click", copyMaintenanceLog);
      els.themeToggle.addEventListener("click", toggleTheme);
      els.searchInput.addEventListener("input", () => {
        state.filters.search = els.searchInput.value;
        state.filters.quickPreset = "";
        renderQuickPresets();
        queueJobsReload();
      });
      for (const [element, key] of [
        [els.actionFilter, "actionScope"],
        [els.runFilter, "run"],
        [els.decisionFilter, "decision"],
        [els.domainFilter, "domain"],
        [els.flagFilter, "flag"],
        [els.applyMethodFilter, "applyMethod"],
        [els.manualStatusFilter, "manualStatus"],
        [els.sortFilter, "sort"]
      ]) {
        element.addEventListener("change", () => {
          state.filters[key] = element.value;
          state.filters.quickPreset = "";
          renderQuickPresets();
          loadJobs();
        });
      }
      for (const button of [els.boardViewButton, els.listViewButton]) {
        button.addEventListener("click", () => {
          state.filters.viewMode = button.dataset.viewMode || "board";
          renderJobs();
          renderLayoutMode();
        });
      }
      els.undoButton.addEventListener("click", undoLastManualStatus);
      els.refreshButton.addEventListener("click", loadData);
      els.loadMoreJobsButton.addEventListener("click", () => loadJobs({ append: true }));
      els.toggleRunHistoryButton.addEventListener("click", () => {
        state.runHistoryExpanded = !state.runHistoryExpanded;
        renderRunHistory();
      });
      els.runScoutButton.addEventListener("click", openRunScoutModal);
      els.closeRunScoutButton.addEventListener("click", closeRunScoutModal);
      els.runScoutOverlay.addEventListener("click", (event) => {
        if (event.target === els.runScoutOverlay) closeRunScoutModal();
      });
      els.runWorkflow.addEventListener("change", updateWorkflowFields);
      els.runFreshMode.addEventListener("change", updateWorkflowFields);
      els.startRunButton.addEventListener("click", startDashboardRun);
      els.refreshRunControlButton.addEventListener("click", loadRunControl);
      els.stopAfterJobButton.addEventListener("click", () => stopDashboardRun("after_current_job"));
      els.stopAfterPageButton.addEventListener("click", () => stopDashboardRun("after_current_page"));
      els.stopNowButton.addEventListener("click", () => stopDashboardRun("now"));
      window.addEventListener("keydown", (event) => {
        trapMobileNavigationFocus(event);
        if (event.key === "Escape" && els.appSidebar.classList.contains("mobile-open")) {
          closeMobileNavigation();
          return;
        }
        trapRunScoutFocus(event);
        if (event.key === "Escape" && !els.runScoutOverlay.classList.contains("hidden")) {
          closeRunScoutModal();
          return;
        }
        if (!event.ctrlKey || event.shiftKey || event.altKey || event.metaKey) return;
        if (event.key.toLowerCase() !== "z") return;
        const active = document.activeElement;
        const tag = active && active.tagName ? active.tagName.toLowerCase() : "";
        if (tag === "input" || tag === "textarea" || tag === "select" || (active && active.isContentEditable)) return;
        event.preventDefault();
        undoLastManualStatus();
      });
    }

    bindControls();
    syncMobileNavigation();
    navigateToPage(state.currentPage, { persist: false });
    applyTheme(state.theme, false);
    render();
    loadData();
    loadRunControl();
    window.setInterval(loadData, POLL_MS);
    window.setInterval(loadRunControl, POLL_MS);
