from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from github_team_stats.domain.activity import ActivityTotals
from github_team_stats.domain.team import TeamActivityReport, TeamMemberActivity
from github_team_stats.presentation.terminal import TerminalPresenter


def report() -> TeamActivityReport:
    now = datetime.now(UTC)
    return TeamActivityReport(
        team_key="backend", team_name="Backend", requester_login="lead", period="2026-10",
        scope="repos:acme/api", members_requested=1, members_completed=0,
        totals=ActivityTotals(
            commits=0, lines_added=0, lines_deleted=0, lines_changed=0,
            pull_requests_opened=0, pull_requests_merged=0, reviews_submitted=0,
            workflow_runs=0,
        ),
        members=[TeamMemberActivity(member_login="alice", cache_status="failed")],
        complete=False, warnings=[], generated_at=now, data_as_of=now,
    )


def test_non_tty_auto_is_plain_and_has_no_ansi() -> None:
    output = io.StringIO()
    TerminalPresenter("auto", stream=output).render_model(report())
    assert "Team: Backend" in output.getvalue()
    assert "\x1b[" not in output.getvalue()


def test_json_stays_machine_readable() -> None:
    output = io.StringIO()
    TerminalPresenter("json", stream=output).render_model(report())
    assert json.loads(output.getvalue())["team_name"] == "Backend"
    assert "\x1b[" not in output.getvalue()


def test_csv_stays_machine_readable() -> None:
    output = io.StringIO()
    TerminalPresenter("csv", stream=output).render_model(report())
    assert output.getvalue().startswith("team,period,member")
    assert "alice" in output.getvalue()
