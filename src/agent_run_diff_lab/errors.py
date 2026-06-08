"""Project exceptions."""


class AgentRunDiffError(Exception):
    """Base exception for user-facing failures."""


class ParseError(AgentRunDiffError):
    """Raised when a transcript cannot be parsed."""


class ConfigError(AgentRunDiffError):
    """Raised when a config file or CLI threshold is invalid."""

