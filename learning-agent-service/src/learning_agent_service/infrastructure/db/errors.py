"""Infrastructure-specific exceptions for optional service dependencies."""

from __future__ import annotations


class InfrastructureError(RuntimeError):
    """Base error type for infrastructure bootstrap issues."""


class InfrastructureDependencyError(InfrastructureError):
    """Raised when an optional dependency is required but not installed."""


class InfrastructureConfigurationError(InfrastructureError):
    """Raised when runtime configuration is incomplete or invalid."""


def require_dependency(package_name: str, purpose: str) -> None:
    """Raise a consistent error for optional dependencies."""

    raise InfrastructureDependencyError(
        "Optional dependency '%s' is required for %s. Install the package before enabling this adapter."
        % (package_name, purpose)
    )
