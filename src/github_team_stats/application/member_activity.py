"""Use case for complete cached member activity reports."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from github_team_stats.application.member_access import MemberAccessPolicy
from github_team_stats.application.ports import ActivitySource, MemberActivityStore
from github_team_stats.domain.activity import MemberGitActivity, MemberGitActivityResult
from github_team_stats.domain.periods import resolve_period

_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class MemberActivityService:
    def __init__(
        self,
        store: MemberActivityStore,
        source: ActivitySource,
        *,
        organization: str | None,
        configured_repositories: list[str],
        scope: str,
        cache_ttl_seconds: int,
        detail_limit: int,
        access_policy: MemberAccessPolicy | None = None,
    ) -> None:
        self._store = store
        self._source = source
        self._organization = organization
        self._configured_repositories = configured_repositories
        self._scope = scope
        self._ttl = timedelta(seconds=cache_ttl_seconds)
        self._detail_limit = detail_limit
        self._access_policy = access_policy or MemberAccessPolicy(store)

    def _is_fresh(self, activity: MemberGitActivity) -> bool:
        if activity.status == "final":
            return True
        return datetime.now(UTC) - activity.data_as_of.astimezone(UTC) <= self._ttl

    async def get_member_activity(
        self, member_login: str, period_text: str, *, force_refresh: bool = False
    ) -> MemberGitActivityResult:
        login = member_login.strip()
        if not _LOGIN_RE.fullmatch(login):
            raise ValueError("Member must be an exact, valid GitHub login")
        if not period_text.strip():
            raise ValueError("Period is required")
        period = resolve_period(period_text)
        requester_login = await self._source.get_authenticated_login()
        member_scope = self._access_policy.authorize(requester_login, login)
        scope = member_scope.cache_key if member_scope is not None else self._scope
        cached = self._store.get_member_activity(requester_login, login, period.key, scope)
        if cached and not force_refresh and self._is_fresh(cached):
            return MemberGitActivityResult(cache_status="hit", activity=cached)

        member = await self._source.get_member(login)
        repositories = (
            list(member_scope.repositories)
            if member_scope is not None
            else await self._source.resolve_repositories(
                self._organization, self._configured_repositories
            )
        )
        activity = await self._source.build_member_activity(
            member, repositories, period, scope, self._detail_limit
        )
        if activity.complete:
            self._store.upsert_member_activity(requester_login, activity)
        return MemberGitActivityResult(
            cache_status="refreshed" if cached else "miss", activity=activity
        )
