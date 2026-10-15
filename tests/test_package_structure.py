"""Protect the canonical package boundaries and legacy import compatibility."""

from github_team_stats.activity_service import MemberActivityService as LegacyActivityService
from github_team_stats.application.member_activity import MemberActivityService
from github_team_stats.application.ports import StatsStore
from github_team_stats.copilot_runtime import CopilotRuntime as LegacyCopilotRuntime
from github_team_stats.domain.member import GitHubMember
from github_team_stats.github_client import GitHubRestClient as LegacyGitHubRestClient
from github_team_stats.infrastructure.github import GitHubRestClient
from github_team_stats.infrastructure.persistence import MongoStatsStore, SQLiteStatsStore


def test_canonical_package_interfaces_are_importable() -> None:
    assert GitHubMember.__module__ == "github_team_stats.domain.member"
    assert MemberActivityService.__module__ == "github_team_stats.application.member_activity"
    assert GitHubRestClient.__module__ == "github_team_stats.infrastructure.github.client"
    assert MongoStatsStore.__module__.endswith("persistence.mongo")
    assert SQLiteStatsStore.__module__.endswith("persistence.sqlite")
    assert StatsStore.__module__ == "github_team_stats.application.ports"


def test_legacy_imports_reexport_canonical_types() -> None:
    assert LegacyActivityService is MemberActivityService
    assert LegacyGitHubRestClient is GitHubRestClient
    assert LegacyCopilotRuntime.__module__ == "github_team_stats.agent.runtime"
