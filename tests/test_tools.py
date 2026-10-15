import json
from datetime import UTC, datetime

import pytest

from github_team_stats.errors import MemberAccessDenied
from github_team_stats.models import GitHubMember, MemberLinesAdded, MemberLinesAddedResult
from github_team_stats.tools import GetMemberLinesAddedParams, GetMemberLinesAddedTool


class FakeService:
    async def get_member_lines_added(self, member_login, period):
        stats = MemberLinesAdded(
            member=GitHubMember(id=42, login=member_login),
            period="2026-09",
            scope="org:acme",
            repositories_counted=2,
            commits_counted=3,
            lines_added=250,
            generated_at=datetime.now(UTC),
            data_as_of=datetime.now(UTC),
            status="final",
        )
        return MemberLinesAddedResult(cache_status="hit", stats=stats)


@pytest.mark.asyncio
async def test_tool_returns_structured_lines_added_json() -> None:
    output = await GetMemberLinesAddedTool(FakeService())(
        GetMemberLinesAddedParams(member_login="rahul", period="September 2026")
    )
    data = json.loads(output)
    assert data["cache_status"] == "hit"
    assert data["stats"]["member"]["login"] == "rahul"
    assert data["stats"]["lines_added"] == 250


@pytest.mark.asyncio
async def test_lines_tool_returns_explicit_member_authorization_error() -> None:
    class DeniedService:
        async def get_member_lines_added(self, *_args):
            raise MemberAccessDenied("Login 'rahuldev' is not an authorized member")

    output = await GetMemberLinesAddedTool(DeniedService())(
        GetMemberLinesAddedParams(member_login="rahuldev", period="this month")
    )

    assert json.loads(output)["error"]["code"] == "member_not_authorized"
