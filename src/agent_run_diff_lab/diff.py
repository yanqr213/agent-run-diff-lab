"""Comparison and risk scoring engine."""

from fnmatch import fnmatch
from typing import Any, Dict, Iterable, List, Tuple

from .config import DiffConfig
from .models import DiffResult, FileChange, FileDiff, RunRecord, ToolCall, ToolCallDiff, stable_repr


SENSITIVE_PATH_PATTERNS = [
    "*.env",
    ".env",
    "*secret*",
    "*credential*",
    "*token*",
    "*/.github/workflows/*",
    "pyproject.toml",
    "package.json",
]
RISKY_TOOL_NAMES = {"shell", "bash", "powershell", "exec", "terminal", "run_command"}
RISKY_INPUT_SNIPPETS = ["rm -rf", "curl ", "wget ", "chmod 777", "sudo ", "token", "secret"]


def compare_runs(baseline: RunRecord, candidate: RunRecord, config: DiffConfig = None) -> DiffResult:
    config = config or DiffConfig()
    base_calls = _filter_tools(baseline.tool_calls, config.ignored_tools)
    cand_calls = _filter_tools(candidate.tool_calls, config.ignored_tools)
    base_files = _filter_files(baseline.file_changes, config.ignored_paths)
    cand_files = _filter_files(candidate.file_changes, config.ignored_paths)

    result = DiffResult(baseline=baseline, candidate=candidate)
    result.tool_diffs = _diff_tools(base_calls, cand_calls, config)
    result.file_diffs = _diff_files(base_files, cand_files)
    result.metrics = _metrics(baseline, candidate, base_calls, cand_calls, base_files, cand_files)
    result.risk_score, result.risk_reasons = _risk(result.tool_diffs, result.file_diffs, cand_calls, cand_files, result.metrics)
    result.violations = _violations(result, config)
    result.passed = not result.violations
    return result


def _filter_tools(calls: Iterable[ToolCall], ignored_tools: Iterable[str]) -> List[ToolCall]:
    patterns = list(ignored_tools)
    return [call for call in calls if not any(fnmatch(call.name, pattern) for pattern in patterns)]


def _filter_files(changes: Iterable[FileChange], ignored_paths: Iterable[str]) -> List[FileChange]:
    patterns = list(ignored_paths)
    return [change for change in changes if not any(fnmatch(change.path, pattern) for pattern in patterns)]


def _diff_tools(base_calls: List[ToolCall], cand_calls: List[ToolCall], config: DiffConfig) -> List[ToolCallDiff]:
    diffs: List[ToolCallDiff] = []
    max_len = max(len(base_calls), len(cand_calls))
    for index in range(max_len):
        base = base_calls[index] if index < len(base_calls) else None
        cand = cand_calls[index] if index < len(cand_calls) else None
        if base is None and cand is not None:
            diffs.append(ToolCallDiff(index, None, cand.name, "added", _call_details(None, cand, config)))
            continue
        if cand is None and base is not None:
            diffs.append(ToolCallDiff(index, base.name, None, "removed", _call_details(base, None, config)))
            continue
        if base is None or cand is None:
            continue
        details = _call_details(base, cand, config)
        if base.name != cand.name:
            diffs.append(ToolCallDiff(index, base.name, cand.name, "reordered_or_replaced", details))
        elif details:
            diffs.append(ToolCallDiff(index, base.name, cand.name, "changed", details))

    if config.allow_tool_reorder:
        diffs = _downgrade_pure_reorder(diffs, base_calls, cand_calls)
    return diffs


