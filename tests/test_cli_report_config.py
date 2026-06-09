import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from agent_run_diff_lab.cli import EXIT_PASS, EXIT_USAGE_ERROR, build_parser, main
from agent_run_diff_lab.config import DiffConfig, apply_list_overrides, load_config
from agent_run_diff_lab.errors import ConfigError
from agent_run_diff_lab.models import FileChange, RunRecord, ToolCall
from agent_run_diff_lab.reporters import render_junit, render_markdown, render_pr_comment, render_sarif


class ConfigTests(unittest.TestCase):
    def test_negative_threshold_errors(self):
        with self.assertRaises(ConfigError):
            DiffConfig(max_risk_score=-1).validate()

    def test_ignored_tools_must_be_list(self):
        with self.assertRaises(ConfigError):
            DiffConfig.from_dict({"ignored_tools": "x"})

    def test_bool_fields_must_be_bool(self):
        with self.assertRaises(ConfigError):
            DiffConfig.from_dict({"compare_outputs": "yes"})

    def test_invalid_json_config_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(str(path))

    def test_overrides_win_over_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text('{"max_risk_score": 1}', encoding="utf-8")
            self.assertEqual(load_config(str(path), {"max_risk_score": 2}).max_risk_score, 2)

    def test_list_overrides_extend(self):
        config = apply_list_overrides(DiffConfig(ignored_tools=["a"]), ["a", "b"], ["x"])
        self.assertEqual(config.ignored_tools, ["a", "b"])
        self.assertEqual(config.ignored_paths, ["x"])


class ReporterTests(unittest.TestCase):
    def test_markdown_lists_file_diff(self):
        from agent_run_diff_lab.diff import compare_runs

        result = compare_runs(RunRecord(), RunRecord(file_changes=[FileChange("x.py")]), DiffConfig(max_risk_score=99))
        self.assertIn("x.py", render_markdown(result))

    def test_markdown_lists_tool_diff(self):
        from agent_run_diff_lab.diff import compare_runs

        result = compare_runs(RunRecord(), RunRecord(tool_calls=[ToolCall(0, "x")]), DiffConfig(max_risk_score=99))
        self.assertIn("Tool Diffs", render_markdown(result))

    def test_junit_contains_violation_failure(self):
        from agent_run_diff_lab.diff import compare_runs

        result = compare_runs(RunRecord(duration_ms=1), RunRecord(duration_ms=10), DiffConfig(max_duration_delta_pct=1))
        self.assertIn("<failure", render_junit(result))

    def test_sarif_contains_gate_violation(self):
        from agent_run_diff_lab.diff import compare_runs

        result = compare_runs(RunRecord(duration_ms=1), RunRecord(duration_ms=10), DiffConfig(max_duration_delta_pct=1))
        payload = json.loads(render_sarif(result))
        rule_ids = [item["ruleId"] for item in payload["runs"][0]["results"]]
        self.assertIn("gate-violation", rule_ids)

    def test_pr_comment_lists_violation(self):
        from agent_run_diff_lab.diff import compare_runs

        result = compare_runs(RunRecord(duration_ms=1), RunRecord(duration_ms=10), DiffConfig(max_duration_delta_pct=1))
        rendered = render_pr_comment(result)
        self.assertIn("Gate Violations", rendered)
        self.assertIn("duration delta", rendered)


class CliTests(unittest.TestCase):
    def test_parser_accepts_format(self):
        args = build_parser().parse_args(["b", "c", "--format", "junit"])
        self.assertEqual(args.format, "junit")

    def test_parser_accepts_ci_native_formats(self):
        self.assertEqual(build_parser().parse_args(["b", "c", "--format", "sarif"]).format, "sarif")
        self.assertEqual(build_parser().parse_args(["b", "c", "--format", "pr-comment"]).format, "pr-comment")

    def test_cli_writes_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            cand = Path(tmp) / "c.json"
            out = Path(tmp) / "report.json"
            base.write_text('{"events":[]}', encoding="utf-8")
            cand.write_text('{"events":[]}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([str(base), str(cand), "--format", "json", "--output", str(out), "--quiet"])
            self.assertEqual(code, EXIT_PASS)
            self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["passed"])

    def test_cli_writes_sarif_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            cand = Path(tmp) / "c.json"
            out = Path(tmp) / "report.sarif"
            base.write_text('{"events":[]}', encoding="utf-8")
            cand.write_text('{"events":[{"type":"file_change","path":"src/app.py","added":1}]}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([str(base), str(cand), "--format", "sarif", "--output", str(out), "--max-risk-score", "99", "--quiet"])
            self.assertEqual(code, EXIT_PASS)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["version"], "2.1.0")

    def test_cli_writes_pr_comment_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            cand = Path(tmp) / "c.json"
            out = Path(tmp) / "comment.md"
            base.write_text('{"duration_ms": 1, "events":[]}', encoding="utf-8")
            cand.write_text('{"duration_ms": 10, "events":[]}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([str(base), str(cand), "--format", "pr-comment", "--output", str(out), "--max-duration-delta-pct", "1", "--quiet"])
            self.assertNotEqual(code, EXIT_PASS)
            self.assertIn("agent-run-diff-lab:pr-comment", out.read_text(encoding="utf-8"))

    def test_cli_usage_error_for_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            cand = Path(tmp) / "c.json"
            base.write_text("{bad", encoding="utf-8")
            cand.write_text('{"events":[]}', encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(base), str(cand), "--quiet"]), EXIT_USAGE_ERROR)


if __name__ == "__main__":
    unittest.main()
