"""Backward-compatible member-activity service imports."""

from github_team_stats.application.member_activity import MemberActivityService
from github_team_stats.application.ports import ActivitySource, ActivityStore

__all__ = ["ActivitySource", "ActivityStore", "MemberActivityService"]
