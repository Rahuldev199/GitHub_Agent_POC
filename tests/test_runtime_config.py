from typing import Any

import pytest
from pydantic import SecretStr

from github_team_stats.config import Settings
from github_team_stats.errors import ConfigError
from github_team_stats.runtime_config import load_or_seed_runtime_settings


class FakeConfigurationCollection:
    def __init__(self, document: dict[str, Any] | None = None) -> None:
        self.document = document
        self.inserted: dict[str, Any] | None = None

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None:
        assert filter == {"_id": "default"}
        return self.document

    def insert_one(self, document: dict[str, Any]) -> object:
        self.inserted = document
        return object()


def test_first_run_seeds_only_non_secret_runtime_configuration() -> None:
    bootstrap = Settings(
        github_repositories_json='["acme/api"]',
        github_token=SecretStr("github-secret"),
        mongodb_uri=SecretStr("mongodb://user:password@example.test"),
    )
    collection = FakeConfigurationCollection()

    resolved = load_or_seed_runtime_settings(bootstrap, collection)

    assert resolved.repositories == ["acme/api"]
    assert collection.inserted is not None
    assert collection.inserted["github_repositories"] == ["acme/api"]
    assert "github_token" not in collection.inserted
    assert "copilot_github_token" not in collection.inserted
    assert "mongodb_uri" not in collection.inserted
    assert "cache_backend" not in collection.inserted


def test_existing_mongodb_document_drives_runtime_configuration() -> None:
    bootstrap = Settings(
        github_repositories_json="[]",
        github_token=SecretStr("github-secret"),
        mongodb_uri=SecretStr("mongodb://localhost:27017"),
    )
    collection = FakeConfigurationCollection(
        {
            "_id": "default",
            "schema_version": 1,
            "github_repositories": ["central/platform"],
            "cache_ttl_seconds": 7200,
            "activity_detail_limit": 75,
            "copilot_model": "gpt-5",
        }
    )

    resolved = load_or_seed_runtime_settings(bootstrap, collection)

    assert resolved.repositories == ["central/platform"]
    assert resolved.cache_ttl_seconds == 7200
    assert resolved.activity_detail_limit == 75
    assert resolved.github_token is not None
    assert resolved.github_token.get_secret_value() == "github-secret"
    assert resolved.mongodb_uri.get_secret_value() == "mongodb://localhost:27017"
    assert collection.inserted is None


def test_missing_mongodb_scope_fails_closed() -> None:
    bootstrap = Settings(github_repositories_json="[]")
    collection = FakeConfigurationCollection(
        {
            "_id": "default",
            "schema_version": 1,
            "github_organization": None,
            "github_repositories": [],
        }
    )

    with pytest.raises(ConfigError, match="application_config must set"):
        load_or_seed_runtime_settings(bootstrap, collection)
