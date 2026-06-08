"""Typed data structures used by parsing, diffing, and reporting."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ToolCall:
    """Normalized representation of one tool call or command invocation."""

    index: int
    name: str
    call_id: str = ""
    input: Any = None
    output: Any = None
    status: str = "unknown"
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    error: str = ""
    retry_of: str = ""
    timestamp: str = ""

    @property
    def failed(self) -> bool:
        return self.status.lower() in {"failed", "error", "timeout", "cancelled"} or bool(self.error)


@dataclass(frozen=True)
class FileChange:
    """Normalized summary of one file touched during a run."""

    path: str
    status: str = "modified"
    added: int = 0
    removed: int = 0
    diff: str = ""
    risk: int = 0


@dataclass
class RunRecord:
    """A normalized agent run transcript."""

    run_id: str = ""
    source: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    file_changes: List[FileChange] = field(default_factory=list)
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def failures(self) -> int:
        return sum(1 for call in self.tool_calls if call.failed)

    @property
    def retry_count(self) -> int:
        explicit = sum(1 for call in self.tool_calls if call.retry_of)
        if explicit:
            return explicit
        seen = set()
        retries = 0
        for call in self.tool_calls:
            key = (call.name, stable_repr(call.input))
            if key in seen:
                retries += 1
            seen.add(key)
        return retries


@dataclass(frozen=True)
class ToolCallDiff:
    index: int
    baseline_name: Optional[str]
    candidate_name: Optional[str]
    change_type: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FileDiff:
    path: str
    change_type: str
    baseline: Optional[FileChange] = None
    candidate: Optional[FileChange] = None


@dataclass
class DiffResult:
    baseline: RunRecord
    candidate: RunRecord
    tool_diffs: List[ToolCallDiff] = field(default_factory=list)
    file_diffs: List[FileDiff] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    risk_score: int = 0
    risk_reasons: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "risk_score": self.risk_score,
            "risk_reasons": list(self.risk_reasons),
            "violations": list(self.violations),
            "metrics": self.metrics,
            "tool_diffs": [
                {
                    "index": diff.index,
                    "baseline_name": diff.baseline_name,
                    "candidate_name": diff.candidate_name,
                    "change_type": diff.change_type,
                    "details": diff.details,
                }
                for diff in self.tool_diffs
            ],
            "file_diffs": [
                {
                    "path": diff.path,
                    "change_type": diff.change_type,
                    "baseline": file_change_to_dict(diff.baseline),
                    "candidate": file_change_to_dict(diff.candidate),
                }
                for diff in self.file_diffs
            ],
        }


def file_change_to_dict(change: Optional[FileChange]) -> Optional[Dict[str, Any]]:
    if change is None:
        return None
    return {
        "path": change.path,
        "status": change.status,
        "added": change.added,
        "removed": change.removed,
        "risk": change.risk,
        "has_diff": bool(change.diff),
    }


def stable_repr(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}:{stable_repr(value[k])}" for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(stable_repr(item) for item in value) + "]"
    return repr(value)