def _call_details(base: ToolCall, cand: ToolCall, config: DiffConfig) -> Dict[str, Any]:
    details: Dict[str, Any] = {}
    if base is None or cand is None:
        call = cand or base
        details["status"] = call.status
        details["failed"] = call.failed
        if call.error:
            details["error"] = call.error
        return details
    if config.compare_inputs and stable_repr(base.input) != stable_repr(cand.input):
        details["input_changed"] = {"baseline": base.input, "candidate": cand.input}
    if config.compare_outputs and stable_repr(base.output) != stable_repr(cand.output):
        details["output_changed"] = {"baseline": base.output, "candidate": cand.output}
    if base.status != cand.status:
        details["status_changed"] = {"baseline": base.status, "candidate": cand.status}
    if bool(base.error) != bool(cand.error) or (base.error and base.error != cand.error):
        details["error_changed"] = {"baseline": base.error, "candidate": cand.error}
    if base.retry_of != cand.retry_of:
        details["retry_changed"] = {"baseline": base.retry_of, "candidate": cand.retry_of}
    duration_delta = cand.duration_ms - base.duration_ms
    cost_delta = cand.cost_usd - base.cost_usd
    if duration_delta:
        details["duration_ms_delta"] = duration_delta
    if cost_delta:
        details["cost_usd_delta"] = round(cost_delta, 8)
    return details


def _downgrade_pure_reorder(diffs: List[ToolCallDiff], base_calls: List[ToolCall], cand_calls: List[ToolCall]) -> List[ToolCallDiff]:
    if sorted(call.name for call in base_calls) == sorted(call.name for call in cand_calls):
        return [diff for diff in diffs if diff.change_type != "reordered_or_replaced"]
    return diffs


def _diff_files(base_files: List[FileChange], cand_files: List[FileChange]) -> List[FileDiff]:
    base_by_path = {change.path: change for change in base_files}
    cand_by_path = {change.path: change for change in cand_files}
    diffs: List[FileDiff] = []
    for path in sorted(set(base_by_path) | set(cand_by_path)):
        base = base_by_path.get(path)
        cand = cand_by_path.get(path)
        if base is None:
            diffs.append(FileDiff(path, "added", None, cand))
        elif cand is None:
            diffs.append(FileDiff(path, "removed", base, None))
        elif (base.status, base.added, base.removed, base.diff) != (cand.status, cand.added, cand.removed, cand.diff):
            diffs.append(FileDiff(path, "changed", base, cand))
    return diffs


def _metrics(
    baseline: RunRecord,
    candidate: RunRecord,
    base_calls: List[ToolCall],
    cand_calls: List[ToolCall],
    base_files: List[FileChange],
    cand_files: List[FileChange],
) -> Dict[str, Any]:
    return {
        "baseline_tools": len(base_calls),
        "candidate_tools": len(cand_calls),
        "tool_count_delta": len(cand_calls) - len(base_calls),
        "baseline_failures": sum(1 for call in base_calls if call.failed),
        "candidate_failures": sum(1 for call in cand_calls if call.failed),
        "failures_delta": sum(1 for call in cand_calls if call.failed) - sum(1 for call in base_calls if call.failed),
        "baseline_retries": baseline.retry_count,
        "candidate_retries": candidate.retry_count,
        "retries_delta": candidate.retry_count - baseline.retry_count,
        "baseline_duration_ms": baseline.duration_ms,
        "candidate_duration_ms": candidate.duration_ms,
        "duration_delta_ms": candidate.duration_ms - baseline.duration_ms,
        "duration_delta_pct": _pct_delta(baseline.duration_ms, candidate.duration_ms),
        "baseline_cost_usd": baseline.cost_usd,
        "candidate_cost_usd": candidate.cost_usd,
        "cost_delta_usd": round(candidate.cost_usd - baseline.cost_usd, 8),
        "cost_delta_pct": _pct_delta(baseline.cost_usd, candidate.cost_usd),
        "baseline_files": len(base_files),
        "candidate_files": len(cand_files),
        "file_changes_delta": len(cand_files) - len(base_files),
    }


def _pct_delta(base: float, cand: float) -> float:
    if base == 0 and cand == 0:
        return 0.0
    if base == 0:
        return 100.0
    return round(((cand - base) / base) * 100.0, 4)


