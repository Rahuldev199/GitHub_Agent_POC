"""Member identity and line-statistics domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GitHubMember(BaseModel):
    id: int
    login: str


class MemberLinesAdded(BaseModel):
    member: GitHubMember
    period: str
    scope: str
    repositories_counted: int = Field(ge=0)
    commits_counted: int = Field(ge=0)
    lines_added: int = Field(ge=0)
    complete: bool = True
    warnings: list[dict[str, int | str]] = Field(default_factory=list)
    generated_at: datetime
    data_as_of: datetime
    status: Literal["current", "final"]
    definitions_version: str = "lines-added-v1"


class MemberLinesAddedResult(BaseModel):
    cache_status: Literal["hit", "miss", "refreshed"]
    stats: MemberLinesAdded
