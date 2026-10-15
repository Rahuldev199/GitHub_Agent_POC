"""Backward-compatible GitHub client imports."""

from github_team_stats.infrastructure.github import GitHubApiError, GitHubRestClient

__all__ = ["GitHubApiError", "GitHubRestClient"]
