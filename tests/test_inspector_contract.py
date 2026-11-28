import unittest
from pathlib import Path


class InspectorContractTests(unittest.TestCase):
    def test_apps_script_waits_for_dispatch_ack_even_when_old_completion_exists(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('else if (awaitingGitHub)', code)
        self.assertNotIn('!full.lastCompletedAt && awaitingGitHub', code)
        self.assertNotIn('!priority.lastCompletedAt && awaitingGitHub', code)

    def test_completion_cooldown_is_five_minutes(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('POST_COMPLETION_COOLDOWN_MINUTES: 5', code)
        self.assertIn('everyMinutes(5)', code)

    def test_dispatch_marker_is_cleared_only_after_newer_completed_job(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('completedMs >= dispatchAt', code)
        self.assertIn('props.deleteProperty(dispatchKey)', code)

    def test_github_watchdog_is_not_a_second_dispatcher(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        self.assertNotIn("createWorkflowDispatch", workflow)
        self.assertNotIn("cancelWorkflowRun", workflow)
        self.assertIn("actions: read", workflow)

    def test_apps_script_is_version_14(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('version: "14.0"', code)
        self.assertIn("V14.0", code)

    def test_sheets_write_has_retry_repair_logic(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn("Repair-safe two-table write", code)
        self.assertIn("repaired_memory_only", code)
        self.assertIn("repaired_result_only", code)


if __name__ == "__main__":
    unittest.main()
