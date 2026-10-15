import pytest

from github_team_stats.application.member_access import MemberAccessPolicy
from github_team_stats.domain.errors import PermissionDenied
from github_team_stats.domain.team import TeamDefinition


def _team(key: str, members: list[str], repositories: list[str]) -> TeamDefinition:
    return TeamDefinition.model_validate(
        {
            "_id": key,
            "team_name": key.title(),
            "lead_logins": ["team-lead"],
            "members": members,
            "repositories": repositories,
            "enabled": True,
        }
    )


class FakeTeamDirectory:
    def __init__(self, teams: list[TeamDefinition]) -> None:
        self.teams = teams
        self.lookups = 0

    def list_teams_for_lead(self, lead_login: str) -> list[TeamDefinition]:
        assert lead_login == "team-lead"
        self.lookups += 1
        return self.teams


def test_authenticated_user_can_report_on_self_without_team_registration() -> None:
    directory = FakeTeamDirectory([])

    scope = MemberAccessPolicy(directory).authorize("team-lead", "TEAM-LEAD")

    assert scope is None
    assert directory.lookups == 0


def test_team_member_uses_union_of_authorized_team_repositories() -> None:
    directory = FakeTeamDirectory(
        [
            _team("backend", ["Rahul"], ["acme/api", "acme/shared"]),
            _team("platform", ["rahul"], ["acme/shared", "acme/infra"]),
        ]
    )

    scope = MemberAccessPolicy(directory).authorize("team-lead", "RAHUL")

    assert scope is not None
    assert scope.repositories == ("acme/api", "acme/infra", "acme/shared")
    assert scope.cache_key == "repos:acme/api,acme/infra,acme/shared"


def test_login_outside_requesters_teams_is_rejected() -> None:
    directory = FakeTeamDirectory([_team("backend", ["Rahuldev199"], ["acme/api"])])

    with pytest.raises(PermissionDenied, match="not an authorized member"):
        MemberAccessPolicy(directory).authorize("team-lead", "rahuldev")
