"""FastAPI dashboard backed by the application's read-only services."""

from __future__ import annotations

import re
import socket
import threading
import webbrowser
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Any, Literal

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from github_team_stats.bootstrap import Application
from github_team_stats.domain.periods import Period, resolve_period
from github_team_stats.domain.team import TeamActivityReport
from github_team_stats.presentation.web.exports import csv_export, html_export, xlsx_export
from github_team_stats.presentation.web.security import LocalSecurityMiddleware, LocalSession

_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)


class AvatarCache:
    def __init__(self, maximum: int = 200) -> None:
        self._maximum = maximum
        self._items: OrderedDict[str, tuple[bytes, str]] = OrderedDict()

    async def get(self, login: str) -> tuple[bytes, str] | None:
        key = login.casefold()
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            response = await client.get(f"https://github.com/{login}.png?size=96")
        if response.status_code != 200 or len(response.content) > 2_000_000:
            return None
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return None
        self._items[key] = (response.content, content_type)
        while len(self._items) > self._maximum:
            self._items.popitem(last=False)
        return self._items[key]


def create_web_app(application: Application, session: LocalSession) -> FastAPI:
    """Create an authenticated local UI. GitHub credentials stay server-side."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await application.close()

    api = FastAPI(title="GitHub Member Activity", docs_url=None, redoc_url=None, lifespan=lifespan)
    api.add_middleware(LocalSecurityMiddleware, session=session)
    static_dir = files("github_team_stats.presentation.web").joinpath("static")
    api.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    avatars = AvatarCache()

    @api.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(str(static_dir.joinpath("index.html")))

    @api.get("/api/teams")
    async def teams() -> dict[str, Any]:
        login = await application.github.get_authenticated_login()
        definitions = application.store.list_teams_for_lead(login)
        return {
            "requester": login,
            "teams": [
                {"key": team.team_key, "name": team.team_name, "members": team.members}
                for team in definitions
            ],
        }

    @api.get("/api/dashboard")
    async def dashboard(
        period: str = "this month", team: str | None = None, refresh: bool = False,
        months: int = Query(6, ge=1, le=12),
    ) -> dict[str, Any]:
        report = await _report(application, period, team, refresh)
        trend = []
        current = resolve_period(report.period)
        for item in _previous_periods(current, months):
            historical = await _report(application, item.key, team, False)
            trend.append({"period": item.key, **historical.totals.model_dump()})
        return {"report": report.model_dump(mode="json"), "charts": _chart_data(report, trend)}

    @api.post("/api/chat")
    async def chat(payload: ChatRequest) -> dict[str, str]:
        return {"answer": await application.runtime.ask(payload.message.strip())}

    @api.get("/api/avatar/{login}")
    async def avatar(login: str) -> Response:
        if not _LOGIN.fullmatch(login):
            raise HTTPException(404, "Invalid GitHub login")
        try:
            image = await avatars.get(login)
        except httpx.HTTPError:
            image = None
        if image is None:
            raise HTTPException(404, "Avatar unavailable")
        body, content_type = image
        return Response(
            body, media_type=content_type,
            headers={"Cache-Control": "private,max-age=86400"},
        )

    @api.get("/api/export/{kind}")
    async def export(
        kind: Literal["csv", "xlsx", "html"], period: str = "this month",
        team: str | None = None,
    ) -> Response:
        report = await _report(application, period, team, False)
        builders = {"csv": csv_export, "xlsx": xlsx_export, "html": html_export}
        media = {
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "html": "text/html; charset=utf-8",
        }
        return Response(
            builders[kind](report), media_type=media[kind],
            headers={"Content-Disposition": f'attachment; filename="team-{report.period}.{kind}"'},
        )

    return api


async def _report(
    application: Application, period: str, team: str | None, refresh: bool,
) -> TeamActivityReport:
    return await application.team_activity_service.get_team_activity(
        period, team_name=team, force_refresh=refresh
    )


def _previous_periods(period: Period, count: int) -> list[Period]:
    result: list[Period] = []
    year, month = period.start.year, period.start.month
    for offset in range(count - 1, -1, -1):
        index = year * 12 + month - 1 - offset
        result.append(resolve_period(f"{index // 12:04d}-{index % 12 + 1:02d}"))
    return result


def _chart_data(report: TeamActivityReport, trend: list[dict[str, Any]]) -> dict[str, Any]:
    members = []
    days: dict[str, int] = {}
    pr_states = {"open": 0, "closed": 0, "merged": 0}
    for item in report.members:
        activity = item.activity
        members.append(
            {"login": item.member_login, "commits": activity.totals.commits if activity else 0}
        )
        if not activity:
            continue
        for commit in activity.commits:
            day = commit.authored_at.date().isoformat()
            days[day] = days.get(day, 0) + 1
        for pull in activity.pull_requests:
            day = pull.created_at.date().isoformat()
            days[day] = days.get(day, 0) + 1
            state = "merged" if pull.merged_at else pull.state.casefold()
            if state in pr_states:
                pr_states[state] += 1
        for review in activity.reviews:
            day = review.submitted_at.date().isoformat()
            days[day] = days.get(day, 0) + 1
        for workflow in activity.workflow_runs:
            day = workflow.created_at.date().isoformat()
            days[day] = days.get(day, 0) + 1
    return {
        "commits_by_member": members,
        "pr_states": pr_states,
        "daily_activity": [{"date": day, "count": value} for day, value in sorted(days.items())],
        "trend": trend,
    }


def run_local_ui(application: Application) -> None:
    """Bind only to loopback, open a one-time URL, and run until interrupted."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    session = LocalSession(origin=origin)
    app = create_web_app(application, session)
    url = f"{origin}/?session={session.bootstrap_token}"
    print(f"Opening read-only dashboard at {origin}")
    print("Press Ctrl+C to stop it.")
    threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uvicorn.Server(config).run(sockets=[listener])
