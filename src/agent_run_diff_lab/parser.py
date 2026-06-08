"""Transcript parsing for JSON and JSONL agent run records."""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .errors import ParseError
from .models import FileChange, RunRecord, ToolCall


TOOL_EVENT_TYPES = {
    "tool_call",
    "tool",
    "tool_use",
    "function_call",
    "command",
    "mcp_tool_call",
}
FILE_EVENT_TYPES = {"file_change", "file", "patch", "edit", "write_file"}


def parse_run_file(path: str) -> RunRecord:
    text = Path(path).read_text(encoding="utf-8")
    record = parse_run_text(text, source=path)
    if not record.run_id:
        record.run_id = Path(path).stem
    return record


def parse_run_text(text: str, source: str = "<memory>") -> RunRecord:
    stripped = text.strip()
    if not stripped:
        raise ParseError(f"Empty transcript: {source}")
    data = _parse_json_or_jsonl(stripped, source)
    record = _record_from_data(data, source)
    _derive_totals(record)
    return record


def _parse_json_or_jsonl(text: str, source: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_error:
        events = []
        for lineno, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ParseError(f"Invalid JSON/JSONL in {source} at line {lineno}: {exc}") from json_error
        if not events:
            raise ParseError(f"No JSONL events found in {source}")
        return events


def _record_from_data(data: Any, source: str) -> RunRecord:
    if isinstance(data, list):
        root: Dict[str, Any] = {"events": data}
    elif isinstance(data, dict):
        root = data
    else:
        raise ParseError(f"Transcript root must be object or array in {source}")

    events, event_source_key = _extract_events(root)
    if not all(isinstance(event, dict) for event in events):
        raise ParseError(f"All transcript events must be objects in {source}")

    record = RunRecord(
        run_id=str(root.get("run_id") or root.get("id") or root.get("session_id") or ""),
        source=source,
        events=list(events),
        duration_ms=_as_float(root.get("duration_ms") or root.get("elapsed_ms") or root.get("total_duration_ms")),
        cost_usd=_as_float(root.get("cost_usd") or root.get("total_cost_usd") or root.get("cost")),
        metadata={k: v for k, v in root.items() if k not in {"events", "steps", "messages", "tool_calls", "files"}},
    )

    tool_calls, orphan_results = _collect_tool_calls(root, events, event_source_key)
    record.tool_calls = tool_calls
    record.file_changes = _collect_file_changes(root, events, orphan_results)
    return record


def _extract_events(root: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    for key in ("events", "steps", "messages", "transcript"):
        if isinstance(root.get(key), list):
            return list(root[key]), key
    if isinstance(root.get("tool_calls"), list):
        return list(root["tool_calls"]), "tool_calls"
    return [], ""


def _collect_tool_calls(
    root: Dict[str, Any], events: Iterable[Dict[str, Any]], event_source_key: str
) -> Tuple[List[ToolCall], Dict[str, Dict[str, Any]]]:
    raw_calls: List[Dict[str, Any]] = []
    result_by_id: Dict[str, Dict[str, Any]] = {}
    for event in events:
        event_type = _event_type(event)
        if event_type in TOOL_EVENT_TYPES or _looks_like_tool_call(event):
            raw_calls.append(event)
        elif event_type in {"tool_result", "tool_output", "function_result"}:
            call_id = str(event.get("call_id") or event.get("tool_call_id") or event.get("id") or "")
            if call_id:
                result_by_id[call_id] = event
    if event_source_key != "tool_calls" and isinstance(root.get("tool_calls"), list):
        raw_calls.extend(item for item in root["tool_calls"] if isinstance(item, dict))

    calls: List[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        call_id = str(raw.get("call_id") or raw.get("tool_call_id") or raw.get("id") or "")
        result = result_by_id.get(call_id, {})
        calls.append(
            ToolCall(
                index=index,
                name=str(raw.get("name") or raw.get("tool") or raw.get("function") or raw.get("command") or "unknown"),
                call_id=call_id,
                input=_first_present(raw, ("input", "arguments", "args", "parameters", "command_input")),
                output=_first_present(raw, ("output", "result", "stdout", "content"), result),
                status=str(raw.get("status") or result.get("status") or _status_from_error(raw, result)),
                duration_ms=_as_float(raw.get("duration_ms") or raw.get("elapsed_ms") or result.get("duration_ms")),
                cost_usd=_as_float(raw.get("cost_usd") or raw.get("cost") or result.get("cost_usd")),
                error=str(raw.get("error") or result.get("error") or raw.get("stderr") or ""),
                retry_of=str(raw.get("retry_of") or raw.get("retryOf") or ""),
                timestamp=str(raw.get("timestamp") or raw.get("time") or ""),
            )
        )
    return calls, result_by_id


def _collect_file_changes(
    root: Dict[str, Any], events: Iterable[Dict[str, Any]], orphan_results: Dict[str, Dict[str, Any]]
) -> List[FileChange]:
    raw_files: List[Dict[str, Any]] = []
    if isinstance(root.get("files"), list):
        raw_files.extend(item for item in root["files"] if isinstance(item, dict))
    if isinstance(root.get("file_changes"), list):
        raw_files.extend(item for item in root["file_changes"] if isinstance(item, dict))
    for event in events:
        event_type = _event_type(event)
        if event_type in FILE_EVENT_TYPES or _looks_like_file_change(event):
            raw_files.append(event)
    changes = [_file_change(raw) for raw in raw_files]
    return _merge_file_changes(changes)


def _file_change(raw: Dict[str, Any]) -> FileChange:
    path = str(raw.get("path") or raw.get("file") or raw.get("filename") or raw.get("target") or "")
    diff = str(raw.get("diff") or raw.get("patch") or "")
    added = _as_int(raw.get("added") or raw.get("additions") or _count_diff_lines(diff, "+"))
    removed = _as_int(raw.get("removed") or raw.get("deletions") or _count_diff_lines(diff, "-"))
    return FileChange(
        path=path or "unknown",
        status=str(raw.get("status") or raw.get("change_type") or raw.get("operation") or "modified"),
        added=added,
        removed=removed,
        diff=diff,
        risk=_as_int(raw.get("risk")),
    )


def _merge_file_changes(changes: Iterable[FileChange]) -> List[FileChange]:
    merged: Dict[str, FileChange] = {}
    for change in changes:
        old = merged.get(change.path)
        if old is None:
            merged[change.path] = change
        else:
            merged[change.path] = FileChange(
                path=change.path,
                status=change.status if change.status != "modified" else old.status,
                added=old.added + change.added,
                removed=old.removed + change.removed,
                diff=(old.diff + "\n" + change.diff).strip(),
                risk=max(old.risk, change.risk),
            )
    return list(merged.values())


def _derive_totals(record: RunRecord) -> None:
    if not record.duration_ms:
        record.duration_ms = sum(call.duration_ms for call in record.tool_calls)
    if not record.cost_usd:
        record.cost_usd = sum(call.cost_usd for call in record.tool_calls)


def _event_type(event: Dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or event.get("kind") or "").lower()


def _looks_like_tool_call(event: Dict[str, Any]) -> bool:
    return any(key in event for key in ("name", "tool", "function", "command")) and any(
        key in event for key in ("input", "arguments", "args", "parameters", "output", "status")
    )


def _looks_like_file_change(event: Dict[str, Any]) -> bool:
    return any(key in event for key in ("path", "file", "filename")) and any(
        key in event for key in ("diff", "patch", "added", "removed", "additions", "deletions")
    )


def _first_present(raw: Dict[str, Any], keys: Iterable[str], fallback: Dict[str, Any] = None) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    fallback = fallback or {}
    for key in keys:
        if key in fallback:
            return fallback[key]
    return None


def _status_from_error(raw: Dict[str, Any], result: Dict[str, Any]) -> str:
    return "failed" if raw.get("error") or result.get("error") or raw.get("stderr") else "ok"


def _as_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _count_diff_lines(diff: str, prefix: str) -> int:
    if not diff:
        return 0
    excluded = "+++" if prefix == "+" else "---"
    return sum(1 for line in diff.splitlines() if line.startswith(prefix) and not line.startswith(excluded))
