"""Backward-compatible member-lines service imports."""

from github_team_stats.application.member_lines import MemberLinesService
from github_team_stats.application.ports import LinesSource

__all__ = ["LinesSource", "MemberLinesService"]
