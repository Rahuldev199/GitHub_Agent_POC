"""Use case for authorized team activity aggregation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from github_team_stats.application.member_activity import MemberActivityService
from github_team_stats.application.ports import ActivitySource, TeamStore
from github_team_stats.domain.activity import ActivityTotals, MemberGitActivity
from github_team_stats.domain.errors import AuthError, GitHubError, PermissionDenied, RateLimited
from github_team_stats.domain.periods import resolve_period
from github_team_stats.domain.team import (
    TeamActivityReport,
    TeamActivityWarning,
    TeamDefinition,
    TeamMemberActivity,
)
from github_team_stats.infrastructure.security import redact_text


class TeamActivityService:
    def __init__(
        self,
        store: TeamStore,
        source: ActivitySource,
        *,
        cache_ttl_seconds: int,
        detail_limit: int,
        member_concurrency: int,
    ) -> None:
        self._store = store
        self._source = source
        self._cache_ttl_seconds = cache_ttl_seconds
        self._detail_limit = detail_limit
        self._semaphore = asyncio.Semaphore(member_concurrency)

    async def get_team_activity(
        self,
        period_text: str,
        *,
        team_name: str | None = None,
        member_logins: list[str] | None = None,
        force_refresh: bool = False,
    ) -> TeamActivityReport:
        period = resolve_period(period_text)
        requester_login = await self._source.get_authenticated_login()
        team = self._select_team(
            self._store.list_teams_for_lead(requester_login), team_name, requester_login
        )
        selected_members = self._select_members(team, member_logins or [])
        member_service = MemberActivityService(
            self._store,
            self._source,
            organization=None,
            configured_repositories=team.repositories,
            scope=team.scope_key,
            cache_ttl_seconds=self._cache_ttl_seconds,
            detail_limit=self._detail_limit,
        )

        async def collect(member_login: str) -> TeamMemberActivity | BaseException:
            async with self._semaphore:
                try:
                    result = await member_service.get_member_activity(
                        member_login, period.key, force_refresh=force_refresh
                    )
                    return TeamMemberActivity(
                        member_login=member_login,
                        cache_status=result.cache_status,
                        activity=result.activity,
                    )
                except (AuthError, RateLimited):
                    raise
                except GitHubError as error:
                    return error

        collected = await asyncio.gather(*(collect(login) for login in selected_members))
        members: list[TeamMemberActivity] = []
        warnings: list[TeamActivityWarning] = []
        activities = []
        for member_login, result in zip(selected_members, collected, strict=True):
            if isinstance(result, BaseException):
                error = result
                code = error.status_code if isinstance(error, GitHubError) else 0
                warnings.append(
                    TeamActivityWarning(
                        member_login=member_login,
                        repository="*",
                        source="member",
                        code=code or 0,
                        message=redact_text(str(error)),
                    )
                )
                members.append(TeamMemberActivity(member_login=member_login, cache_status="failed"))
                continue
            members.append(result)
            if result.activity is None:
                raise RuntimeError("Successful team member result did not include activity")
            activities.append(result.activity)
            for warning in result.activity.warnings:
                warnings.append(
                    TeamActivityWarning(
                        member_login=member_login,
                        repository=warning.repository,
                        source=warning.source,
                        code=warning.code,
                        message=warning.message,
                    )
                )

        now = datetime.now(UTC)
        complete = len(activities) == len(selected_members) and all(
            activity.complete for activity in activities
        )
        return TeamActivityReport(
            team_key=team.team_key,
            team_name=team.team_name,
            requester_login=requester_login,
            period=period.key,
            scope=team.scope_key,
            members_requested=len(selected_members),
            members_completed=len(activities),
            totals=_aggregate_totals(activities),
            members=members,
            complete=complete,
            warnings=warnings,
            generated_at=now,
            data_as_of=min((activity.data_as_of for activity in activities), default=now),
        )

    @staticmethod
    def _select_team(
        teams: list[TeamDefinition], team_name: str | None, requester_login: str
    ) -> TeamDefinition:
        if team_name:
            requested = team_name.strip().casefold()
            matches = [
                team
                for team in teams
                if requested in {team.team_key.casefold(), team.team_name.casefold()}
            ]
            if len(matches) == 1:
                return matches[0]
            raise PermissionDenied(
                f"GitHub user {requester_login!r} is not authorized for team {team_name!r}"
            )
        if len(teams) == 1:
            return teams[0]
        if not teams:
            raise PermissionDenied(
                f"GitHub user {requester_login!r} is not configured as a team lead"
            )
        names = ", ".join(sorted(team.team_name for team in teams))
        raise ValueError(f"Multiple authorized teams found; specify one of: {names}")

    @staticmethod
    def _select_members(team: TeamDefinition, requested_logins: list[str]) -> list[str]:
        if not requested_logins:
            return team.members
        authorized = {login.casefold(): login for login in team.members}
        selected: list[str] = []
        seen: set[str] = set()
        unauthorized: list[str] = []
        for requested_login in requested_logins:
            normalized = requested_login.strip().casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            configured_login = authorized.get(normalized)
            if configured_login is None:
                unauthorized.append(requested_login.strip())
            else:
                selected.append(configured_login)
        if unauthorized:
            names = ", ".join(unauthorized)
            raise PermissionDenied(f"Requested member(s) are not authorized for this team: {names}")
        if not selected:
            raise ValueError("At least one team member login is required")
        return selected


def _aggregate_totals(activities: list[MemberGitActivity]) -> ActivityTotals:
    fields = ActivityTotals.model_fields
    totals = {
        field: sum(getattr(activity.totals, field) for activity in activities) for field in fields
    }
    return ActivityTotals(**totals)
