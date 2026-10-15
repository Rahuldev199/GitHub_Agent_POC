from datetime import UTC, datetime

from github_team_stats.models import GitHubMember, MemberLinesAdded
from github_team_stats.store import SQLiteStatsStore


def test_sqlite_cache_is_isolated_by_requester(tmp_path) -> None:
    store = SQLiteStatsStore(tmp_path / "cache.sqlite3")
    stats = MemberLinesAdded(
        member=GitHubMember(id=1, login="member"),
        period="2026-09",
        scope="repos:acme/api",
        repositories_counted=1,
        commits_counted=1,
        lines_added=10,
        generated_at=datetime.now(UTC),
        data_as_of=datetime.now(UTC),
        status="final",
    )
    try:
        store.upsert_member_lines_added("lead-one", stats)
        assert (
            store.get_member_lines_added("lead-one", "member", "2026-09", "repos:acme/api")
            is not None
        )
        assert (
            store.get_member_lines_added("lead-two", "member", "2026-09", "repos:acme/api") is None
        )
    finally:
        store.close()
