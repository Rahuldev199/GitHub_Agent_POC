"""Authorized-team domain models."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from github_team_stats.domain.activity import ActivityTotals, MemberGitActivity

_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class TeamDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    team_key: str = Field(alias="_id", min_length=1, max_length=100)
    team_name: str = Field(min_length=1, max_length=200)
    lead_logins: list[str] = Field(min_length=1)
    members: list[str] = Field(min_length=1)
    repositories: list[str] = Field(min_length=1)
    enabled: bool = True

    @field_validator("lead_logins")
    @classmethod
    def validate_leads(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip().casefold() for value in values))
        if any(not _LOGIN_RE.fullmatch(value) for value in normalized):
            raise ValueError("Every team lead must be an exact GitHub login")
        return normalized

    @field_validator("members")
    @classmethod
    def validate_members(cls, values: list[str]) -> list[str]:
        unique: dict[str, str] = {}
        for value in values:
            login = value.strip()
            if not _LOGIN_RE.fullmatch(login):
                raise ValueError("Every team member must be an exact GitHub login")
            unique.setdefault(login.casefold(), login)
        return list(unique.values())

    @field_validator("repositories")
    @classmethod
    def validate_repositories(cls, values: list[str]) -> list[str]:
        unique: dict[str, str] = {}
        for value in values:
            repository = value.strip()
            if not _REPOSITORY_RE.fullmatch(repository):
                raise ValueError("Every team repository must use owner/name")
            unique.setdefault(repository.casefold(), repository)
        return list(unique.values())

    @property
    def scope_key(self) -> str:
        repositories = ",".join(sorted(repo.casefold() for repo in self.repositories))
        return f"repos:{repositories}"


class TeamActivityWarning(BaseModel):
    member_login: str
    repository: str
    source: str
    code: int
    message: str


class TeamMemberActivity(BaseModel):
    member_login: str
    cache_status: Literal["hit", "miss", "refreshed", "failed"]
    activity: MemberGitActivity | None = None


class TeamActivityReport(BaseModel):
    team_key: str
    team_name: str
    requester_login: str
    period: str
    scope: str
    members_requested: int = Field(ge=1)
    members_completed: int = Field(ge=0)
    totals: ActivityTotals
    members: list[TeamMemberActivity]
    complete: bool
    warnings: list[TeamActivityWarning]
    generated_at: datetime
    data_as_of: datetime
    definitions_version: str = "team-git-activity-v1"