def _risk(
    tool_diffs: List[ToolCallDiff], file_diffs: List[FileDiff], cand_calls: List[ToolCall], cand_files: List[FileChange], metrics: Dict[str, Any]
) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    if metrics["failures_delta"] > 0:
        points = min(25, metrics["failures_delta"] * 10)
        score += points
        reasons.append(f"candidate added {metrics['failures_delta']} failure(s) (+{points})")
    if metrics["retries_delta"] > 0:
        points = min(15, metrics["retries_delta"] * 5)
        score += points
        reasons.append(f"candidate added {metrics['retries_delta']} retry/retries (+{points})")
    for diff in tool_diffs:
        if diff.change_type == "reordered_or_replaced":
            score += 6
            reasons.append(f"tool order/name changed at index {diff.index} (+6)")
        elif diff.change_type in {"added", "removed"}:
            score += 5
            reasons.append(f"tool call {diff.change_type} at index {diff.index} (+5)")
        if diff.details.get("status_changed") or diff.details.get("error_changed"):
            score += 8
            reasons.append(f"tool status/error changed at index {diff.index} (+8)")
    for call in cand_calls:
        lower_name = call.name.lower()
        input_text = stable_repr(call.input).lower()
        if lower_name in RISKY_TOOL_NAMES or any(part in lower_name for part in RISKY_TOOL_NAMES):
            score += 4
            reasons.append(f"candidate used high-impact tool {call.name} (+4)")
        for snippet in RISKY_INPUT_SNIPPETS:
            if snippet in input_text:
                score += 8
                reasons.append(f"candidate tool input contains '{snippet.strip()}' (+8)")
                break
    for diff in file_diffs:
        points = 4 if diff.change_type == "changed" else 6
        score += points
        reasons.append(f"file {diff.change_type}: {diff.path} (+{points})")
    for change in cand_files:
        if _is_sensitive_path(change.path):
            score += 12
            reasons.append(f"sensitive path touched: {change.path} (+12)")
        if change.added + change.removed >= 200:
            score += 8
            reasons.append(f"large file delta in {change.path} (+8)")
        if change.risk:
            score += change.risk
            reasons.append(f"file-provided risk for {change.path} (+{change.risk})")
    return score, reasons


def _is_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(fnmatch(normalized, pattern.lower()) for pattern in SENSITIVE_PATH_PATTERNS)


def _violations(result: DiffResult, config: DiffConfig) -> List[str]:
    metrics = result.metrics
    violations: List[str] = []
    if config.max_duration_delta_pct is not None and metrics["duration_delta_pct"] > config.max_duration_delta_pct:
        violations.append(
            f"duration delta {metrics['duration_delta_pct']}% exceeds {config.max_duration_delta_pct}%"
        )
    if config.max_cost_delta_pct is not None and metrics["cost_delta_pct"] > config.max_cost_delta_pct:
        violations.append(f"cost delta {metrics['cost_delta_pct']}% exceeds {config.max_cost_delta_pct}%")
    if metrics["failures_delta"] > config.max_failures_delta:
        violations.append(f"failure delta {metrics['failures_delta']} exceeds {config.max_failures_delta}")
    if metrics["retries_delta"] > config.max_retries_delta:
        violations.append(f"retry delta {metrics['retries_delta']} exceeds {config.max_retries_delta}")
    if config.max_file_changes_delta is not None and metrics["file_changes_delta"] > config.max_file_changes_delta:
        violations.append(f"file change delta {metrics['file_changes_delta']} exceeds {config.max_file_changes_delta}")
    if not config.allow_new_failed_tools:
        for diff in result.tool_diffs:
            if diff.change_type == "added" and diff.details.get("failed"):
                violations.append(f"new failed tool call at index {diff.index}: {diff.candidate_name}")
    if result.risk_score > config.max_risk_score:
        violations.append(f"risk score {result.risk_score} exceeds {config.max_risk_score}")
    return violations

