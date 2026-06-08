"""Configuration and validation for the diff gate."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .errors import ConfigError


@dataclass
class DiffConfig:
    max_duration_delta_pct: Optional[float] = 50.0
    max_cost_delta_pct: Optional[float] = 50.0
    max_failures_delta: int = 0
    max_retries_delta: int = 1
    max_risk_score: int = 39
    max_file_changes_delta: Optional[int] = None
    allow_new_failed_tools: bool = False
    allow_tool_reorder: bool = False
    compare_outputs: bool = True
    compare_inputs: bool = True
    ignored_tools: List[str] = field(default_factory=list)
    ignored_paths: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiffConfig":
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ConfigError(f"Unknown config keys: {', '.join(unknown)}")
        config = cls(**data)
        config.validate()
        return config

    def validate(self) -> None:
        numeric_min_zero = {
            "max_duration_delta_pct": self.max_duration_delta_pct,
            "max_cost_delta_pct": self.max_cost_delta_pct,
            "max_failures_delta": self.max_failures_delta,
            "max_retries_delta": self.max_retries_delta,
            "max_risk_score": self.max_risk_score,
            "max_file_changes_delta": self.max_file_changes_delta,
        }
        for name, value in numeric_min_zero.items():
            if value is not None and value < 0:
                raise ConfigError(f"{name} must be >= 0")
        for name in ("ignored_tools", "ignored_paths"):
            value = getattr(self, name)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ConfigError(f"{name} must be a list of strings")
        for name in ("allow_new_failed_tools", "allow_tool_reorder", "compare_outputs", "compare_inputs"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"{name} must be boolean")


def load_config(path: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None) -> DiffConfig:
    data: Dict[str, Any] = {}
    if path:
        raw = Path(path).read_text(encoding="utf-8")
        try:
            data.update(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid JSON config {path}: {exc}") from exc
    if overrides:
        data.update({key: value for key, value in overrides.items() if value is not None})
    return DiffConfig.from_dict(data) if data else DiffConfig()


def apply_list_overrides(config: DiffConfig, ignored_tools: Iterable[str], ignored_paths: Iterable[str]) -> DiffConfig:
    config.ignored_tools.extend(item for item in ignored_tools if item not in config.ignored_tools)
    config.ignored_paths.extend(item for item in ignored_paths if item not in config.ignored_paths)
    config.validate()
    return config

