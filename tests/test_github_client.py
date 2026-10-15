import json

import httpx
import pytest

from github_team_stats.github_client import GitHubApiError, GitHubRestClient
from github_team_stats.models import GitHubMember
from github_team_stats.periods import resolve_period


@pytest.mark.asyncio
async def test_build_member_lines_added_excludes_merges_and_other_authors() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        payloads = {
            "/repos/acme/api/commits": [
                {
                    "sha": "one",
                    "author": {"login": "rahul"},
                    "parents": [{"sha": "parent"}],
                },
                {
                    "sha": "merge",
                    "author": {"login": "rahul"},
                    "parents": [{"sha": "a"}, {"sha": "b"}],
                },
                {
                    "sha": "other",
                    "author": {"login": "someone-else"},
                    "parents": [{"sha": "parent"}],
                },
            ],
            "/repos/acme/api/commits/one": {"stats": {"additions": 125}},
        }
        return httpx.Response(200, content=json.dumps(payloads[request.url.path]))

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        stats = await client.build_member_lines_added(
            GitHubMember(id=42, login="rahul"),
            ["acme/api"],
            resolve_period("2026-09"),
            "org:acme",
        )
    finally:
        await client.aclose()

    assert stats.lines_added == 125
    assert stats.commits_counted == 1
    assert requested_paths == [
        "/repos/acme/api/commits",
        "/repos/acme/api/commits/one",
    ]


@pytest.mark.asyncio
async def test_resolve_organization_repositories_excludes_forks_and_disabled() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"full_name": "acme/api", "fork": False, "disabled": False},
                {"full_name": "acme/fork", "fork": True, "disabled": False},
                {"full_name": "acme/old", "fork": False, "disabled": True},
            ],
        )

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        repositories = await client.resolve_repositories("acme", [])
    finally:
        await client.aclose()

    assert repositories == ["acme/api"]


@pytest.mark.asyncio
async def test_build_member_activity_returns_all_read_only_categories() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        payloads = {
            "/repos/acme/api/commits": [
                {
                    "sha": "abc",
                    "author": {"login": "rahul"},
                    "parents": [{"sha": "parent"}],
                }
            ],
            "/repos/acme/api/commits/abc": {
                "sha": "abc",
                "html_url": "https://github.com/acme/api/commit/abc",
                "commit": {
                    "message": "Add endpoint",
                    "author": {"date": "2026-09-03T10:00:00Z"},
                },
                "stats": {"additions": 25, "deletions": 4},
                "files": [{"filename": "api.py"}],
            },
            "/repos/acme/api/pulls": [
                {
                    "number": 7,
                    "title": "Ship endpoint",
                    "html_url": "https://github.com/acme/api/pull/7",
                    "state": "closed",
                    "draft": False,
                    "user": {"login": "rahul"},
                    "created_at": "2026-09-04T10:00:00Z",
                    "updated_at": "2026-09-06T10:00:00Z",
                    "merged_at": "2026-09-06T10:00:00Z",
                }
            ],
            "/repos/acme/api/pulls/7": {
                "number": 7,
                "title": "Ship endpoint",
                "html_url": "https://github.com/acme/api/pull/7",
                "state": "closed",
                "draft": False,
                "additions": 25,
                "deletions": 4,
                "changed_files": 1,
            },
            "/repos/acme/api/pulls/7/reviews": [
                {
                    "user": {"login": "rahul"},
                    "state": "COMMENTED",
                    "html_url": "https://github.com/acme/api/pull/7#review-1",
                    "submitted_at": "2026-09-05T10:00:00Z",
                }
            ],
            "/repos/acme/api/actions/runs": {
                "workflow_runs": [
                    {
                        "id": 99,
                        "name": "CI",
                        "display_title": "Add endpoint",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": "main",
                        "html_url": "https://github.com/acme/api/actions/runs/99",
                        "actor": {"login": "rahul"},
                        "created_at": "2026-09-03T10:01:00Z",
                        "updated_at": "2026-09-03T10:05:00Z",
                    }
                ]
            },
        }
        return httpx.Response(200, json=payloads[request.url.path])

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        activity = await client.build_member_activity(
            GitHubMember(id=42, login="rahul"),
            ["acme/api"],
            resolve_period("2026-09"),
            "org:acme",
            200,
        )
    finally:
        await client.aclose()

    assert activity.totals.model_dump() == {
        "commits": 1,
        "lines_added": 25,
        "lines_deleted": 4,
        "lines_changed": 29,
        "pull_requests_opened": 1,
        "pull_requests_merged": 1,
        "reviews_submitted": 1,
        "workflow_runs": 1,
    }
    assert activity.commits[0].files_changed == 1
    assert activity.pull_requests[0].number == 7
    assert activity.reviews[0].state == "COMMENTED"
    assert activity.workflow_runs[0].conclusion == "success"
    assert set(methods) == {"GET"}


