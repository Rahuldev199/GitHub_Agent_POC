"""Protocols that keep application use cases independent of infrastructure."""

from __future__ import annotations

from typing import Any, Protocol

from github_team_stats.domain.activity import MemberGitActivity
from github_team_stats.domain.member import GitHubMember, MemberLinesAdded
from github_team_stats.domain.periods import Period
from github_team_stats.domain.team import TeamDefinition


class LinesStore(Protocol):
    def get_member_lines_added(
        self, requester_login: str, member_login: str, period: str, scope: str
    ) -> MemberLinesAdded | None: ...

    def upsert_member_lines_added(self, requester_login: str, stats: MemberLinesAdded) -> None: ...


class ActivityStore(Protocol):
    def get_member_activity(
        self, requester_login: str, member_login: str, period: str, scope: str
    ) -> MemberGitActivity | None: ...

    def upsert_member_activity(self, requester_login: str, activity: MemberGitActivity) -> None: ...


class TeamStore(ActivityStore, Protocol):
    def list_teams_for_lead(self, lead_login: str) -> list[TeamDefinition]: ...


class TeamDirectory(Protocol):
    def list_teams_for_lead(self, lead_login: str) -> list[TeamDefinition]: ...


class MemberActivityStore(ActivityStore, TeamDirectory, Protocol):
    """Storage capabilities required by an individual activity report."""


class MemberLinesStore(LinesStore, TeamDirectory, Protocol):
    """Storage capabilities required by an individual lines report."""


class AuditStore(Protocol):
    def append_conversation_audit(self, document: dict[str, Any]) -> None: ...

    def get_conversation_audit(
        self, *, session_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]: ...


class StatsStore(MemberLinesStore, TeamStore, AuditStore, Protocol):
    def close(self) -> None: ...


class GitHubIdentitySource(Protocol):
    async def get_authenticated_login(self) -> str: ...

    async def get_member(self, login: str) -> GitHubMember: ...

    async def resolve_repositories(
        self, organization: str | None, configured_repositories: list[str]
    ) -> list[str]: ...


class LinesSource(GitHubIdentitySource, Protocol):
    async def build_member_lines_added(
        self,
        member: GitHubMember,
        repositories: list[str],
        period: Period,
        scope: str,
    ) -> MemberLinesAdded: ...


class ActivitySource(GitHubIdentitySource, Protocol):
    async def build_member_activity(
        self,
        member: GitHubMember,
        repositories: list[str],
        period: Period,
        scope: str,
        detail_limit: int,
    ) -> MemberGitActivity: ...
