"""Use case for cached member line-addition reports."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from github_team_stats.application.member_access import MemberAccessPolicy
from github_team_stats.application.ports import LinesSource, MemberLinesStore
from github_team_stats.domain.member import MemberLinesAdded, MemberLinesAddedResult
from github_team_stats.domain.periods import resolve_period

_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class MemberLinesService:
    def __init__(
        self,
        store: MemberLinesStore,
        source: LinesSource,
        *,
        organization: str | None,
        configured_repositories: list[str],
        scope: str,
        cache_ttl_seconds: int = 3600,
        access_policy: MemberAccessPolicy | None = None,
    ) -> None:
        self._store = store
        self._source = source
        self._organization = organization
        self._configured_repositories = configured_repositories
        self._scope = scope
        self._ttl = timedelta(seconds=cache_ttl_seconds)
        self._access_policy = access_policy or MemberAccessPolicy(store)

    def _is_fresh(self, stats: MemberLinesAdded) -> bool:
        if stats.status == "final":
            return True
        return datetime.now(UTC) - stats.data_as_of.astimezone(UTC) <= self._ttl

    async def get_member_lines_added(
        self, member_login: str, period_text: str, *, force_refresh: bool = False
    ) -> MemberLinesAddedResult:
        normalized_login = member_login.strip()
        if not normalized_login:
            raise ValueError("Member login is required")
        if not _LOGIN_RE.fullmatch(normalized_login):
            raise ValueError("Member must be an exact, valid GitHub login")
        if not period_text.strip():
            raise ValueError("Period is required")

        period = resolve_period(period_text)
        requester_login = await self._source.get_authenticated_login()
        member_scope = self._access_policy.authorize(requester_login, normalized_login)
        scope = member_scope.cache_key if member_scope is not None else self._scope
        cached = self._store.get_member_lines_added(
            requester_login, normalized_login, period.key, scope
        )
        if cached and not force_refresh and self._is_fresh(cached):
            return MemberLinesAddedResult(cache_status="hit", stats=cached)

        member = await self._source.get_member(normalized_login)
        repositories = (
            list(member_scope.repositories)
            if member_scope is not None
            else await self._source.resolve_repositories(
                self._organization, self._configured_repositories
            )
        )
        stats = await self._source.build_member_lines_added(member, repositories, period, scope)
        if stats.complete:
            self._store.upsert_member_lines_added(requester_login, stats)
        return MemberLinesAddedResult(cache_status="refreshed" if cached else "miss", stats=stats)
