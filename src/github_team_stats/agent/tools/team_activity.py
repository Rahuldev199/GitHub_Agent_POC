"""Copilot tool adapter for authorized team reports."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from github_team_stats.agent.tools.member_activity import (
    _source_availability,
    _truncate_untrusted_text,
)
from github_team_stats.application.team_activity import TeamActivityService


class GetTeamActivityParams(BaseModel):
    period: str = Field(
        description="Required month as YYYY-MM, month name, 'this month', or 'last month'"
    )
    team_name: str | None = Field(
        default=None,
        description="Optional authorized team name; omit when the lead has exactly one team",
    )
    member_logins: list[str] = Field(
        default_factory=list,
        description=(
            "Optional selected GitHub logins. Every login must belong to the authorized team. "
            "Use an empty list to report all configured team members."
        ),
    )
    live: bool = Field(
        default=False,
        description="Set true for current, open, or explicitly live status requests",
    )


class GetTeamActivityTool:
    name = "get_team_activity"

    def __init__(self, service: TeamActivityService) -> None:
        self._service = service

    async def __call__(self, params: GetTeamActivityParams) -> str:
        result = await self._service.get_team_activity(
            params.period,
            team_name=params.team_name,
            member_logins=params.member_logins,
            force_refresh=params.live,
        )
        payload = result.model_dump(mode="json")
        truncation = {"commit_messages": False, "pull_request_titles": False}
        for member in payload.get("members", []):
            activity = member.get("activity") if isinstance(member, dict) else None
            if not isinstance(activity, dict):
                continue
            activity["source_availability"] = _source_availability(activity)
            member_truncation = _truncate_untrusted_text(activity)
            for key, changed in member_truncation.items():
                truncation[key] |= changed
        payload["model_content_truncated"] = truncation
        return json.dumps(payload, indent=2)
