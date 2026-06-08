"""agent-run-diff-lab public API."""

from .config import DiffConfig, load_config
from .diff import compare_runs
from .models import DiffResult, FileChange, RunRecord, ToolCall
from .parser import parse_run_file, parse_run_text

__all__ = [
    "DiffConfig",
    "DiffResult",
    "FileChange",
    "RunRecord",
    "ToolCall",
    "compare_runs",
    "load_config",
    "parse_run_file",
    "parse_run_text",
]

__version__ = "0.1.0"

