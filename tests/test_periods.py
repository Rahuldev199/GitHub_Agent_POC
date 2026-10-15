from datetime import UTC, datetime

import pytest

from github_team_stats.periods import resolve_period

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09", "2026-09"),
        ("September", "2026-09"),
        ("Sep 2025", "2025-09"),
        ("this month", "2026-10"),
        ("last month", "2026-09"),
    ],
)
def test_resolve_period(value: str, expected: str) -> None:
    assert resolve_period(value, now=NOW).key == expected


def test_bare_future_month_means_most_recent_occurrence() -> None:
    assert resolve_period("December", now=NOW).key == "2025-12"


def test_rejects_future_explicit_period() -> None:
    with pytest.raises(ValueError, match="Future"):
        resolve_period("2026-11", now=NOW)
