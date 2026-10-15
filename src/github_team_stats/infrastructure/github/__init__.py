"""Read-only GitHub API infrastructure."""

from github_team_stats.infrastructure.github.client import GitHubRestClient
from github_team_stats.infrastructure.github.transport import GitHubApiError

__all__ = ["GitHubApiError", "GitHubRestClient"]
