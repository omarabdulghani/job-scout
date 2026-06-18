import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiveDashboardHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html_path = ROOT / "recommended_jobs_dashboard.html"
        cls.document = cls.html_path.read_text(encoding="utf-8")
        cls.frontend_files = [
            ROOT / "dashboard" / "styles.css",
            ROOT / "dashboard" / "app.js",
            *sorted((ROOT / "dashboard" / "modules").glob("*.js")),
        ]
        cls.html = cls.document + "\n" + "\n".join(
            path.read_text(encoding="utf-8")
            for path in cls.frontend_files
        )

    def test_dashboard_file_exists(self):
        self.assertTrue(self.html_path.exists())

    def test_dashboard_polls_stable_json_file(self):
        self.assertIn('dataFile: "data/recommended_jobs_dashboard_data.json"', self.html)
        self.assertIn('dashboardData: "/api/dashboard-data"', self.html)
        self.assertIn('jobStatus: "/api/job-status"', self.html)
        self.assertIn("window.setInterval(loadData, POLL_MS)", self.html)
        self.assertIn("fetch(DATA_URL", self.html)
        self.assertIn('API_DATA_URL + "?include_jobs=false', self.html)

    def test_dashboard_has_required_filters(self):
        for element_id in [
            "searchInput",
            "actionFilter",
            "runFilter",
            "decisionFilter",
            "domainFilter",
            "flagFilter",
            "applyMethodFilter",
            "manualStatusFilter",
            "sortFilter",
            "boardViewButton",
            "listViewButton",
            "undoButton",
            "quickPresets",
            "themeToggle",
            "runScoutButton",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)

    def test_dashboard_has_application_shell_navigation(self):
        for page in [
            "home",
            "jobs",
            "scout",
            "profile",
            "strategy",
            "applications",
            "runs",
            "settings",
        ]:
            self.assertIn(f'data-app-page="{page}"', self.html)
            self.assertIn(f'data-page-id="{page}"', self.html)
        self.assertIn("navigateToPage", self.html)
        self.assertIn('localStorage.getItem("jobScoutCurrentPage")', self.html)
        self.assertIn('id="homeFocusTitle"', self.html)
        self.assertIn('id="homeStartScoutButton"', self.html)
        self.assertIn("renderHome", self.html)

    def test_dashboard_has_profile_and_cv_editor(self):
        for element_id in [
            "profileForm",
            "saveProfileButton",
            "profileReadinessRing",
            "profileReadinessList",
            "cvUploadInput",
            "uploadCvButton",
            "openCvPreview",
            "experienceRepeater",
            "educationRepeater",
            "languageRepeater",
            "profileSkills",
            "profileWorkAuthorization",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('profile: "/api/profile"', self.html)
        self.assertIn("loadProfileData", self.html)
        self.assertIn("saveProfile", self.html)
        self.assertIn("uploadCv", self.html)

    def test_dashboard_has_strategy_and_query_editor(self):
        for element_id in [
            "strategyForm",
            "saveStrategyButton",
            "strategyCoreGoal",
            "strategyPrimaryPaths",
            "strategyBridgeRoles",
            "strategyHardBlockers",
            "strategyLocations",
            "strategyPrimaryQueries",
            "strategyBridgeQueries",
            "strategyFallbackQueries",
            "strategyPrimaryQueryCount",
            "strategyBridgeQueryCount",
            "strategyFallbackQueryCount",
            "strategyQueryDuplicateNotice",
            "strategyQueryLearningEnabled",
            "strategyFreshMaxPages",
            "strategyFullText",
            "strategyPortfolioNotes",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('strategy: "/api/strategy"', self.html)
        self.assertIn("loadStrategyData", self.html)
        self.assertIn("saveStrategy", self.html)
        self.assertIn("One item per line. Commas and semicolons are preserved.", self.html)
        self.assertIn('from "./modules/list-editor.js"', self.html)

    def test_dashboard_has_strategy_based_scout_controls(self):
        for element_id in [
            "runSearchGoal",
            "runCustomSearchGroups",
            "runSearchPrimary",
            "runSearchBridge",
            "runSearchFallback",
            "runSearchGoalSummary",
            "searchGroupFilter",
            "freshSearchPathSummary",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("Career + Growth - Recommended", self.html)
        self.assertIn("Income Priority", self.html)
        self.assertIn("Search path", self.html)

    def test_dashboard_has_persistent_light_dark_theme_toggle(self):
        self.assertIn('localStorage.getItem("jobDashboardTheme")', self.html)
        self.assertIn('const THEME_STORAGE_KEY = "jobDashboardTheme"', self.html)
        self.assertIn('data-theme', self.html)
        self.assertIn('id="themeToggle"', self.html)
        self.assertIn('id="themeToggleText"', self.html)
        self.assertIn('id="icon-moon"', self.html)
        self.assertIn('id="icon-sun"', self.html)
        self.assertIn("applyTheme", self.html)
        self.assertIn("toggleTheme", self.html)
        self.assertIn("renderThemeToggle", self.html)

    def test_dashboard_has_manual_status_actions(self):
        self.assertIn("Applied", self.html)
        self.assertIn("Irrelevant", self.html)
        self.assertIn("Undo", self.html)
        self.assertIn("saveManualStatus", self.html)
        self.assertIn("showUndoToast", self.html)
        self.assertIn("manualUndoStack", self.html)
        self.assertIn("undoLastManualStatus", self.html)
        self.assertIn("updateUndoButtonState", self.html)
        self.assertIn("targetStatus === currentStatus ? \"unreviewed\" : targetStatus", self.html)
        self.assertIn("manual-applied", self.html)
        self.assertIn("manual-irrelevant", self.html)

    def test_dashboard_has_reusable_toast_and_mission_icons(self):
        self.assertIn("function showToast(", self.html)
        self.assertIn("function hideToast(", self.html)
        self.assertIn('id="icon-save"', self.html)
        self.assertIn('id="icon-trash"', self.html)
        self.assertNotIn("hideUndoToast", self.html)

    def test_run_scout_marks_beta_experimental_and_disabled_markets(self):
        self.assertIn('id="runExperimentalConfirm"', self.html)
        self.assertIn("Experimental market", self.html)
        self.assertNotIn("(Beta)", self.html)
        self.assertNotIn("(Unavailable)", self.html)
        self.assertIn("experimental_confirmed", self.html)

    def test_dashboard_has_global_manual_status_undo(self):
        self.assertIn('id="undoButton"', self.html)
        self.assertIn("pushManualUndo({ job, previousStatus, newStatus: status })", self.html)
        self.assertIn("trackUndo: false", self.html)
        self.assertIn('event.key.toLowerCase() !== "z"', self.html)

    def test_dashboard_has_run_badges_and_empty_run_labels(self):
        self.assertIn("run-badge", self.html)
        self.assertIn("shortRunLabel", self.html)
        self.assertIn("runFilterLabel", self.html)
        self.assertIn(" - empty", self.html)

    def test_dashboard_has_applying_workflow_tools(self):
        self.assertIn("Actionable jobs", self.html)
        self.assertIn("Actionable jobs are unreviewed Apply First and Good Options", self.html)
        self.assertIn('value="needs_action"', self.html)
        self.assertIn('actionScope: "needs_action"', self.html)
        self.assertIn('state.filters.actionScope = "needs_action"', self.html)
        self.assertIn("needsAction", self.html)
        self.assertIn("Open job", self.html)
        self.assertIn("Copy link", self.html)
        self.assertIn("copyJobLink", self.html)
        self.assertIn("Easy Apply", self.html)
        self.assertIn("applyMethodFilter", self.html)
        self.assertIn("applyMethodBadge", self.html)
        self.assertIn("applyMethod(job)", self.html)
        self.assertIn("Best Next Jobs", self.html)
        self.assertIn("bestNextJobs", self.html)
        self.assertIn("renderBestNextJobs", self.html)
        self.assertIn("QUICK_PRESETS", self.html)
        self.assertIn("applyQuickPreset", self.html)

    def test_dashboard_has_board_and_compact_list_layouts(self):
        self.assertIn('id="boardView"', self.html)
        self.assertIn('id="compactList"', self.html)
        self.assertIn("compact-job", self.html)
        self.assertIn("renderCompactList", self.html)
        self.assertIn("compactJobRow", self.html)
        self.assertIn("renderLayoutMode", self.html)
        self.assertIn("decision-chip", self.html)

    def test_dashboard_has_fresh_scout_progress_panel(self):
        for element_id in [
            "freshPanel",
            "freshTitle",
            "freshStatus",
            "freshCompleteSummary",
            "freshApply",
            "freshGood",
            "freshJobs",
            "freshKnownSkipped",
            "freshQuery",
            "freshPages",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("renderFreshProgress", self.html)
        self.assertIn("renderFreshCompleteSummary", self.html)
        self.assertIn("Filter to this run", self.html)
        self.assertIn("Show details", self.html)
        self.assertIn("selectedFreshRun", self.html)
        self.assertIn("freshPageCard", self.html)
        self.assertIn("Run History", self.html)
        self.assertIn("renderRunHistory", self.html)

    def test_dashboard_has_run_scout_overlay(self):
        for element_id in [
            "runScoutOverlay",
            "runWorkflow",
            "runLocation",
            "runQuery",
            "runMaxPages",
            "runAiBudgetMode",
            "runBrowser",
            "runHumanMode",
            "runFreshMode",
            "runResumeMode",
            "startRunButton",
            "runLogTail",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('runControl: "/api/run-control"', self.html)
        self.assertIn("startDashboardRun", self.html)
        self.assertIn("stopDashboardRun", self.html)
        self.assertIn("Smart Guard", self.html)
        self.assertIn("Deep Search", self.html)
        self.assertIn("ai_budget_mode", self.html)
        self.assertIn("trapRunScoutFocus", self.html)
        self.assertIn("modal.scrollTop = 0", self.html)
        self.assertIn('aria-label="Close run scout dialog"', self.html)

    def test_dashboard_has_safe_legacy_tools(self):
        for element_id in [
            "advancedToolsTitle",
            "legacyApplicationCount",
            "legacyTodayCount",
            "legacyReviewCount",
            "legacySeenCount",
            "validateBoardsButton",
            "refreshLegacyStatsButton",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('legacyTools: "/api/legacy-tools"', self.html)
        self.assertIn('value="validate_boards"', self.html)
        self.assertIn("It cannot apply to jobs or submit an application.", self.html)
        self.assertIn("openValidationWorkflow", self.html)

    def test_dashboard_has_accessible_mobile_navigation_sheet(self):
        for element_id in [
            "appSidebar",
            "mobileNavBackdrop",
            "mobileNavToggle",
            "mobileWorkspaceTitle",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('aria-controls="appSidebar"', self.html)
        self.assertIn("openMobileNavigation", self.html)
        self.assertIn("closeMobileNavigation", self.html)
        self.assertIn("trapMobileNavigationFocus", self.html)
        self.assertIn('event.key === "Escape"', self.html)
        self.assertIn('currentHeading.setAttribute("tabindex", "-1")', self.html)

    def test_applications_render_in_scalable_batches(self):
        for element_id in [
            "applicationsVisibleCount",
            "loadMoreApplicationsButton",
            "applicationsTableFooter",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("loadApplications({ append: true })", self.html)
        self.assertIn('limit: "50"', self.html)
        self.assertIn("payload.has_more", self.html)

    def test_jobs_load_from_paginated_api(self):
        for element_id in [
            "jobsVisibleCount",
            "loadMoreJobsButton",
            "jobsTableFooter",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('jobs: "/api/jobs"', self.html)
        self.assertIn('limit: "100"', self.html)
        self.assertIn("loadJobs({ append: true })", self.html)
        self.assertIn("include_jobs=false", self.html)
        self.assertIn("compact: true", self.html)
        self.assertIn("if (!data.summary.by_manual_status || jobs.length)", self.html)

    def test_hidden_workspaces_load_on_demand(self):
        startup = self.html.split("bindControls();", 1)[1]
        startup = startup.split("window.setInterval", 1)[0]
        self.assertNotIn("loadStrategyData();", startup)
        self.assertNotIn("loadAiSettings();", startup)
        self.assertNotIn("loadBoardSettings();", startup)
        self.assertNotIn("loadAssistant();", startup)
        self.assertNotIn("loadMaintenance();", startup)

    def test_dashboard_has_required_decision_columns(self):
        for decision in ["APPLY_FIRST", "GOOD_OPTIONS", "LOW_PROBABILITY", "REJECTED"]:
            self.assertIn(f'data-column="{decision}"', self.html)

    def test_dashboard_uses_one_stable_file_name(self):
        self.assertNotIn("recommended_jobs_dashboard_2026", self.html)

    def test_runs_page_reports_persistence_health_separately(self):
        self.assertIn('id="diagnosticPersistence"', self.html)
        self.assertIn('id="latestPersistenceWarning"', self.html)
        self.assertIn("Recovered persistence warning", self.html)

    def test_dashboard_has_interrupted_run_lifecycle_ui(self):
        self.assertIn('id="latestRunIncident"', self.html)
        self.assertIn("A previous run was interrupted and can be resumed", self.html)
        self.assertIn("Interrupted Fresh Scout Run", self.html)
        self.assertIn("Resume last run", self.html)
        self.assertIn("effectiveActiveRunId", self.html)
        self.assertIn(".decision-chip.INTERRUPTED", self.html)

    def test_dashboard_uses_external_feature_modules(self):
        self.assertRegex(
            self.document,
            r'href="dashboard/styles\.css\?v=[^"]+"',
        )
        self.assertRegex(
            self.document,
            r'type="module" src="dashboard/app\.js\?v=[^"]+"',
        )
        for module_name in [
            "navigation.js",
            "jobs.js",
            "scout.js",
            "profile.js",
            "applications.js",
            "settings.js",
            "maintenance.js",
            "list-editor.js",
        ]:
            self.assertTrue((ROOT / "dashboard" / "modules" / module_name).exists())
        self.assertNotIn("<style>", self.document)


if __name__ == "__main__":
    unittest.main()
