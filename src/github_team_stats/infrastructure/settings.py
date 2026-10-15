"""Validated bootstrap settings and credential resolution."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from github_team_stats.infrastructure.credentials import Credential, load_stored_token

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CONFIG_PATH = (
    Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    / "github-member-activity"
    / "config"
)


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or user config."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del dotenv_settings
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=CONFIG_PATH),
            file_secret_settings,
        )

    github_token: SecretStr | None = None
    gh_token: SecretStr | None = None
    allow_github_enterprise: bool = False
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2022-11-28"
    github_concurrency: int = Field(default=4, ge=1, le=16)
    github_max_retries: int = Field(default=3, ge=0, le=8)
    github_rate_limit_warning_threshold: int = Field(default=50, ge=0)
    github_organization: str | None = None
    github_repositories_json: str = "[]"

    cache_backend: Literal["sqlite", "mongodb"] = "mongodb"
    sqlite_path: Path | None = None
    mongodb_uri: SecretStr = SecretStr("mongodb://localhost:27017")
    mongodb_database: str = "github_member_stats"
    cache_ttl_seconds: int = Field(default=3600, ge=60)
    activity_detail_limit: int = Field(default=200, ge=1, le=1000)
    team_member_concurrency: int = Field(default=4, ge=1, le=16)
    audit_enabled: bool = True
    audit_retention_days: int = Field(default=30, ge=1, le=3650)
    audit_include_user_messages: bool = True
    audit_include_assistant_responses: bool = True

    copilot_github_token: SecretStr | None = None
    copilot_model: str = "gpt-5"

    @field_validator("github_organization")
    @classmethod
    def normalize_organization(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        if normalized and not _OWNER_RE.fullmatch(normalized):
            raise ValueError("GITHUB_ORGANIZATION is not a valid GitHub organization login")
        return normalized or None

    @field_validator("github_repositories_json")
    @classmethod
    def validate_repositories_json(cls, value: str) -> str:
        repositories = json.loads(value)
        if not isinstance(repositories, list):
            raise ValueError("GITHUB_REPOSITORIES_JSON must be a JSON array")
        for repository in repositories:
            if not isinstance(repository, str) or repository.count("/") != 1:
                raise ValueError(f"Invalid repository {repository!r}; expected owner/name")
            owner, name = repository.split("/", 1)
            if not _OWNER_RE.fullmatch(owner) or not _REPOSITORY_RE.fullmatch(name):
                raise ValueError(f"Invalid GitHub repository {repository!r}")
        return value

    @model_validator(mode="after")
    def validate_repository_scope(self) -> Settings:
        parsed_api_url = urlparse(self.github_api_url)
        if parsed_api_url.scheme != "https" or not parsed_api_url.hostname:
            raise ValueError("GITHUB_API_URL must be an absolute HTTPS URL")
        if (
            parsed_api_url.hostname.casefold() != "api.github.com"
            and not self.allow_github_enterprise
        ):
            raise ValueError(
                "GITHUB_API_URL host must be api.github.com unless ALLOW_GITHUB_ENTERPRISE=true"
            )
        if self.github_organization and self.repositories:
            raise ValueError(
                "Set only one repository scope: GITHUB_ORGANIZATION or GITHUB_REPOSITORIES_JSON"
            )
        return self

    @property
    def repositories(self) -> list[str]:
        return list(dict.fromkeys(json.loads(self.github_repositories_json)))

    @property
    def scope_key(self) -> str:
        if self.github_organization:
            return f"org:{self.github_organization.casefold()}"
        if not self.repositories:
            raise ValueError(
                "MongoDB application_config must set github_organization or "
                "github_repositories_json"
            )
        joined = ",".join(sorted(repository.casefold() for repository in self.repositories))
        return f"repos:{joined}"

    @property
    def resolved_sqlite_path(self) -> Path:
        if self.sqlite_path is not None:
            return self.sqlite_path.expanduser().resolve()
        local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local_app_data / "github-member-activity" / "cache.sqlite3"


def resolve_github_credential(settings: Settings) -> Credential:
    """Use an environment/config token, then Windows Credential Manager."""

    explicit = settings.github_token or settings.gh_token
    if explicit:
        source = "GITHUB_TOKEN" if settings.github_token else "GH_TOKEN"
        return Credential(explicit.get_secret_value(), source)

    stored = load_stored_token()
    if stored:
        return Credential(stored, "Windows Credential Manager")

    raise ValueError(
        "No GitHub credential found. Run 'github-member-activity auth setup' or set GITHUB_TOKEN."
    )


def resolve_github_token(settings: Settings) -> str:
    return resolve_github_credential(settings).token


def resolve_copilot_token(settings: Settings, github_token: str) -> str:
    """Use a dedicated Copilot token when provided, otherwise reuse GitHub auth."""

    if settings.copilot_github_token:
        explicit = settings.copilot_github_token.get_secret_value().strip()
        if explicit:
            return explicit
    return github_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
