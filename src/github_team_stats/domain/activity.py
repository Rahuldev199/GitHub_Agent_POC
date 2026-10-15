"""Read-only GitHub activity domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from github_team_stats.domain.member import GitHubMember


class CommitActivity(BaseModel):
    repository: str
    sha: str
    message: str
    url: str
    authored_at: datetime
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changed_lines: int = Field(ge=0)
    files_changed: int = Field(ge=0)


class PullRequestActivity(BaseModel):
    repository: str
    number: int
    title: str
    url: str
    state: str
    draft: bool
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None = None
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changed_files: int = Field(ge=0)


class ReviewActivity(BaseModel):
    repository: str
    pull_number: int
    pull_title: str
    state: str
    url: str
    submitted_at: datetime


class WorkflowRunActivity(BaseModel):
    repository: str
    run_id: int
    name: str
    title: str
    event: str
    status: str
    conclusion: str | None = None
    branch: str | None = None
    url: str
    created_at: datetime
    updated_at: datetime


class ActivityTotals(BaseModel):
    commits: int = Field(ge=0)
    lines_added: int = Field(ge=0)
    lines_deleted: int = Field(ge=0)
    lines_changed: int = Field(ge=0)
    pull_requests_opened: int = Field(ge=0)
    pull_requests_merged: int = Field(ge=0)
    reviews_submitted: int = Field(ge=0)
    workflow_runs: int = Field(ge=0)


class ActivityWarning(BaseModel):
    repository: str
    source: str
    code: int
    message: str


class MemberGitActivity(BaseModel):
    member: GitHubMember
    period: str
    scope: str
    repositories_counted: int = Field(ge=0)
    totals: ActivityTotals
    commits: list[CommitActivity]
    pull_requests: list[PullRequestActivity]
    reviews: list[ReviewActivity]
    workflow_runs: list[WorkflowRunActivity]
    details_truncated: dict[str, bool]
    complete: bool = True
    warnings: list[ActivityWarning] = Field(default_factory=list)
    generated_at: datetime
    data_as_of: datetime
    status: Literal["current", "final"]
    definitions_version: str = "member-git-activity-v1"


class MemberGitActivityResult(BaseModel):
    cache_status: Literal["hit", "miss", "refreshed"]
    activity: MemberGitActivity
