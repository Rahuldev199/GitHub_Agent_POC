from datetime import UTC, datetime, timedelta

import pytest

from github_team_stats.activity_models import ActivityTotals, MemberGitActivity
from github_team_stats.activity_service import MemberActivityService
from github_team_stats.errors import PermissionDenied
from github_team_stats.models import GitHubMember
from github_team_stats.team_models import TeamDefinition


def _activity(*, status: str = "final", age_seconds: int = 0) -> MemberGitActivity:
    now = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return MemberGitActivity(
        member=GitHubMember(id=1, login="rahul"),
        period="2026-09",
        scope="org:acme",
        repositories_counted=1,
        totals=ActivityTotals(
            commits=1,
            lines_added=10,
            lines_deleted=2,
            lines_changed=12,
            pull_requests_opened=1,
            pull_requests_merged=0,
            reviews_submitted=1,
            workflow_runs=1,
        ),
        commits=[],
        pull_requests=[],
        reviews=[],
        workflow_runs=[],
        details_truncated={},
        generated_at=now,
        data_as_of=now,
        status=status,
    )


class FakeStore:
    def __init__(self, cached: MemberGitActivity | None = None) -> None:
        self.cached = cached
        self.saved: MemberGitActivity | None = None

    def get_member_activity(self, *_args) -> MemberGitActivity | None:
        return self.cached

    def upsert_member_activity(self, _requester_login: str, activity: MemberGitActivity) -> None:
        self.saved = activity

    def list_teams_for_lead(self, _lead_login: str) -> list[TeamDefinition]:
        return [
            TeamDefinition.model_validate(
                {
                    "_id": "backend",
                    "team_name": "Backend",
                    "lead_logins": ["team-lead"],
                    "members": ["Rahuldev199"],
                    "repositories": ["acme/api"],
                    "enabled": True,
                }
            )
        ]


class FakeSource:
    def __init__(self, result: MemberGitActivity, requester: str = "rahul") -> None:
        self.result = result
        self.requester = requester
        self.calls = 0

    async def get_member(self, login: str) -> GitHubMember:
        self.calls += 1
        return GitHubMember(id=1, login=login)

    async def get_authenticated_login(self) -> str:
        return self.requester

    async def resolve_repositories(self, _organization, _configured):
        return ["acme/api"]

    async def build_member_activity(self, *_args):
        return self.result


def _service(store: FakeStore, source: FakeSource) -> MemberActivityService:
    return MemberActivityService(
        store,
        source,
        organization="acme",
        configured_repositories=[],
        scope="org:acme",
        cache_ttl_seconds=60,
        detail_limit=200,
    )


@pytest.mark.asyncio
async def test_historical_cache_hit_does_not_call_github() -> None:
    cached = _activity()
    source = FakeSource(_activity())
    result = await _service(FakeStore(cached), source).get_member_activity("rahul", "2026-09")

    assert result.cache_status == "hit"
    assert source.calls == 0


@pytest.mark.asyncio
async def test_cache_miss_fetches_and_saves() -> None:
    store = FakeStore()
    source = FakeSource(_activity())
    result = await _service(store, source).get_member_activity("rahul", "2026-09")

    assert result.cache_status == "miss"
    assert source.calls == 1
    assert store.saved == result.activity


@pytest.mark.asyncio
async def test_incomplete_report_is_not_cached_as_final() -> None:
    store = FakeStore()
    incomplete = _activity()
    incomplete.complete = False
    incomplete.status = "current"
    incomplete.warnings = [
        {
            "repository": "acme/private",
            "source": "commits",
            "code": 404,
            "message": "Not visible",
        }
    ]

    result = await _service(store, FakeSource(incomplete)).get_member_activity("rahul", "2026-09")

    assert result.activity.complete is False
    assert store.saved is None


@pytest.mark.asyncio
async def test_invalid_login_is_rejected_before_data_access() -> None:
    source = FakeSource(_activity())
    with pytest.raises(ValueError, match="exact"):
        await _service(FakeStore(), source).get_member_activity("not a login", "2026-09")
    assert source.calls == 0


@pytest.mark.asyncio
async def test_member_outside_requesters_registered_team_is_rejected() -> None:
    source = FakeSource(_activity(), requester="team-lead")

    with pytest.raises(PermissionDenied, match="not an authorized member"):
        await _service(FakeStore(), source).get_member_activity("rahuldev", "2026-09")

    assert source.calls == 0
