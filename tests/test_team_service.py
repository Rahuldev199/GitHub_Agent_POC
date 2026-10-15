from datetime import UTC, datetime

import pytest

from github_team_stats.activity_models import ActivityTotals, MemberGitActivity
from github_team_stats.errors import AuthError, NotFound, PermissionDenied
from github_team_stats.models import GitHubMember
from github_team_stats.team_models import TeamDefinition
from github_team_stats.team_service import TeamActivityService


def _activity(login: str, lines_added: int, *, complete: bool = True) -> MemberGitActivity:
    now = datetime.now(UTC)
    return MemberGitActivity(
        member=GitHubMember(id=len(login), login=login),
        period="2026-09",
        scope="repos:acme/api",
        repositories_counted=1,
        totals=ActivityTotals(
            commits=1,
            lines_added=lines_added,
            lines_deleted=2,
            lines_changed=lines_added + 2,
            pull_requests_opened=1,
            pull_requests_merged=1,
            reviews_submitted=1,
            workflow_runs=1,
        ),
        commits=[],
        pull_requests=[],
        reviews=[],
        workflow_runs=[],
        details_truncated={},
        complete=complete,
        warnings=(
            []
            if complete
            else [
                {
                    "repository": "acme/api",
                    "source": "actions",
                    "code": 403,
                    "message": "Actions unavailable",
                }
            ]
        ),
        generated_at=now,
        data_as_of=now,
        status="final" if complete else "current",
    )


def _team(key: str = "backend", name: str = "Backend") -> TeamDefinition:
    return TeamDefinition.model_validate(
        {
            "_id": key,
            "team_name": name,
            "lead_logins": ["team-lead"],
            "members": ["rahul", "alice"],
            "repositories": ["acme/api"],
            "enabled": True,
        }
    )


class FakeStore:
    def __init__(self, teams: list[TeamDefinition]) -> None:
        self.teams = teams
        self.cached: dict[str, MemberGitActivity] = {}
        self.saved: list[str] = []

    def list_teams_for_lead(self, lead_login: str) -> list[TeamDefinition]:
        assert lead_login == "team-lead"
        return self.teams

    def get_member_activity(
        self, _requester: str, member: str, _period: str, _scope: str
    ) -> MemberGitActivity | None:
        return self.cached.get(member.casefold())

    def upsert_member_activity(self, _requester: str, activity: MemberGitActivity) -> None:
        self.saved.append(activity.member.login)


class FakeSource:
    def __init__(
        self,
        activities: dict[str, MemberGitActivity],
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.activities = activities
        self.failures = failures or {}

    async def get_authenticated_login(self) -> str:
        return "team-lead"

    async def get_member(self, login: str) -> GitHubMember:
        failure = self.failures.get(login)
        if failure:
            raise failure
        return GitHubMember(id=len(login), login=login)

    async def resolve_repositories(self, _organization, configured):
        return configured

    async def build_member_activity(self, member: GitHubMember, *_args):
        return self.activities[member.login]


def _service(store: FakeStore, source: FakeSource) -> TeamActivityService:
    return TeamActivityService(
        store,
        source,
        cache_ttl_seconds=3600,
        detail_limit=200,
        member_concurrency=2,
    )


@pytest.mark.asyncio
async def test_aggregates_authorized_team_members_in_python() -> None:
    store = FakeStore([_team()])
    source = FakeSource({"rahul": _activity("rahul", 100), "alice": _activity("alice", 250)})

    report = await _service(store, source).get_team_activity("2026-09")

    assert report.team_name == "Backend"
    assert report.requester_login == "team-lead"
    assert report.members_requested == 2
    assert report.members_completed == 2
    assert report.totals.lines_added == 350
    assert report.totals.commits == 2
    assert report.complete is True
    assert store.saved == ["rahul", "alice"]


@pytest.mark.asyncio
async def test_selected_authorized_member_returns_only_that_member() -> None:
    store = FakeStore([_team()])
    source = FakeSource({"rahul": _activity("rahul", 100), "alice": _activity("alice", 250)})

    report = await _service(store, source).get_team_activity(
        "2026-09", member_logins=["ALICE", "alice"]
    )

    assert report.members_requested == 1
    assert report.members_completed == 1
    assert report.totals.lines_added == 250
    assert [member.member_login for member in report.members] == ["alice"]
    assert store.saved == ["alice"]


@pytest.mark.asyncio
async def test_selected_member_outside_authorized_team_is_denied() -> None:
    store = FakeStore([_team()])
    source = FakeSource({})

    with pytest.raises(PermissionDenied, match="not authorized"):
        await _service(store, source).get_team_activity(
            "2026-09", member_logins=["unauthorized-user"]
        )


@pytest.mark.asyncio
async def test_member_failure_returns_partial_team_report_not_false_zero() -> None:
    store = FakeStore([_team()])
    source = FakeSource(
        {"rahul": _activity("rahul", 100)},
        {"alice": NotFound("Member not found", status_code=404, path="/users/alice")},
    )

    report = await _service(store, source).get_team_activity("2026-09")

    assert report.complete is False
    assert report.members_completed == 1
    assert report.totals.lines_added == 100
    assert report.members[1].cache_status == "failed"
    assert report.warnings[0].member_login == "alice"
    assert report.warnings[0].code == 404


@pytest.mark.asyncio
async def test_authentication_failure_aborts_team_report() -> None:
    source = FakeSource(
        {"alice": _activity("alice", 250)},
        {"rahul": AuthError("Invalid token", status_code=401, path="/users/rahul")},
    )

    with pytest.raises(AuthError):
        await _service(FakeStore([_team()]), source).get_team_activity("2026-09")


@pytest.mark.asyncio
async def test_requester_without_authorized_team_is_denied() -> None:
    with pytest.raises(PermissionDenied, match="not configured as a team lead"):
        await _service(FakeStore([]), FakeSource({})).get_team_activity("2026-09")


@pytest.mark.asyncio
async def test_named_team_must_be_authorized_for_requester() -> None:
    store = FakeStore([_team(), _team("mobile", "Mobile")])
    source = FakeSource({})

    with pytest.raises(ValueError, match="Multiple authorized teams"):
        await _service(store, source).get_team_activity("2026-09")
    with pytest.raises(PermissionDenied, match="not authorized"):
        await _service(store, source).get_team_activity("2026-09", team_name="Finance")