@pytest.mark.asyncio
async def test_repository_404_returns_incomplete_report_and_structured_warning() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/repos/acme/missing/"):
            return httpx.Response(404, json={"message": "Not Found"})
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": []})
        return httpx.Response(200, json=[])

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        activity = await client.build_member_activity(
            GitHubMember(id=42, login="rahul"),
            ["acme/missing", "acme/empty"],
            resolve_period("2026-09"),
            "org:acme",
            200,
        )
    finally:
        await client.aclose()

    assert activity.complete is False
    warning = activity.warnings[0]
    assert warning.repository == "acme/missing"
    assert warning.source == "commits"
    assert warning.code == 404
    assert "private-repository token access" in warning.message


@pytest.mark.asyncio
async def test_commit_failure_does_not_skip_pull_requests_or_actions() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested_paths.append(path)
        if path == "/repos/acme/api/commits":
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/acme/api/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 7,
                        "title": "Fix source isolation",
                        "state": "closed",
                        "draft": False,
                        "user": {"login": "rahul"},
                        "created_at": "2026-09-03T10:00:00Z",
                        "updated_at": "2026-09-04T10:00:00Z",
                        "merged_at": "2026-09-04T10:00:00Z",
                        "html_url": "https://github.com/acme/api/pull/7",
                    }
                ],
            )
        if path == "/repos/acme/api/pulls/7":
            return httpx.Response(
                200,
                json={
                    "number": 7,
                    "title": "Fix source isolation",
                    "state": "closed",
                    "draft": False,
                    "created_at": "2026-09-03T10:00:00Z",
                    "updated_at": "2026-09-04T10:00:00Z",
                    "merged_at": "2026-09-04T10:00:00Z",
                    "html_url": "https://github.com/acme/api/pull/7",
                    "additions": 10,
                    "deletions": 2,
                    "changed_files": 1,
                },
            )
        if path == "/repos/acme/api/pulls/7/reviews":
            return httpx.Response(200, json=[])
        if path == "/repos/acme/api/actions/runs":
            return httpx.Response(200, json={"workflow_runs": []})
        raise AssertionError(f"Unexpected request: {path}")

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        activity = await client.build_member_activity(
            GitHubMember(id=42, login="rahul"),
            ["acme/api"],
            resolve_period("2026-09"),
            "org:acme",
            200,
        )
    finally:
        await client.aclose()

    assert activity.complete is False
    assert activity.totals.pull_requests_opened == 1
    assert activity.totals.pull_requests_merged == 1
    assert activity.pull_requests[0].number == 7
    assert activity.warnings[0].source == "commits"
    assert "/repos/acme/api/pulls" in requested_paths
    assert "/repos/acme/api/actions/runs" in requested_paths


@pytest.mark.asyncio
async def test_auth_and_rate_limit_errors_abort_report() -> None:
    for code, headers in (
        (401, {}),
        (403, {"X-RateLimit-Remaining": "0"}),
        (429, {"Retry-After": "1"}),
    ):
        transport = httpx.MockTransport(
            lambda _request, code=code, headers=headers: httpx.Response(
                code, headers=headers, json={"message": "blocked"}
            )
        )
        client = GitHubRestClient("test-token", transport=transport, max_retries=0)
        try:
            with pytest.raises(GitHubApiError):
                await client.build_member_activity(
                    GitHubMember(id=42, login="rahul"),
                    ["acme/api"],
                    resolve_period("2026-09"),
                    "org:acme",
                    200,
                )
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_retries_and_etag_conditional_requests() -> None:
    attempts = 0
    conditional_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        conditional_headers.append(request.headers.get("if-none-match"))
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if attempts == 2:
            return httpx.Response(200, headers={"ETag": '"v1"'}, json={"login": "lead"})
        return httpx.Response(304, headers={"ETag": '"v1"'})

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        first = await client._get("/user")
        second = await client._get("/user")
    finally:
        await client.aclose()

    assert first == second == {"login": "lead"}
    assert conditional_headers == [None, None, '"v1"']


@pytest.mark.asyncio
async def test_nearly_spent_budget_has_clear_warning() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"X-RateLimit-Remaining": "4", "X-RateLimit-Reset": "123"},
            json={"login": "lead"},
        )
    )
    client = GitHubRestClient("test-token", transport=transport)
    try:
        await client._get("/user")
    finally:
        await client.aclose()
    assert client.rate_limit_warning == (
        "GitHub API budget is nearly spent: 4 requests remain; reset=123"
    )


@pytest.mark.asyncio
async def test_actions_403_is_partial_but_does_not_abort_other_activity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(403, json={"message": "Actions permission required"})
        return httpx.Response(200, json=[])

    client = GitHubRestClient("test-token", transport=httpx.MockTransport(handler))
    try:
        activity = await client.build_member_activity(
            GitHubMember(id=42, login="rahul"),
            ["acme/api"],
            resolve_period("2026-09"),
            "repos:acme/api",
            200,
        )
    finally:
        await client.aclose()

    assert activity.complete is False
    assert activity.totals.commits == 0
    assert activity.warnings[0].model_dump(exclude={"message"}) == {
        "repository": "acme/api",
        "source": "actions",
        "code": 403,
    }
