"""Resilient, read-only HTTP transport for GitHub REST requests."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Self

import httpx

from github_team_stats.domain.errors import (
    AuthError,
    GitHubError,
    NotFound,
    PermissionDenied,
    RateLimited,
)

GitHubApiError = GitHubError
logger = logging.getLogger(__name__)


class GitHubHttpTransport:
    """Handle authentication, pagination, retries, ETags, and typed API errors."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        api_version: str = "2022-11-28",
        timeout: float = 30.0,
        concurrency: int = 4,
        max_retries: int = 3,
        rate_limit_warning_threshold: int = 50,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("A GitHub credential is required for GitHub requests")
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": api_version,
                "User-Agent": "github-member-activity-agent/0.3",
            },
        )
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._rate_limit_warning_threshold = rate_limit_warning_threshold
        self._etag_cache: dict[str, tuple[str, bytes]] = {}
        self.rate_limit_warning: str | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = await self._request(path, params)
        if response.status_code >= 400:
            raise self._error_for_response(response, path)
        data = response.json()
        if not isinstance(data, dict):
            raise GitHubApiError(f"Unexpected GitHub response for {path}")
        return data

    async def _pages(self, path: str, **params: Any) -> AsyncIterator[list[dict[str, Any]]]:
        page = 1
        while True:
            response = await self._request(path, {**params, "per_page": 100, "page": page})
            if response.status_code == 409 and path.endswith("/commits"):
                return
            if response.status_code >= 400:
                raise self._error_for_response(response, path)
            items = response.json()
            if not isinstance(items, list):
                raise GitHubApiError(f"Unexpected GitHub response for {path}")
            if not items:
                break
            yield items
            if len(items) < 100:
                break
            page += 1

    async def _object_pages(
        self, path: str, item_key: str, **params: Any
    ) -> AsyncIterator[list[dict[str, Any]]]:
        page = 1
        while True:
            data = await self._get(path, **params, per_page=100, page=page)
            items = data.get(item_key)
            if not isinstance(items, list):
                raise GitHubApiError(f"Unexpected GitHub response for {path}")
            if not items:
                break
            yield items
            if len(items) < 100:
                break
            page += 1

    async def _request(self, path: str, params: dict[str, Any]) -> httpx.Response:
        cache_key = f"{path}?{sorted(params.items())!r}"
        cached = self._etag_cache.get(cache_key)
        headers = {"If-None-Match": cached[0]} if cached else None
        for attempt in range(self._max_retries + 1):
            async with self._semaphore:
                response = await self._client.get(path, params=params, headers=headers)
            self._record_rate_budget(response)
            if response.status_code == 304 and cached:
                return httpx.Response(
                    200,
                    content=cached[1],
                    headers=response.headers,
                    request=response.request,
                )
            if not self._is_rate_limited(response) or attempt >= self._max_retries:
                etag = response.headers.get("etag")
                if response.status_code < 300 and etag:
                    self._etag_cache[cache_key] = (etag, response.content)
                return response
            await asyncio.sleep(self._retry_delay(response, attempt))
        return response

    def _record_rate_budget(self, response: httpx.Response) -> None:
        remaining_text = response.headers.get("x-ratelimit-remaining")
        if remaining_text is None:
            return
        try:
            remaining = int(remaining_text)
        except ValueError:
            return
        if remaining <= self._rate_limit_warning_threshold:
            reset = response.headers.get("x-ratelimit-reset", "unknown")
            self.rate_limit_warning = (
                f"GitHub API budget is nearly spent: {remaining} requests remain; reset={reset}"
            )
            logger.warning(self.rate_limit_warning)

    @staticmethod
    def _is_rate_limited(response: httpx.Response) -> bool:
        body = response.text.casefold()
        return response.status_code == 429 or (
            response.status_code == 403
            and (
                response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
                or "secondary rate limit" in body
            )
        )

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        reset = response.headers.get("x-ratelimit-reset")
        if reset:
            try:
                return max(float(reset) - time.time(), 0.0)
            except ValueError:
                pass
        return float(min(2**attempt, 60))

    @staticmethod
    def _error_for_response(response: httpx.Response, path: str) -> GitHubApiError:
        request_id = response.headers.get("x-github-request-id", "unknown")
        rate_limited = GitHubHttpTransport._is_rate_limited(response)
        message = (
            f"GitHub API returned {response.status_code} for {path} (request id: {request_id})"
        )
        error_type: type[GitHubError]
        if response.status_code == 401:
            error_type = AuthError
        elif rate_limited:
            error_type = RateLimited
        elif response.status_code == 403:
            error_type = PermissionDenied
        elif response.status_code == 404:
            error_type = NotFound
            message += "; verify the repository name and private-repository token access"
        else:
            error_type = GitHubError
        return error_type(
            message,
            status_code=response.status_code,
            path=path,
            rate_limited=rate_limited,
        )
