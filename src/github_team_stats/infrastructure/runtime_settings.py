"""MongoDB-backed non-secret runtime configuration."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from github_team_stats.domain.errors import ConfigError
from github_team_stats.infrastructure.settings import Settings

CONFIG_DOCUMENT_ID = "default"
CONFIG_COLLECTION = "application_config"
RUNTIME_CONFIG_FIELDS = (
    "github_organization",
    "allow_github_enterprise",
    "github_api_url",
    "github_api_version",
    "github_concurrency",
    "github_max_retries",
    "github_rate_limit_warning_threshold",
    "cache_ttl_seconds",
    "activity_detail_limit",
    "team_member_concurrency",
    "audit_enabled",
    "audit_retention_days",
    "audit_include_user_messages",
    "audit_include_assistant_responses",
    "copilot_model",
)


class ConfigurationCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def insert_one(self, document: dict[str, Any]) -> Any: ...


def _has_repository_scope(settings: Settings) -> bool:
    return bool(settings.github_organization or settings.repositories)


def _seed_document(settings: Settings) -> dict[str, Any]:
    if not _has_repository_scope(settings):
        raise ConfigError(
            "MongoDB application_config is missing. For the first run only, set "
            "GITHUB_ORGANIZATION or GITHUB_REPOSITORIES_JSON in the bootstrap config; "
            "the application will seed MongoDB and use it thereafter."
        )
    values = settings.model_dump(mode="python")
    document = {
        "_id": CONFIG_DOCUMENT_ID,
        "schema_version": 1,
        "github_repositories": settings.repositories,
    }
    document.update({field: values[field] for field in RUNTIME_CONFIG_FIELDS})
    return document


def load_or_seed_runtime_settings(
    bootstrap: Settings, collection: ConfigurationCollection
) -> Settings:
    document = collection.find_one({"_id": CONFIG_DOCUMENT_ID})
    if document is None:
        collection.insert_one(_seed_document(bootstrap))
        return bootstrap

    values = bootstrap.model_dump(mode="python")
    values.update({field: document[field] for field in RUNTIME_CONFIG_FIELDS if field in document})
    repositories = document.get("github_repositories")
    if repositories is not None:
        values["github_repositories_json"] = json.dumps(repositories)
    elif "github_repositories_json" in document:
        values["github_repositories_json"] = document["github_repositories_json"]
    try:
        settings = Settings.model_validate(values)
    except ValidationError as error:
        raise ConfigError(f"Invalid MongoDB application_config: {error}") from error
    if not _has_repository_scope(settings):
        raise ConfigError(
            "MongoDB application_config must set github_organization or github_repositories_json"
        )
    return settings


def resolve_runtime_settings(bootstrap: Settings) -> Settings:
    if bootstrap.cache_backend != "mongodb":
        if not _has_repository_scope(bootstrap):
            raise ConfigError("Set GITHUB_ORGANIZATION or provide GITHUB_REPOSITORIES_JSON")
        return bootstrap

    client: MongoClient[dict[str, Any]] = MongoClient(
        bootstrap.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=5000
    )
    try:
        collection = client[bootstrap.mongodb_database][CONFIG_COLLECTION]
        return load_or_seed_runtime_settings(bootstrap, collection)
    except PyMongoError as error:
        raise ConfigError(
            "Could not load MongoDB application_config; verify the MongoDB URI and availability"
        ) from error
    finally:
        client.close()
