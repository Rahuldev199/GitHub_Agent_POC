"""Application error hierarchy shared across package layers."""

from __future__ import annotations


class AppError(RuntimeError):
    exit_code = 1
    status_code: int | None = None


class ConfigError(AppError):
    exit_code = 2


class GitHubError(AppError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        path: str | None = None,
        rate_limited: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path
        self.rate_limited = rate_limited

    @property
    def recoverable_repository_error(self) -> bool:
        return self.status_code in {403, 404} and not self.rate_limited


class AuthError(GitHubError):
    exit_code = 401


class PermissionDenied(GitHubError):
    exit_code = 403


class MemberAccessDenied(PermissionDenied):
    """The requester is not authorized to report on the selected member."""


class NotFound(GitHubError):
    exit_code = 404


class RateLimited(GitHubError):
    exit_code = 429
