"""Human and machine-readable terminal presentation."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import IO, Any

from pydantic import BaseModel
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from github_team_stats.domain.activity import MemberGitActivityResult
from github_team_stats.domain.member import MemberLinesAddedResult
from github_team_stats.domain.team import TeamActivityReport, TeamMemberActivity

FORMATS = ("auto", "rich", "plain", "json", "csv")


class TerminalPresenter:
    """Render reports without mixing decorative and machine-readable output."""

    def __init__(self, output_format: str = "auto", *, stream: IO[str] | None = None) -> None:
        self.format = output_format
        self.stream = stream or sys.stdout
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.rich_enabled = output_format == "rich" or (
            output_format == "auto" and self.is_tty
        )
        self.console = Console(
            file=self.stream,
            no_color="NO_COLOR" in os.environ,
            force_terminal=self.rich_enabled,
            markup=self.rich_enabled,
        )

    def working(self, message: str) -> AbstractContextManager[Any]:
        if self.rich_enabled:
            return self.console.status(f"[cyan]{message}[/cyan]", spinner="dots")
        return nullcontext()

    @contextmanager
    def progress(self, message: str) -> Iterator[None]:
        if not self.rich_enabled:
            yield
            return
        progress = Progress(
            SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(),
            TimeElapsedColumn(), console=self.console, transient=True,
        )
        with progress:
            progress.add_task(message, total=None)
            yield

    def banner(self) -> None:
        if self.rich_enabled:
            self.console.print(
                Panel.fit(
                    "[bold cyan]GitHub Member Activity[/bold cyan]\n[dim]Read-only reporting[/dim]",
                    border_style="cyan",
                )
            )
        else:
            print("GitHub Member Activity — read-only reporting", file=self.stream)

    def chat_user(self, message: str) -> None:
        if self.rich_enabled:
            self.console.print(Panel(Text(message), title="You", border_style="blue"))

    def chat_agent(self, message: str) -> None:
        if self.rich_enabled:
            self.console.print(Panel(Markdown(message), title="Agent", border_style="green"))
        else:
            print(f"Agent: {message}", file=self.stream)

    def render_model(self, value: BaseModel) -> None:
        if self.format == "json":
            print(json.dumps(value.model_dump(mode="json"), indent=2), file=self.stream)
            return
        if self.format == "csv":
            print(_csv_for(value), end="", file=self.stream)
            return
        if isinstance(value, TeamActivityReport):
            self._team(value)
        elif isinstance(value, MemberGitActivityResult):
            self._member(value)
        elif isinstance(value, MemberLinesAddedResult):
            self._lines(value)
        else:
            self._plain_model(value)

    def _header(self, subject: str, period: str, source: str, complete: bool) -> None:
        status = "complete" if complete else "incomplete"
        content = f"[bold]{subject}[/bold]\nPeriod: {period}  •  Source: {source}  •  {status}"
        self.console.print(Panel(content, border_style="green" if complete else "yellow"))

    def _member(self, result: MemberGitActivityResult) -> None:
        activity = result.activity
        if not self.rich_enabled:
            self._plain_model(result)
            return
        self._header(activity.member.login, activity.period, result.cache_status, activity.complete)
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        for label, value in _total_rows(activity.totals):
            table.add_row(label, _value_text(value))
        self.console.print(table)
        self._warnings(activity.warnings)

    def _lines(self, result: MemberLinesAddedResult) -> None:
        stats = result.stats
        if not self.rich_enabled:
            self._plain_model(result)
            return
        self._header(stats.member.login, stats.period, result.cache_status, stats.complete)
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Commits counted", _value_text(stats.commits_counted))
        table.add_row("Lines added", _value_text(stats.lines_added))
        table.add_row("Repositories", _value_text(stats.repositories_counted))
        self.console.print(table)
        self._warnings(stats.warnings)

    def _team(self, report: TeamActivityReport) -> None:
        if not self.rich_enabled:
            self._plain_team(report)
            return
        sources = sorted({member.cache_status for member in report.members})
        self._header(report.team_name, report.period, ", ".join(sources), report.complete)
        table = Table(show_header=True, header_style="bold cyan", row_styles=("", "dim"))
        columns = (
            ("Member", None),
            ("Commits", "commits"),
            ("Added", "lines_added"),
            ("Deleted", "lines_deleted"),
            ("PRs", "pull_requests_opened"),
            ("Reviews", "reviews_submitted"),
            ("Runs", "workflow_runs"),
            ("Status", None),
        )
        for title, _ in columns:
            table.add_column(title, justify="left" if title in {"Member", "Status"} else "right")
        maxima = _maxima(report.members)
        warning_members = {warning.member_login.casefold() for warning in report.warnings}
        for member in report.members:
            values: list[Text] = [Text(member.member_login)]
            totals = member.activity.totals if member.activity else None
            for _, field in columns[1:-1]:
                if field is None:
                    continue
                number = getattr(totals, field, 0) if totals else 0
                values.append(_value_text(number, top=number > 0 and number == maxima[field]))
            warning = member.member_login.casefold() in warning_members
            label = "⚠ warning" if warning else ("failed" if member.activity is None else "ok")
            values.append(Text(label, style="yellow" if warning else "green"))
            table.add_row(*values)
        self.console.print(table)
        self._warnings(report.warnings)

    def _warnings(self, warnings: list[Any]) -> None:
        if not warnings:
            return
        def field(warning: Any, name: str, default: Any = "") -> Any:
            return warning.get(name, default) if isinstance(warning, dict) else getattr(
                warning, name, default
            )

        lines = []
        for warning in warnings:
            member = field(warning, "member_login")
            lines.append(
                f"• {member} {field(warning, 'repository')} / {field(warning, 'source')} "
                f"({field(warning, 'code', 0)}): {field(warning, 'message')}".strip()
            )
        self.console.print(Panel("\n".join(lines), title="Warnings", border_style="yellow"))

    def _plain_model(self, value: BaseModel) -> None:
        print(json.dumps(value.model_dump(mode="json"), indent=2), file=self.stream)

    def _plain_team(self, report: TeamActivityReport) -> None:
        print(f"Team: {report.team_name} | Period: {report.period}", file=self.stream)
        print("Member\tCommits\tAdded\tDeleted\tPRs\tReviews\tRuns\tStatus", file=self.stream)
        for member in report.members:
            totals = member.activity.totals if member.activity else None
            numbers = [
                getattr(totals, field, 0) if totals else 0
                for field in (
                    "commits", "lines_added", "lines_deleted", "pull_requests_opened",
                    "reviews_submitted", "workflow_runs",
                )
            ]
            print(
                "\t".join(
                    [member.member_login, *(str(value) for value in numbers), member.cache_status]
                ),
                file=self.stream,
            )


def _total_rows(totals: Any) -> list[tuple[str, int]]:
    return [
        ("Commits", totals.commits),
        ("Lines added", totals.lines_added),
        ("Lines deleted", totals.lines_deleted),
        ("Lines changed", totals.lines_changed),
        ("Pull requests", totals.pull_requests_opened),
        ("Merged PRs", totals.pull_requests_merged),
        ("Reviews", totals.reviews_submitted),
        ("Workflow runs", totals.workflow_runs),
    ]


def _value_text(value: int, *, top: bool = False) -> Text:
    style = "bold green" if top else ("dim" if value == 0 else "")
    return Text(str(value), style=style)


def _maxima(members: list[TeamMemberActivity]) -> dict[str, int]:
    fields = (
        "commits", "lines_added", "lines_deleted", "pull_requests_opened",
        "reviews_submitted", "workflow_runs",
    )
    return {
        field: max(
            (getattr(member.activity.totals, field) for member in members if member.activity),
            default=0,
        )
        for field in fields
    }


def _csv_for(value: BaseModel) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    if isinstance(value, TeamActivityReport):
        writer.writerow(
            ["team", "period", "member", "cache_status", "commits", "lines_added",
             "lines_deleted", "lines_changed", "pull_requests_opened", "pull_requests_merged",
             "reviews_submitted", "workflow_runs", "complete"]
        )
        for member in value.members:
            totals = member.activity.totals if member.activity else None
            writer.writerow(
                [value.team_name, value.period, member.member_login, member.cache_status,
                 *(getattr(totals, field, 0) for field in totals.model_fields),
                 bool(member.activity and member.activity.complete)]
                if totals
                else [value.team_name, value.period, member.member_login, member.cache_status,
                      0, 0, 0, 0, 0, 0, 0, 0, False]
            )
    elif isinstance(value, MemberGitActivityResult):
        writer.writerow(["member", "period", "metric", "value", "cache_status", "complete"])
        for label, amount in _total_rows(value.activity.totals):
            writer.writerow(
                [value.activity.member.login, value.activity.period, label, amount,
                 value.cache_status, value.activity.complete]
            )
    elif isinstance(value, MemberLinesAddedResult):
        writer.writerow(
            ["member", "period", "commits_counted", "lines_added", "repositories_counted",
             "cache_status", "complete"]
        )
        stats = value.stats
        writer.writerow(
            [stats.member.login, stats.period, stats.commits_counted, stats.lines_added,
             stats.repositories_counted, value.cache_status, stats.complete]
        )
    else:
        writer.writerow(["json"])
        writer.writerow([json.dumps(value.model_dump(mode="json"))])
    return buffer.getvalue()
