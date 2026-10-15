"""Backward-compatible imports for the domain error hierarchy."""

from github_team_stats.domain.errors import (
    AppError,
    AuthError,
    ConfigError,
    GitHubError,
    MemberAccessDenied,
    NotFound,
    PermissionDenied,
    RateLimited,
)

__all__ = [
    "AppError",
    "AuthError",
    "ConfigError",
    "GitHubError",
    "MemberAccessDenied",
    "NotFound",
    "PermissionDenied",
    "RateLimited",
]
