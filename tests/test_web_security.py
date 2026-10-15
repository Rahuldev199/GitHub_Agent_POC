from __future__ import annotations

from typing import Any, cast

import httpx
import pytest

from github_team_stats.presentation.web.security import LocalSession
from github_team_stats.presentation.web.server import create_web_app


class Runtime:
    async def ask(self, message: str) -> str:
        return f"answer: {message}"


class FakeApplication:
    runtime = Runtime()

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_one_time_bootstrap_and_origin_protection() -> None:
    session = LocalSession(origin="http://127.0.0.1:8765")
    app = create_web_app(cast(Any, FakeApplication()), session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=session.origin, follow_redirects=False
    ) as client:
        first = await client.get(f"/?session={session.bootstrap_token}")
        assert first.status_code == 303
        assert "httponly" in first.headers["set-cookie"].casefold()
        assert session.bootstrap_token not in first.headers["location"]
        async with httpx.AsyncClient(
            transport=transport, base_url=session.origin, follow_redirects=False
        ) as second_client:
            reused = await second_client.get(f"/?session={session.bootstrap_token}")
        assert reused.status_code == 401
        denied = await client.post("/api/chat", json={"message": "hello"})
        assert denied.status_code == 403
        allowed = await client.post(
            "/api/chat", json={"message": "hello"}, headers={"Origin": session.origin}
        )
        assert allowed.json() == {"answer": "answer: hello"}


@pytest.mark.asyncio
async def test_non_loopback_host_is_rejected() -> None:
    session = LocalSession(origin="http://127.0.0.1:8765")
    app = create_web_app(cast(Any, FakeApplication()), session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8765"
    ) as client:
        assert (await client.get("/")).status_code == 403


def test_assets_do_not_use_a_cdn() -> None:
    from importlib.resources import files

    root = files("github_team_stats.presentation.web").joinpath("static")
    for name in ("index.html", "app.css", "chat-progress.css", "app.js"):
        text = root.joinpath(name).read_text(encoding="utf-8")
        assert "cdn." not in text.casefold()


def test_chat_assets_expose_accessible_working_states() -> None:
    from importlib.resources import files

    root = files("github_team_stats.presentation.web").joinpath("static")
    page = root.joinpath("index.html").read_text(encoding="utf-8")
    script = root.joinpath("app.js").read_text(encoding="utf-8")
    assert 'aria-live="polite"' in page
    assert "Analyzing your request" in script
    assert "Checking available GitHub activity" in script
    assert "Preparing the response" in script
    assert "chatPending" in script
