import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from agent_run_diff_lab.cli import EXIT_GATE_FAILED, EXIT_PASS, main
from agent_run_diff_lab.config import DiffConfig, load_config
from agent_run_diff_lab.diff import compare_runs
from agent_run_diff_lab.errors import ConfigError, ParseError
from agent_run_diff_lab.models import FileChange, RunRecord, ToolCall
from agent_run_diff_lab.parser import parse_run_file, parse_run_text
from agent_run_diff_lab.reporters import render_json, render_junit, render_markdown


class ParserBasicTests(unittest.TestCase):
    def test_parse_json_object_events(self):
        run = parse_run_text('{"run_id":"r1","events":[{"type":"tool_call","name":"read","status":"ok"}]}')
        self.assertEqual(run.run_id, "r1")
        self.assertEqual(run.tool_calls[0].name, "read")

    def test_parse_jsonl_events(self):
        run = parse_run_text('{"type":"tool_call","name":"read","status":"ok"}\n{"type":"file_change","path":"a.py","added":1}')
        self.assertEqual(len(run.tool_calls), 1)
        self.assertEqual(run.file_changes[0].path, "a.py")

    def test_empty_transcript_errors(self):
        with self.assertRaises(ParseError):
            parse_run_text("")

    def test_invalid_jsonl_errors(self):
        with self.assertRaises(ParseError):
            parse_run_text('{"ok": true}\n{bad')

    def test_root_array_supported(self):
        run = parse_run_text('[{"type":"tool_call","name":"x"}]')
        self.assertEqual(run.tool_calls[0].name, "x")

    def test_tool_result_attaches_output(self):
        run = parse_run_text(
            '{"events":[{"type":"tool_call","id":"1","name":"x"},{"type":"tool_result","call_id":"1","output":"done"}]}'
        )
        self.assertEqual(run.tool_calls[0].output, "done")

    def test_file_diff_line_counts(self):
        run = parse_run_text('{"events":[{"type":"file_change","path":"a","diff":"--- a\\n+++ b\\n-old\\n+new"}]}')
        self.assertEqual(run.file_changes[0].added, 1)
        self.assertEqual(run.file_changes[0].removed, 1)

    def test_parse_file_sets_run_id_from_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.json"
            path.write_text('{"events":[]}', encoding="utf-8")
            self.assertEqual(parse_run_file(str(path)).run_id, "sample")


class DiffBasicTests(unittest.TestCase):
    def test_identical_runs_pass(self):
        run = RunRecord(tool_calls=[ToolCall(0, "read")], duration_ms=1, cost_usd=1)
        result = compare_runs(run, run, DiffConfig())
        self.assertTrue(result.passed)
        self.assertEqual(result.risk_score, 0)

    def test_added_tool_detected(self):
        base = RunRecord(tool_calls=[ToolCall(0, "read")])
        cand = RunRecord(tool_calls=[ToolCall(0, "read"), ToolCall(1, "write")])
        result = compare_runs(base, cand, DiffConfig(max_risk_score=99))
        self.assertEqual(result.tool_diffs[0].change_type, "added")

    def test_replaced_tool_detected(self):
        base = RunRecord(tool_calls=[ToolCall(0, "read")])
        cand = RunRecord(tool_calls=[ToolCall(0, "write")])
        result = compare_runs(base, cand, DiffConfig(max_risk_score=99))
        self.assertEqual(result.tool_diffs[0].change_type, "reordered_or_replaced")

    def test_input_change_detected(self):
        base = RunRecord(tool_calls=[ToolCall(0, "read", input={"path": "a"})])
        cand = RunRecord(tool_calls=[ToolCall(0, "read", input={"path": "b"})])
        result = compare_runs(base, cand, DiffConfig(max_risk_score=99))
        self.assertIn("input_changed", result.tool_diffs[0].details)

    def test_output_compare_can_be_disabled(self):
        base = RunRecord(tool_calls=[ToolCall(0, "read", output="a")])
        cand = RunRecord(tool_calls=[ToolCall(0, "read", output="b")])
        result = compare_runs(base, cand, DiffConfig(compare_outputs=False))
        self.assertEqual(result.tool_diffs, [])

    def test_file_added_detected(self):
        result = compare_runs(RunRecord(), RunRecord(file_changes=[FileChange("a.py")]), DiffConfig(max_risk_score=99))
        self.assertEqual(result.file_diffs[0].change_type, "added")

    def test_failure_delta_violation(self):
        base = RunRecord(tool_calls=[ToolCall(0, "x", status="ok")])
        cand = RunRecord(tool_calls=[ToolCall(0, "x", status="failed")])
        result = compare_runs(base, cand, DiffConfig(max_risk_score=99))
        self.assertFalse(result.passed)
        self.assertTrue(any("failure delta" in item for item in result.violations))

    def test_duration_threshold_violation(self):
        result = compare_runs(RunRecord(duration_ms=100), RunRecord(duration_ms=200), DiffConfig(max_duration_delta_pct=10, max_risk_score=99))
        self.assertFalse(result.passed)

    def test_cost_threshold_violation(self):
        result = compare_runs(RunRecord(cost_usd=1), RunRecord(cost_usd=2), DiffConfig(max_cost_delta_pct=10, max_risk_score=99))
        self.assertFalse(result.passed)

    def test_ignore_tool(self):
        base = RunRecord()
        cand = RunRecord(tool_calls=[ToolCall(0, "noise")])
        result = compare_runs(base, cand, DiffConfig(ignored_tools=["noise"]))
        self.assertTrue(result.passed)


class ReportAndCliBasicTests(unittest.TestCase):
    def test_json_report_is_parseable(self):
        result = compare_runs(RunRecord(), RunRecord(), DiffConfig())
        self.assertIn("passed", json.loads(render_json(result)))

    def test_markdown_report_contains_summary(self):
        result = compare_runs(RunRecord(), RunRecord(), DiffConfig())
        self.assertIn("## Summary", render_markdown(result))

    def test_junit_report_is_xml(self):
        result = compare_runs(RunRecord(), RunRecord(), DiffConfig())
        self.assertIn("<testsuite", render_junit(result))

    def test_config_unknown_key_errors(self):
        with self.assertRaises(ConfigError):
            DiffConfig.from_dict({"bad": 1})

    def test_load_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text('{"max_risk_score": 1}', encoding="utf-8")
            self.assertEqual(load_config(str(path)).max_risk_score, 1)

    def test_cli_pass_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            cand = Path(tmp) / "c.json"
            base.write_text('{"events":[]}', encoding="utf-8")
            cand.write_text('{"events":[]}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(base), str(cand), "--format", "json", "--quiet"]), EXIT_PASS)

    def test_cli_gate_failed_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            cand = Path(tmp) / "c.json"
            base.write_text('{"duration_ms": 1, "events":[]}', encoding="utf-8")
            cand.write_text('{"duration_ms": 10, "events":[]}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(base), str(cand), "--max-duration-delta-pct", "1", "--quiet"]), EXIT_GATE_FAILED)


if __name__ == "__main__":
    unittest.main()
