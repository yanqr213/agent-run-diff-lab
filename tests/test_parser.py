import unittest

from agent_run_diff_lab.errors import ParseError
from agent_run_diff_lab.parser import parse_run_text


class ParserShapeTests(unittest.TestCase):
    def test_steps_container_supported(self):
        run = parse_run_text('{"steps":[{"type":"tool","tool":"search","input":"q"}]}')
        self.assertEqual(run.tool_calls[0].name, "search")

    def test_messages_container_supported(self):
        run = parse_run_text('{"messages":[{"type":"function_call","function":"lookup","arguments":{"x":1}}]}')
        self.assertEqual(run.tool_calls[0].input, {"x": 1})

    def test_transcript_container_supported(self):
        run = parse_run_text('{"transcript":[{"type":"command","command":"python","args":["-V"]}]}')
        self.assertEqual(run.tool_calls[0].name, "python")

    def test_root_tool_calls_not_duplicated(self):
        run = parse_run_text('{"tool_calls":[{"name":"x","input":1}]}')
        self.assertEqual(len(run.tool_calls), 1)

    def test_extra_root_tool_calls_collected_with_events(self):
        run = parse_run_text('{"events":[],"tool_calls":[{"name":"x","input":1}]}')
        self.assertEqual(run.tool_calls[0].name, "x")

    def test_tool_alias_tool(self):
        run = parse_run_text('{"events":[{"tool":"shell","input":{"command":"pwd"}}]}')
        self.assertEqual(run.tool_calls[0].name, "shell")

    def test_tool_alias_function(self):
        run = parse_run_text('{"events":[{"function":"read_file","arguments":{"path":"a"}}]}')
        self.assertEqual(run.tool_calls[0].name, "read_file")

    def test_tool_alias_command(self):
        run = parse_run_text('{"events":[{"command":"ls","args":["-la"]}]}')
        self.assertEqual(run.tool_calls[0].name, "ls")

    def test_output_alias_stdout(self):
        run = parse_run_text('{"events":[{"tool":"shell","input":"x","stdout":"ok"}]}')
        self.assertEqual(run.tool_calls[0].output, "ok")

    def test_status_defaults_to_failed_on_stderr(self):
        run = parse_run_text('{"events":[{"tool":"shell","input":"x","stderr":"bad"}]}')
        self.assertEqual(run.tool_calls[0].status, "failed")

    def test_duration_total_derived_from_tools(self):
        run = parse_run_text('{"events":[{"tool":"a","input":1,"duration_ms":2},{"tool":"b","input":2,"duration_ms":3}]}')
        self.assertEqual(run.duration_ms, 5)

    def test_cost_total_derived_from_tools(self):
        run = parse_run_text('{"events":[{"tool":"a","input":1,"cost_usd":0.2},{"tool":"b","input":2,"cost_usd":0.3}]}')
        self.assertAlmostEqual(run.cost_usd, 0.5)

    def test_file_aliases_supported(self):
        run = parse_run_text('{"events":[{"type":"file","filename":"x.py","additions":2,"deletions":1}]}')
        self.assertEqual(run.file_changes[0].path, "x.py")
        self.assertEqual(run.file_changes[0].added, 2)

    def test_file_changes_root_supported(self):
        run = parse_run_text('{"file_changes":[{"path":"x.py","added":1}]}')
        self.assertEqual(run.file_changes[0].path, "x.py")

    def test_files_root_supported(self):
        run = parse_run_text('{"files":[{"path":"x.py","added":1}]}')
        self.assertEqual(run.file_changes[0].path, "x.py")

    def test_file_changes_merge_by_path(self):
        run = parse_run_text('{"events":[{"type":"file_change","path":"x","added":1},{"type":"file_change","path":"x","removed":2}]}')
        self.assertEqual(run.file_changes[0].added, 1)
        self.assertEqual(run.file_changes[0].removed, 2)

    def test_non_object_root_errors(self):
        with self.assertRaises(ParseError):
            parse_run_text('"hello"')

    def test_non_object_event_errors(self):
        with self.assertRaises(ParseError):
            parse_run_text('{"events":[1]}')


if __name__ == "__main__":
    unittest.main()

