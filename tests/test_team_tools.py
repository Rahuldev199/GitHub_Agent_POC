import json

import pytest

from github_team_stats.team_tools import GetTeamActivityParams, GetTeamActivityTool


class FakeTeamService:
    async def get_team_activity(
        self,
        period: str,
        *,
        team_name: str | None,
        member_logins: list[str],
        force_refresh: bool,
    ):
        class Result:
            def model_dump(self, *, mode: str) -> dict:
                assert mode == "json"
                return {
                    "period": period,
                    "team_name": team_name,
                    "member_logins": member_logins,
                    "live": force_refresh,
                    "members": [
                        {
                            "member_login": "rahul",
                            "activity": {
                                "commits": [{"message": "x" * 700}],
                                "pull_requests": [],
                                "reviews": [],
                                "warnings": [],
                            },
                        }
                    ],
                }

        return Result()


@pytest.mark.asyncio
async def test_team_tool_passes_structured_parameters_and_bounds_model_content() -> None:
    output = await GetTeamActivityTool(FakeTeamService())(
        GetTeamActivityParams(
            period="last month",
            team_name="Backend",
            member_logins=["rahul", "alice"],
            live=True,
        )
    )
    payload = json.loads(output)

    assert payload["period"] == "last month"
    assert payload["team_name"] == "Backend"
    assert payload["member_logins"] == ["rahul", "alice"]
    assert payload["live"] is True
    assert len(payload["members"][0]["activity"]["commits"][0]["message"]) == 500
    assert payload["members"][0]["activity"]["source_availability"] == {
        "commits": "available",
        "pull_requests": "available",
        "reviews": "available",
        "workflow_runs": "available",
    }
    assert payload["model_content_truncated"]["commit_messages"] is True
