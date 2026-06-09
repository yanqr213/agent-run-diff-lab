"""Markdown, JSON, SARIF, PR comment, and JUnit report renderers."""

import json
from typing import Iterable
from xml.etree.ElementTree import Element, SubElement, tostring

from .models import DiffResult

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


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


def render_pr_comment(result: DiffResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        "<!-- agent-run-diff-lab:pr-comment:v1 -->",
        f"## Agent Run Diff: {status}",
        "",
        (
            f"Risk score **{result.risk_score}** with **{len(result.violations)}** gate violation(s), "
            f"**{len(result.tool_diffs)}** tool diff(s), and **{len(result.file_diffs)}** file diff(s)."
        ),
        "",
    ]
    if result.violations:
        lines.extend(["### Gate Violations", ""])
        for violation in result.violations[:10]:
            lines.append(f"- {violation}")
        if len(result.violations) > 10:
            lines.append(f"- ... and {len(result.violations) - 10} more violation(s).")
        lines.append("")
    if result.risk_reasons:
        lines.extend(["### Top Risk Reasons", ""])
        for reason in result.risk_reasons[:10]:
            lines.append(f"- {reason}")
        if len(result.risk_reasons) > 10:
            lines.append(f"- ... and {len(result.risk_reasons) - 10} more risk reason(s).")
        lines.append("")
    lines.extend(
        [
            "### Suggested Next Step",
            "",
            "- Review new failures, risky tool inputs, and sensitive file diffs before approving the candidate run.",
            "- If this change is intentional, update the configured thresholds or ignored tools/paths with a short rationale.",
            "",
            "<details>",
            "<summary>Machine-readable summary</summary>",
            "",
            "```json",
            json.dumps(
                {
                    "passed": result.passed,
                    "risk_score": result.risk_score,
                    "violations": result.violations,
                    "metrics": result.metrics,
                    "tool_diffs": len(result.tool_diffs),
                    "file_diffs": len(result.file_diffs),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)


def render_sarif(result: DiffResult) -> str:
    sarif_results = []
    for index, violation in enumerate(result.violations):
        sarif_results.append(
            {
                "ruleId": "gate-violation",
                "level": "error",
                "message": {"text": violation},
                "locations": [_artifact_location("agent-run-diff-lab", 1)],
                "partialFingerprints": {"agentRunDiff": f"violation-{index}-{violation}"},
            }
        )
    for index, reason in enumerate(result.risk_reasons):
        sarif_results.append(
            {
                "ruleId": "risk-reason",
                "level": "warning",
                "message": {"text": reason},
                "locations": [_artifact_location("agent-run-diff-lab", 1)],
                "partialFingerprints": {"agentRunDiff": f"risk-{index}-{reason}"},
            }
        )
    for diff in result.file_diffs:
        sarif_results.append(
            {
                "ruleId": "file-diff",
                "level": "warning",
                "message": {"text": f"Candidate run has {diff.change_type} file diff: {diff.path}"},
                "locations": [_artifact_location(diff.path, 1)],
                "partialFingerprints": {"agentRunDiff": f"file-{diff.change_type}-{diff.path}"},
            }
        )
    payload = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agent-run-diff-lab",
                        "informationUri": "https://github.com/yanqr213/agent-run-diff-lab",
                        "rules": [
                            _sarif_rule("gate-violation", "Agent run diff gate violation", "A configured run-diff threshold was exceeded."),
                            _sarif_rule("risk-reason", "Agent run diff risk reason", "A risk scoring rule contributed to the candidate run score."),
                            _sarif_rule("file-diff", "Agent run file diff", "The candidate run touched a file differently from the baseline."),
                        ],
                    }
                },
                "invocations": [{"executionSuccessful": result.passed}],
                "properties": {
                    "risk_score": result.risk_score,
                    "passed": result.passed,
                    "metrics": result.metrics,
                    "tool_diffs": len(result.tool_diffs),
                    "file_diffs": len(result.file_diffs),
                },
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sarif_rule(rule_id: str, name: str, text: str) -> dict:
    return {
        "id": rule_id,
        "name": name,
        "shortDescription": {"text": name},
        "fullDescription": {"text": text},
        "help": {"text": text},
        "defaultConfiguration": {"level": "warning"},
    }


def _artifact_location(path: str, line: int) -> dict:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": _sarif_uri(path)},
            "region": {"startLine": max(1, int(line or 1))},
        }
    }


def _sarif_uri(path: str) -> str:
    normalized = str(path or "agent-run-diff-lab").replace("\\", "/")
    return normalized.lstrip("/")


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
