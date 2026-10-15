"""Copilot tool adapter for member line totals."""

from __future__ import annotations

from pydantic import BaseModel, Field

from github_team_stats.agent.tools.errors import member_access_error
from github_team_stats.application.member_lines import MemberLinesService
from github_team_stats.domain.errors import MemberAccessDenied


class GetMemberLinesAddedParams(BaseModel):
    member_login: str = Field(description="Exact GitHub login of the member to analyze")
    period: str = Field(
        description="Required month as YYYY-MM, month name, 'this month', or 'last month'"
    )


class GetMemberLinesAddedTool:
    name = "get_member_lines_added"

    def __init__(self, service: MemberLinesService) -> None:
        self._service = service

    async def __call__(self, params: GetMemberLinesAddedParams) -> str:
        try:
            result = await self._service.get_member_lines_added(params.member_login, params.period)
        except MemberAccessDenied as error:
            return member_access_error(error)
        return result.model_dump_json(indent=2)
