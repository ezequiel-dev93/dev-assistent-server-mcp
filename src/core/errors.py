from pathlib import Path


class DevAssistantError(Exception):
    """Base error for DevAssistant domain and application layers."""


class PathOutsideWorkspaceError(DevAssistantError, ValueError):
    """Raised when a target path resolves outside the allowed workspace roots."""


class ProtectedPathError(DevAssistantError, ValueError):
    """Raised when attempting to write to a protected directory or forbidden extension."""


class ConfigError(DevAssistantError, ValueError):
    """Raised when project or user configuration is invalid."""


class UnparseableFileError(DevAssistantError):
    """Raised when a source file cannot be parsed by its AST/syntax extractor."""

    def __init__(self, file_path: Path, cause: Exception) -> None:
        self.file_path = file_path
        self.cause = cause
        super().__init__(f"Cannot parse '{file_path}': {cause}")


class AdrNotFoundError(DevAssistantError, LookupError):
    """Raised when a requested ADR number does not exist in the project."""


class UnsafeTargetUrlError(DevAssistantError, ValueError):
    """Raised when an HTTP probe URL uses a forbidden scheme or targets a blocked SSRF address."""

