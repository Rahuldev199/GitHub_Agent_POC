"""Read-only GitHub activity collection client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from github_team_stats.domain.activity import (
    ActivityTotals,
    ActivityWarning,
    CommitActivity,
    MemberGitActivity,
    PullRequestActivity,
    ReviewActivity,
    WorkflowRunActivity,
)
from github_team_stats.domain.member import GitHubMember, MemberLinesAdded
from github_team_stats.domain.periods import Period
from github_team_stats.infrastructure.github.transport import GitHubApiError, GitHubHttpTransport


class GitHubRestClient(GitHubHttpTransport):
    """Read-only GitHub REST client for member development activity."""

    _authenticated_login: str | None = None

    async def get_member(self, login: str) -> GitHubMember:
        normalized = login.strip()
        if not normalized:
            raise ValueError("Member login cannot be empty")
        data = await self._get(f"/users/{normalized}")
        if data.get("type") == "Bot" or str(data.get("login", "")).endswith("[bot]"):
            raise ValueError("Bot accounts are not supported")
        return GitHubMember(id=int(data["id"]), login=str(data["login"]))

    async def get_authenticated_login(self) -> str:
        if self._authenticated_login is None:
            data = await self._get("/user")
            login = str(data.get("login") or "").strip()
            if not login:
                raise GitHubApiError("Authenticated GitHub user response did not include a login")
            self._authenticated_login = login
        return self._authenticated_login

    async def resolve_repositories(
        self, organization: str | None, configured_repositories: list[str]
    ) -> list[str]:
        if configured_repositories:
            return sorted(set(configured_repositories), key=str.casefold)
        if not organization:
            raise ValueError("A GitHub organization or repository list is required")

        repositories: list[str] = []
        async for page in self._pages(
            f"/orgs/{organization}/repos", type="all", sort="full_name", direction="asc"
        ):
            repositories.extend(
                str(repository["full_name"])
                for repository in page
                if not repository.get("fork", False) and not repository.get("disabled", False)
            )
        resolved = sorted(set(repositories), key=str.casefold)
        if not resolved:
            raise GitHubApiError(
                f"No readable, non-fork repositories found for organization {organization!r}"
            )
        return resolved

    async def build_member_lines_added(
        self,
        member: GitHubMember,
        repositories: list[str],
        period: Period,
        scope: str,
    ) -> MemberLinesAdded:
        lines_added = 0
        commits_counted = 0
        warnings: list[dict[str, int | str]] = []
        inclusive_until = period.end - timedelta(microseconds=1)

        for repository in repositories:
            owner, name = repository.split("/", 1)
            repo_path = f"/repos/{owner}/{name}"
            try:
                async for commits in self._pages(
                    f"{repo_path}/commits",
                    author=member.login,
                    since=period.start.isoformat(),
                    until=inclusive_until.isoformat(),
                ):
                    for commit in commits:
                        if len(commit.get("parents", [])) > 1:
                            continue
                        author_login = str((commit.get("author") or {}).get("login", ""))
                        if author_login.casefold() != member.login.casefold():
                            continue
                        detail = await self._get(f"{repo_path}/commits/{commit['sha']}")
                        additions = int((detail.get("stats") or {}).get("additions", 0))
                        lines_added += max(additions, 0)
                        commits_counted += 1
            except GitHubApiError as error:
                if not error.recoverable_repository_error:
                    raise
                warnings.append(
                    {
                        "repository": repository,
                        "source": "commits",
                        "code": error.status_code or 0,
                        "message": str(error),
                    }
                )

        now = datetime.now(UTC)
        if self.rate_limit_warning:
            warnings.append(
                {
                    "repository": "*",
                    "source": "rate_limit",
                    "code": 200,
                    "message": self.rate_limit_warning,
                }
            )
        return MemberLinesAdded(
            member=member,
            period=period.key,
            scope=scope,
            repositories_counted=len(repositories),
            commits_counted=commits_counted,
            lines_added=lines_added,
            complete=not any(int(warning["code"]) >= 400 for warning in warnings),
            warnings=warnings,
            generated_at=now,
            data_as_of=now,
            status="current" if period.is_current or warnings else "final",
        )

    async def build_member_activity(
        self,
        member: GitHubMember,
        repositories: list[str],
        period: Period,
        scope: str,
        detail_limit: int,
    ) -> MemberGitActivity:
        commits: list[CommitActivity] = []
        pull_requests: list[PullRequestActivity] = []
        reviews: list[ReviewActivity] = []
        workflow_runs: list[WorkflowRunActivity] = []
        warnings: list[ActivityWarning] = []
        counts = {
            "commits": 0,
            "lines_added": 0,
            "lines_deleted": 0,
            "lines_changed": 0,
            "pull_requests_opened": 0,
            "pull_requests_merged": 0,
            "reviews_submitted": 0,
            "workflow_runs": 0,
        }
        truncated = {
            "commits": False,
            "pull_requests": False,
            "reviews": False,
            "workflow_runs": False,
        }
        inclusive_until = period.end - timedelta(microseconds=1)

        for repository in repositories:
            owner, name = repository.split("/", 1)
            repo_path = f"/repos/{owner}/{name}"
            try:
                async for commit_page in self._pages(
                    f"{repo_path}/commits",
                    author=member.login,
                    since=period.start.isoformat(),
                    until=inclusive_until.isoformat(),
                ):
                    for summary in commit_page:
                        if len(summary.get("parents", [])) > 1:
                            continue
                        author_login = str((summary.get("author") or {}).get("login", ""))
                        if author_login.casefold() != member.login.casefold():
                            continue
                        detail = await self._get(f"{repo_path}/commits/{summary['sha']}")
                        stats = detail.get("stats") or {}
                        additions = max(int(stats.get("additions", 0)), 0)
                        deletions = max(int(stats.get("deletions", 0)), 0)
                        counts["commits"] += 1
                        counts["lines_added"] += additions
                        counts["lines_deleted"] += deletions
                        counts["lines_changed"] += additions + deletions
                        if len(commits) < detail_limit:
                            commit_data = detail.get("commit") or summary.get("commit") or {}
                            author_data = commit_data.get("author") or {}
                            files = detail.get("files") or []
                            commits.append(
                                CommitActivity(
                                    repository=repository,
                                    sha=str(detail.get("sha") or summary["sha"]),
                                    message=str(commit_data.get("message") or ""),
                                    url=str(
                                        detail.get("html_url") or summary.get("html_url") or ""
                                    ),
                                    authored_at=_parse_datetime(author_data.get("date")),
                                    additions=additions,
                                    deletions=deletions,
                                    changed_lines=additions + deletions,
                                    files_changed=len(files),
                                )
                            )
                        else:
                            truncated["commits"] = True

            except GitHubApiError as error:
                if not error.recoverable_repository_error:
                    raise
                warnings.append(
                    ActivityWarning(
                        repository=repository,
                        source="commits",
                        code=error.status_code or 0,
                        message=str(error),
                    )
                )

            try:
                stop_pulls = False
                async for pull_page in self._pages(
                    f"{repo_path}/pulls", state="all", sort="updated", direction="desc"
                ):
                    for pull in pull_page:
                        updated_at = _parse_datetime(pull.get("updated_at"))
                        if updated_at < period.start:
                            stop_pulls = True
                            break
                        created_at = _parse_datetime(pull.get("created_at"))
                        if created_at >= period.end:
                            continue
                        pull_number = int(pull["number"])
                        author_login = str((pull.get("user") or {}).get("login", ""))
                        merged_at = _optional_datetime(pull.get("merged_at"))
                        opened_in_period = period.start <= created_at < period.end
                        merged_in_period = bool(
                            merged_at and period.start <= merged_at < period.end
                        )
                        authored_by_member = author_login.casefold() == member.login.casefold()
                        if authored_by_member and (opened_in_period or merged_in_period):
                            counts["pull_requests_opened"] += int(opened_in_period)
                            counts["pull_requests_merged"] += int(merged_in_period)
                            detail = await self._get(f"{repo_path}/pulls/{pull_number}")
                            if len(pull_requests) < detail_limit:
                                pull_requests.append(
                                    PullRequestActivity(
                                        repository=repository,
                                        number=pull_number,
                                        title=str(detail.get("title") or pull.get("title") or ""),
                                        url=str(
                                            detail.get("html_url") or pull.get("html_url") or ""
                                        ),
                                        state=str(detail.get("state") or pull.get("state") or ""),
                                        draft=bool(detail.get("draft", pull.get("draft", False))),
                                        created_at=created_at,
                                        updated_at=updated_at,
                                        merged_at=merged_at,
                                        additions=max(int(detail.get("additions", 0)), 0),
                                        deletions=max(int(detail.get("deletions", 0)), 0),
                                        changed_files=max(int(detail.get("changed_files", 0)), 0),
                                    )
                                )
                            else:
                                truncated["pull_requests"] = True

                        async for review_page in self._pages(
                            f"{repo_path}/pulls/{pull_number}/reviews"
                        ):
                            for review in review_page:
                                reviewer = str((review.get("user") or {}).get("login", ""))
                                submitted_at = _optional_datetime(review.get("submitted_at"))
                                if (
                                    reviewer.casefold() != member.login.casefold()
                                    or submitted_at is None
                                    or not period.start <= submitted_at < period.end
                                ):
                                    continue
                                counts["reviews_submitted"] += 1
                                if len(reviews) < detail_limit:
                                    reviews.append(
                                        ReviewActivity(
                                            repository=repository,
                                            pull_number=pull_number,
                                            pull_title=str(pull.get("title") or ""),
                                            state=str(review.get("state") or ""),
                                            url=str(
                                                review.get("html_url") or pull.get("html_url") or ""
                                            ),
                                            submitted_at=submitted_at,
                                        )
                                    )
                                else:
                                    truncated["reviews"] = True
                    if stop_pulls:
                        break
            except GitHubApiError as error:
                if not error.recoverable_repository_error:
                    raise
                warnings.append(
                    ActivityWarning(
                        repository=repository,
                        source=_source_for_path(error.path),
                        code=error.status_code or 0,
                        message=str(error),
                    )
                )

            try:
                created_range = (
                    f"{period.start.date().isoformat()}..{inclusive_until.date().isoformat()}"
                )
                async for run_page in self._object_pages(
                    f"{repo_path}/actions/runs",
                    "workflow_runs",
                    actor=member.login,
                    created=created_range,
                ):
                    for run in run_page:
                        actor = str((run.get("actor") or {}).get("login", ""))
                        created_at = _parse_datetime(run.get("created_at"))
                        if (
                            actor.casefold() != member.login.casefold()
                            or not period.start <= created_at < period.end
                        ):
                            continue
                        counts["workflow_runs"] += 1
                        if len(workflow_runs) < detail_limit:
                            workflow_runs.append(
                                WorkflowRunActivity(
                                    repository=repository,
                                    run_id=int(run["id"]),
                                    name=str(run.get("name") or ""),
                                    title=str(run.get("display_title") or ""),
                                    event=str(run.get("event") or ""),
                                    status=str(run.get("status") or ""),
                                    conclusion=(
                                        str(run["conclusion"])
                                        if run.get("conclusion") is not None
                                        else None
                                    ),
                                    branch=(
                                        str(run["head_branch"])
                                        if run.get("head_branch") is not None
                                        else None
                                    ),
                                    url=str(run.get("html_url") or ""),
                                    created_at=created_at,
                                    updated_at=_parse_datetime(run.get("updated_at")),
                                )
                            )
                        else:
                            truncated["workflow_runs"] = True
            except GitHubApiError as error:
                if not error.recoverable_repository_error:
                    raise
                warnings.append(
                    ActivityWarning(
                        repository=repository,
                        source="actions",
                        code=error.status_code or 0,
                        message=str(error),
                    )
                )

        now = datetime.now(UTC)
        if self.rate_limit_warning:
            warnings.append(
                ActivityWarning(
                    repository="*",
                    source="rate_limit",
                    code=200,
                    message=self.rate_limit_warning,
                )
            )
        return MemberGitActivity(
            member=member,
            period=period.key,
            scope=scope,
            repositories_counted=len(repositories),
            totals=ActivityTotals(**counts),
            commits=commits,
            pull_requests=pull_requests,
            reviews=reviews,
            workflow_runs=workflow_runs,
            details_truncated=truncated,
            complete=not any(warning.code >= 400 for warning in warnings),
            warnings=warnings,
            generated_at=now,
            data_as_of=now,
            status="current" if period.is_current or warnings else "final",
        )


def _parse_datetime(value: Any) -> datetime:
    if not value or not isinstance(value, str):
        raise GitHubApiError("GitHub response contained a missing or invalid timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _optional_datetime(value: Any) -> datetime | None:
    return _parse_datetime(value) if value else None


def _source_for_path(path: str | None) -> str:
    if not path:
        return "repository"
    if "/commits" in path:
        return "commits"
    if "/reviews" in path:
        return "reviews"
    if "/pulls" in path:
        return "pull_requests"
    if "/actions/" in path:
        return "actions"
    return "repository"
