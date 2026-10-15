import httpx
import pytest

from github_team_stats.errors import AuthError, NotFound, PermissionDenied, RateLimited
from github_team_stats.github_client import GitHubRestClient


@pytest.mark.parametrize(
    ("status", "headers", "expected_type", "exit_code"),
    [
        (401, {}, AuthError, 401),
        (403, {}, PermissionDenied, 403),
        (403, {"X-RateLimit-Remaining": "0"}, RateLimited, 429),
        (404, {}, NotFound, 404),
        (429, {"Retry-After": "1"}, RateLimited, 429),
    ],
)
def test_github_status_maps_to_typed_error(
    status: int, headers: dict[str, str], expected_type: type, exit_code: int
) -> None:
    response = httpx.Response(status, headers=headers, request=httpx.Request("GET", "https://x"))
    error = GitHubRestClient._error_for_response(response, "/repos/acme/private")
    assert isinstance(error, expected_type)
    assert error.exit_code == exit_code


def test_not_found_includes_private_repository_hint() -> None:
    response = httpx.Response(404, request=httpx.Request("GET", "https://x"))
    error = GitHubRestClient._error_for_response(response, "/repos/acme/private")
    assert "private-repository token access" in str(error)
