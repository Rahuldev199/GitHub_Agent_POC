from datetime import UTC, datetime, timedelta

import pytest

from github_team_stats.models import GitHubMember, MemberLinesAdded
from github_team_stats.service import MemberLinesService


def make_stats(*, period="2025-09", age_hours=0, status="final"):
    timestamp = datetime.now(UTC) - timedelta(hours=age_hours)
    return MemberLinesAdded(
        member=GitHubMember(id=42, login="rahul"),
        period=period,
        scope="org:acme",
        repositories_counted=2,
        commits_counted=3,
        lines_added=250,
        generated_at=timestamp,
        data_as_of=timestamp,
        status=status,
    )


class FakeStore:
    def __init__(self, value=None):
        self.value = value
        self.saved = []

    def get_member_lines_added(self, requester_login, member_login, period, scope):
        return self.value

    def upsert_member_lines_added(self, requester_login, stats):
        self.value = stats
        self.saved.append(stats)

    def close(self):
        pass


class FakeSource:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def get_member(self, login):
        self.calls.append(("member", login))
        return self.value.member

    async def get_authenticated_login(self):
        return "rahul"

    async def resolve_repositories(self, organization, configured_repositories):
        self.calls.append(("repositories", organization, configured_repositories))
        return ["acme/api", "acme/web"]

    async def build_member_lines_added(self, member, repositories, period, scope):
        self.calls.append(("build", member.login, repositories, period.key, scope))
        return self.value


def service(store, source, *, ttl=3600):
    return MemberLinesService(
        store,
        source,
        organization="acme",
        configured_repositories=[],
        scope="org:acme",
        cache_ttl_seconds=ttl,
    )


@pytest.mark.asyncio
async def test_historical_cache_hit_skips_all_github_calls() -> None:
    cached = make_stats()
    source = FakeSource(cached)

    result = await service(FakeStore(cached), source).get_member_lines_added("Rahul", "2025-09")

    assert result.cache_status == "hit"
    assert result.stats.lines_added == 250
    assert source.calls == []


@pytest.mark.asyncio
async def test_cache_miss_validates_member_fetches_and_persists() -> None:
    fresh = make_stats()
    store = FakeStore()
    source = FakeSource(fresh)

    result = await service(store, source).get_member_lines_added("rahul", "2025-09")

    assert result.cache_status == "miss"
    assert source.calls == [
        ("member", "rahul"),
        ("repositories", "acme", []),
        ("build", "rahul", ["acme/api", "acme/web"], "2025-09", "org:acme"),
    ]
    assert store.saved == [fresh]


@pytest.mark.asyncio
async def test_stale_current_snapshot_is_refreshed() -> None:
    now = datetime.now(UTC)
    period = f"{now.year:04d}-{now.month:02d}"
    stale = make_stats(period=period, age_hours=2, status="current")
    fresh = make_stats(period=period, status="current")
    source = FakeSource(fresh)

    result = await service(FakeStore(stale), source).get_member_lines_added("rahul", period)

    assert result.cache_status == "refreshed"
    assert source.calls[0] == ("member", "rahul")


@pytest.mark.asyncio
async def test_member_and_period_are_required() -> None:
    source = FakeSource(make_stats())
    member_service = service(FakeStore(), source)

    with pytest.raises(ValueError, match="Member login"):
        await member_service.get_member_lines_added(" ", "2025-09")
    with pytest.raises(ValueError, match="valid GitHub login"):
        await member_service.get_member_lines_added("../rahul", "2025-09")
    with pytest.raises(ValueError, match="Period"):
        await member_service.get_member_lines_added("rahul", " ")
    assert source.calls == []
