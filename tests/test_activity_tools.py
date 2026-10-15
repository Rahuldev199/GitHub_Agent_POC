import json

import pytest

from github_team_stats.activity_tools import (
    GetMemberGitActivityParams,
    GetMemberGitActivityTool,
)
from github_team_stats.errors import MemberAccessDenied


class FakeService:
    async def get_member_activity(self, member_login: str, period: str, *, force_refresh: bool):
        class Result:
            def model_dump(self, *, mode: str) -> dict:
                return {
                    "member": member_login,
                    "period": period,
                    "live": force_refresh,
                    "mode": mode,
                }

        return Result()


@pytest.mark.asyncio
async def test_activity_tool_passes_only_structured_parameters() -> None:
    payload = await GetMemberGitActivityTool(FakeService())(
        GetMemberGitActivityParams(member_login="rahul", period="2026-09", live=True)
    )
    assert json.loads(payload) == {
        "member": "rahul",
        "period": "2026-09",
        "live": True,
        "mode": "json",
    }


@pytest.mark.asyncio
async def test_activity_tool_returns_explicit_member_authorization_error() -> None:
    class DeniedService:
        async def get_member_activity(self, *_args, **_kwargs):
            raise MemberAccessDenied("Login 'rahuldev' is not an authorized member")

    payload = await GetMemberGitActivityTool(DeniedService())(
        GetMemberGitActivityParams(member_login="rahuldev", period="this month")
    )

    assert json.loads(payload) == {
        "ok": False,
        "error": {
            "code": "member_not_authorized",
            "message": "Login 'rahuldev' is not an authorized member",
        },
    }


def test_truncates_commit_messages_and_pr_titles_for_model() -> None:
    from github_team_stats.activity_tools import _truncate_untrusted_text

    activity = {
        "commits": [{"message": "x" * 700}],
        "pull_requests": [{"title": "y" * 400}],
        "reviews": [{"pull_title": "z" * 400}],
    }

    result = _truncate_untrusted_text(activity)

    assert len(activity["commits"][0]["message"]) == 500
    assert len(activity["pull_requests"][0]["title"]) == 300
    assert len(activity["reviews"][0]["pull_title"]) == 300
    assert result == {"commit_messages": True, "pull_request_titles": True}


def test_marks_only_failed_github_source_as_partial_for_model() -> None:
    from github_team_stats.activity_tools import _source_availability

    activity = {
        "warnings": [
            {
                "repository": "acme/api",
                "source": "commits",
                "code": 404,
                "message": "Not Found",
            }
        ]
    }

    assert _source_availability(activity) == {
        "commits": "partial",
        "pull_requests": "available",
        "reviews": "available",
        "workflow_runs": "available",
    }
