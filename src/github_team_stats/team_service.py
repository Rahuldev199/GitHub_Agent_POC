"""Backward-compatible team-activity service imports."""

from github_team_stats.application.ports import TeamStore as TeamActivityStore
from github_team_stats.application.team_activity import TeamActivityService

__all__ = ["TeamActivityService", "TeamActivityStore"]
