from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from github_team_stats.config import (
    Settings,
    resolve_copilot_token,
    resolve_github_token,
)


def test_repository_scope_configuration() -> None:
    settings = Settings(
        github_organization=None,
        github_repositories_json='["acme/api", "acme/web"]',
        github_token=SecretStr("secret"),
    )
    assert settings.repositories == ["acme/api", "acme/web"]
    assert settings.scope_key == "repos:acme/api,acme/web"
    assert settings.cache_backend == "mongodb"
    assert settings.audit_enabled is True
    assert settings.audit_retention_days == 30


def test_explicit_token_takes_precedence_over_credential_manager() -> None:
    settings = Settings(
        github_organization="acme",
        github_repositories_json="[]",
        github_token=SecretStr("secret"),
    )
    with patch("github_team_stats.infrastructure.settings.load_stored_token") as load_stored:
        assert resolve_github_token(settings) == "secret"
    load_stored.assert_not_called()


def test_copilot_reuses_github_token_by_default() -> None:
    settings = Settings(
        github_organization="acme",
        github_repositories_json="[]",
        copilot_github_token=SecretStr(""),
    )
    assert resolve_copilot_token(settings, "github-secret") == "github-secret"


def test_dedicated_copilot_token_takes_precedence() -> None:
    settings = Settings(
        github_organization="acme",
        github_repositories_json="[]",
        copilot_github_token=SecretStr("copilot-secret"),
    )
    assert resolve_copilot_token(settings, "github-secret") == "copilot-secret"


def test_rejects_organization_and_repository_scope_together() -> None:
    with pytest.raises(ValidationError, match="only one repository scope"):
        Settings(
            github_organization="acme",
            github_repositories_json='["acme/api"]',
        )


@pytest.mark.parametrize(
    "url",
    ["http://api.github.com", "https://evil.example/api", "api.github.com"],
)
def test_rejects_untrusted_github_api_url(url: str) -> None:
    with pytest.raises(ValidationError, match="GITHUB_API_URL"):
        Settings(github_organization="acme", github_api_url=url)


def test_allows_explicit_github_enterprise_https_url() -> None:
    settings = Settings(
        github_organization="acme",
        github_repositories_json="[]",
        github_api_url="https://github.company.example/api/v3",
        allow_github_enterprise=True,
    )
    assert settings.github_api_url == "https://github.company.example/api/v3"


def test_environment_overrides_appdata_config_and_dotenv_is_ignored(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.write_text(
        'github_organization = "from-file"\ngithub_repositories_json = "[]"\n',
        encoding="utf-8",
    )
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITHUB_ORGANIZATION=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ORGANIZATION", "from-environment")
    monkeypatch.setenv("GITHUB_REPOSITORIES_JSON", "[]")
    with patch("github_team_stats.config.CONFIG_PATH", config):
        settings = Settings()
    assert settings.github_organization == "from-environment"
