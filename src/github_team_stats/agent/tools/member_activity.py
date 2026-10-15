"""Copilot tool adapter for complete member activity."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from github_team_stats.agent.tools.errors import member_access_error
from github_team_stats.application.member_activity import MemberActivityService
from github_team_stats.domain.errors import MemberAccessDenied


class GetMemberGitActivityParams(BaseModel):
    member_login: str = Field(description="Exact GitHub login of the member to analyze")
    period: str = Field(
        description="Required month as YYYY-MM, month name, 'this month', or 'last month'"
    )
    live: bool = Field(
        default=False,
        description=(
            "Set true when the user asks for current/open/live PR or workflow status; "
            "this bypasses the cache"
        ),
    )


class GetMemberGitActivityTool:
    name = "get_member_git_activity"

    def __init__(self, service: MemberActivityService) -> None:
        self._service = service

    async def __call__(self, params: GetMemberGitActivityParams) -> str:
        try:
            result = await self._service.get_member_activity(
                params.member_login, params.period, force_refresh=params.live
            )
        except MemberAccessDenied as error:
            return member_access_error(error)
        payload = result.model_dump(mode="json")
        activity = payload.get("activity")
        if isinstance(activity, dict):
            activity["source_availability"] = _source_availability(activity)
            payload["model_content_truncated"] = _truncate_untrusted_text(activity)
        return json.dumps(payload, indent=2)


def _source_availability(activity: dict[str, Any]) -> dict[str, str]:
    availability = {
        "commits": "available",
        "pull_requests": "available",
        "reviews": "available",
        "workflow_runs": "available",
    }
    source_mapping = {
        "commits": ("commits",),
        "pull_requests": ("pull_requests",),
        "reviews": ("reviews",),
        "actions": ("workflow_runs",),
        "repository": tuple(availability),
    }
    for warning in activity.get("warnings", []):
        if not isinstance(warning, dict) or int(warning.get("code", 0)) < 400:
            continue
        for source in source_mapping.get(str(warning.get("source", "")), ()):
            availability[source] = "partial"
    return availability


def _truncate_untrusted_text(activity: dict[str, Any]) -> dict[str, bool]:
    truncated = {"commit_messages": False, "pull_request_titles": False}
    for commit in activity.get("commits", []):
        commit["message"], changed = _bounded_text(str(commit.get("message", "")), 500)
        truncated["commit_messages"] |= changed
    for pull_request in activity.get("pull_requests", []):
        pull_request["title"], changed = _bounded_text(str(pull_request.get("title", "")), 300)
        truncated["pull_request_titles"] |= changed
    for review in activity.get("reviews", []):
        review["pull_title"], changed = _bounded_text(str(review.get("pull_title", "")), 300)
        truncated["pull_request_titles"] |= changed
    return truncated


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[: limit - 1] + "…", True
