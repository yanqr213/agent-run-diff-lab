import unittest

from agent_run_diff_lab.config import DiffConfig
from agent_run_diff_lab.diff import compare_runs
from agent_run_diff_lab.models import FileChange, RunRecord, ToolCall


class DiffBehaviorTests(unittest.TestCase):
    def test_removed_tool_detected(self):
        result = compare_runs(RunRecord(tool_calls=[ToolCall(0, "x")]), RunRecord(), DiffConfig(max_risk_score=99))
        self.assertEqual(result.tool_diffs[0].change_type, "removed")

    def test_status_change_detected(self):
        result = compare_runs(
            RunRecord(tool_calls=[ToolCall(0, "x", status="ok")]),
            RunRecord(tool_calls=[ToolCall(0, "x", status="failed")]),
            DiffConfig(max_risk_score=99),
        )
        self.assertIn("status_changed", result.tool_diffs[0].details)

    def test_error_change_detected(self):
        result = compare_runs(
            RunRecord(tool_calls=[ToolCall(0, "x")]),
            RunRecord(tool_calls=[ToolCall(0, "x", error="boom")]),
            DiffConfig(max_risk_score=99),
        )
        self.assertIn("error_changed", result.tool_diffs[0].details)

    def test_retry_change_detected(self):
        result = compare_runs(
            RunRecord(tool_calls=[ToolCall(0, "x")]),
            RunRecord(tool_calls=[ToolCall(0, "x", retry_of="1")]),
            DiffConfig(max_risk_score=99),
        )
        self.assertIn("retry_changed", result.tool_diffs[0].details)

    def test_retry_count_from_duplicate_inputs(self):
        cand = RunRecord(tool_calls=[ToolCall(0, "x", input=1), ToolCall(1, "x", input=1)])
        result = compare_runs(RunRecord(), cand, DiffConfig(max_retries_delta=0, max_risk_score=99))
        self.assertEqual(result.metrics["candidate_retries"], 1)

    def test_allow_tool_reorder_downgrades_pure_reorder(self):
        base = RunRecord(tool_calls=[ToolCall(0, "a"), ToolCall(1, "b")])
        cand = RunRecord(tool_calls=[ToolCall(0, "b"), ToolCall(1, "a")])
        result = compare_runs(base, cand, DiffConfig(allow_tool_reorder=True))
        self.assertEqual(result.tool_diffs, [])

    def test_disallow_tool_reorder_reports(self):
        base = RunRecord(tool_calls=[ToolCall(0, "a"), ToolCall(1, "b")])
        cand = RunRecord(tool_calls=[ToolCall(0, "b"), ToolCall(1, "a")])
        result = compare_runs(base, cand, DiffConfig(max_risk_score=99))
        self.assertEqual(len(result.tool_diffs), 2)

    def test_ignore_path(self):
        cand = RunRecord(file_changes=[FileChange("generated/a.txt")])
        result = compare_runs(RunRecord(), cand, DiffConfig(ignored_paths=["generated/*"]))
        self.assertTrue(result.passed)

    def test_file_removed_detected(self):
        result = compare_runs(RunRecord(file_changes=[FileChange("x")]), RunRecord(), DiffConfig(max_risk_score=99))
        self.assertEqual(result.file_diffs[0].change_type, "removed")

    def test_file_changed_detected(self):
        result = compare_runs(
            RunRecord(file_changes=[FileChange("x", added=1)]),
            RunRecord(file_changes=[FileChange("x", added=2)]),
            DiffConfig(max_risk_score=99),
        )
        self.assertEqual(result.file_diffs[0].change_type, "changed")

    def test_sensitive_path_increases_risk(self):
        result = compare_runs(RunRecord(), RunRecord(file_changes=[FileChange(".env")]), DiffConfig(max_risk_score=99))
        self.assertGreaterEqual(result.risk_score, 12)

    def test_large_file_delta_increases_risk(self):
        result = compare_runs(RunRecord(), RunRecord(file_changes=[FileChange("x", added=201)]), DiffConfig(max_risk_score=99))
        self.assertTrue(any("large file delta" in reason for reason in result.risk_reasons))

    def test_file_provided_risk_included(self):
        result = compare_runs(RunRecord(), RunRecord(file_changes=[FileChange("x", risk=7)]), DiffConfig(max_risk_score=99))
        self.assertTrue(any("(+7)" in reason for reason in result.risk_reasons))

    def test_risky_shell_input_increases_risk(self):
        result = compare_runs(
            RunRecord(),
            RunRecord(tool_calls=[ToolCall(0, "shell", input={"command": "rm -rf /tmp/x"})]),
            DiffConfig(max_risk_score=99),
        )
        self.assertTrue(any("rm -rf" in reason for reason in result.risk_reasons))

    def test_new_failed_tool_violation_can_be_allowed(self):
        result = compare_runs(
            RunRecord(),
            RunRecord(tool_calls=[ToolCall(0, "x", status="failed")]),
            DiffConfig(allow_new_failed_tools=True, max_failures_delta=10, max_risk_score=99),
        )
        self.assertTrue(all("new failed tool" not in violation for violation in result.violations))

    def test_file_change_delta_violation(self):
        result = compare_runs(
            RunRecord(file_changes=[]),
            RunRecord(file_changes=[FileChange("a"), FileChange("b")]),
            DiffConfig(max_file_changes_delta=1, max_risk_score=99),
        )
        self.assertTrue(any("file change delta" in violation for violation in result.violations))

    def test_zero_baseline_cost_delta_pct(self):
        result = compare_runs(RunRecord(cost_usd=0), RunRecord(cost_usd=2), DiffConfig(max_cost_delta_pct=99, max_risk_score=99))
        self.assertEqual(result.metrics["cost_delta_pct"], 100.0)

    def test_zero_to_zero_duration_pct(self):
        result = compare_runs(RunRecord(duration_ms=0), RunRecord(duration_ms=0), DiffConfig())
        self.assertEqual(result.metrics["duration_delta_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()

