"""Backward-compatible settings imports."""

from github_team_stats.infrastructure.settings import (
    CONFIG_PATH,
    Settings,
    get_settings,
    resolve_copilot_token,
    resolve_github_credential,
    resolve_github_token,
)

__all__ = [
    "CONFIG_PATH",
    "Settings",
    "get_settings",
    "resolve_copilot_token",
    "resolve_github_credential",
    "resolve_github_token",
]
