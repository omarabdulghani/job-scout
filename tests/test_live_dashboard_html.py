import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiveDashboardHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html_path = ROOT / "recommended_jobs_dashboard.html"
        cls.html = cls.html_path.read_text(encoding="utf-8")

    def test_dashboard_file_exists(self):
        self.assertTrue(self.html_path.exists())

    def test_dashboard_polls_stable_json_file(self):
        self.assertIn('const DATA_URL = "recommended_jobs_dashboard_data.json"', self.html)
        self.assertIn('const API_DATA_URL = "/api/dashboard-data"', self.html)
        self.assertIn('const API_STATUS_URL = "/api/job-status"', self.html)
        self.assertIn("window.setInterval(loadData, POLL_MS)", self.html)
        self.assertIn("fetch(DATA_URL", self.html)
        self.assertIn("fetch(API_DATA_URL", self.html)

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
            "runScoutButton",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)

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
            "runBrowser",
            "runHumanMode",
            "runFreshMode",
            "runResumeMode",
            "startRunButton",
            "runLogTail",
        ]:
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('const API_RUN_CONTROL_URL = "/api/run-control"', self.html)
        self.assertIn("startDashboardRun", self.html)
        self.assertIn("stopDashboardRun", self.html)

    def test_dashboard_has_required_decision_columns(self):
        for decision in ["APPLY_FIRST", "GOOD_OPTIONS", "LOW_PROBABILITY", "REJECTED"]:
            self.assertIn(f'data-column="{decision}"', self.html)

    def test_dashboard_uses_one_stable_file_name(self):
        self.assertNotIn("recommended_jobs_dashboard_2026", self.html)


if __name__ == "__main__":
    unittest.main()
