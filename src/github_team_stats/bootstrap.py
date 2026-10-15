"""Application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from github_team_stats.agent.runtime import CopilotRuntime
from github_team_stats.agent.tools.member_activity import GetMemberGitActivityTool
from github_team_stats.agent.tools.member_lines import GetMemberLinesAddedTool
from github_team_stats.agent.tools.team_activity import GetTeamActivityTool
from github_team_stats.application.member_activity import MemberActivityService
from github_team_stats.application.member_lines import MemberLinesService
from github_team_stats.application.ports import StatsStore
from github_team_stats.application.team_activity import TeamActivityService
from github_team_stats.infrastructure.audit import ConversationAuditor
from github_team_stats.infrastructure.github import GitHubRestClient
from github_team_stats.infrastructure.persistence import MongoStatsStore, SQLiteStatsStore
from github_team_stats.infrastructure.runtime_settings import resolve_runtime_settings
from github_team_stats.infrastructure.settings import (
    Settings,
    resolve_copilot_token,
    resolve_github_token,
)


@dataclass(slots=True)
class Application:
    settings: Settings
    github: GitHubRestClient
    store: StatsStore
    service: MemberLinesService
    tool: GetMemberLinesAddedTool
    activity_service: MemberActivityService
    activity_tool: GetMemberGitActivityTool
    team_activity_service: TeamActivityService
    team_activity_tool: GetTeamActivityTool
    runtime: CopilotRuntime

    async def close(self) -> None:
        await self.runtime.close()
        await self.github.aclose()
        self.store.close()


def build_application(settings: Settings) -> Application:
    settings = resolve_runtime_settings(settings)
    github_token = resolve_github_token(settings)
    github = GitHubRestClient(
        github_token,
        api_url=settings.github_api_url,
        api_version=settings.github_api_version,
        concurrency=settings.github_concurrency,
        max_retries=settings.github_max_retries,
        rate_limit_warning_threshold=settings.github_rate_limit_warning_threshold,
    )
    if settings.cache_backend == "mongodb":
        store: StatsStore = MongoStatsStore(
            settings.mongodb_uri.get_secret_value(),
            settings.mongodb_database,
            audit_enabled=settings.audit_enabled,
        )
    else:
        store = SQLiteStatsStore(settings.resolved_sqlite_path)
    service = MemberLinesService(
        store,
        github,
        organization=settings.github_organization,
        configured_repositories=settings.repositories,
        scope=settings.scope_key,
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )
    tool = GetMemberLinesAddedTool(service)
    activity_service = MemberActivityService(
        store,
        github,
        organization=settings.github_organization,
        configured_repositories=settings.repositories,
        scope=settings.scope_key,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        detail_limit=settings.activity_detail_limit,
    )
    activity_tool = GetMemberGitActivityTool(activity_service)
    team_activity_service = TeamActivityService(
        store,
        github,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        detail_limit=settings.activity_detail_limit,
        member_concurrency=settings.team_member_concurrency,
    )
    team_activity_tool = GetTeamActivityTool(team_activity_service)
    auditor = (
        ConversationAuditor(
            store,
            model=settings.copilot_model,
            retention_days=settings.audit_retention_days,
            include_user_messages=settings.audit_include_user_messages,
            include_assistant_responses=settings.audit_include_assistant_responses,
        )
        if settings.audit_enabled
        else None
    )
    runtime = CopilotRuntime(
        tool,
        activity_tool,
        team_activity_tool,
        model=settings.copilot_model,
        github_token=resolve_copilot_token(settings, github_token),
        auditor=auditor,
    )
    return Application(
        settings,
        github,
        store,
        service,
        tool,
        activity_service,
        activity_tool,
        team_activity_service,
        team_activity_tool,
        runtime,
    )
