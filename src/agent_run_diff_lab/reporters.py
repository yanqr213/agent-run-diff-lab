"""Markdown, JSON, and JUnit report renderers."""

import json
from typing import Iterable
from xml.etree.ElementTree import Element, SubElement, tostring

from .models import DiffResult


def render_json(result: DiffResult, pretty: bool = True) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2 if pretty else None, sort_keys=True)


def render_markdown(result: DiffResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"# Agent Run Diff Report: {status}",
        "",
        "## Summary",
        "",
        f"- Risk score: `{result.risk_score}`",
        f"- Violations: `{len(result.violations)}`",
        f"- Tool diffs: `{len(result.tool_diffs)}`",
        f"- File diffs: `{len(result.file_diffs)}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in result.metrics.items():
        lines.append(f"| `{key}` | `{value}` |")

    lines.extend(["", "## Violations", ""])
    lines.extend(_bullet_or_empty(result.violations))

    lines.extend(["", "## Risk Reasons", ""])
    lines.extend(_bullet_or_empty(result.risk_reasons))

    lines.extend(["", "## Tool Diffs", ""])
    if result.tool_diffs:
        lines.extend(["| Index | Change | Baseline | Candidate | Details |", "| ---: | --- | --- | --- | --- |"])
        for diff in result.tool_diffs:
            details = json.dumps(diff.details, ensure_ascii=False, sort_keys=True)
            lines.append(
                f"| {diff.index} | `{diff.change_type}` | `{diff.baseline_name or ''}` | "
                f"`{diff.candidate_name or ''}` | `{_escape_table(details)}` |"
            )
    else:
        lines.append("_No tool diffs._")

    lines.extend(["", "## File Diffs", ""])
    if result.file_diffs:
        lines.extend(["| Path | Change | Baseline +/- | Candidate +/- |", "| --- | --- | ---: | ---: |"])
        for diff in result.file_diffs:
            base = _change_size(diff.baseline)
            cand = _change_size(diff.candidate)
            lines.append(f"| `{_escape_table(diff.path)}` | `{diff.change_type}` | `{base}` | `{cand}` |")
    else:
        lines.append("_No file diffs._")

    return "\n".join(lines) + "\n"


def render_junit(result: DiffResult, suite_name: str = "agent-run-diff-lab") -> str:
    tests = 1 + len(result.violations)
    failures = len(result.violations)
    suite = Element("testsuite", name=suite_name, tests=str(tests), failures=str(failures), errors="0")
    case = SubElement(suite, "testcase", classname=suite_name, name="risk-threshold")
    if result.risk_score and not result.passed:
        failure = SubElement(case, "failure", message=f"risk score {result.risk_score}")
        failure.text = "\n".join(result.risk_reasons)
    for violation in result.violations:
        vcase = SubElement(suite, "testcase", classname=suite_name, name=_safe_case_name(violation))
        failure = SubElement(vcase, "failure", message=violation)
        failure.text = violation
    return '<?xml version="1.0" encoding="utf-8"?>\n' + tostring(suite, encoding="unicode")


def _bullet_or_empty(items: Iterable[str]):
    items = list(items)
    if not items:
        return ["_None._"]
    return [f"- {item}" for item in items]


def _change_size(change) -> str:
    if change is None:
        return ""
    return f"+{change.added}/-{change.removed}"


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "\\n")


def _safe_case_name(text: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in text)[:120]

