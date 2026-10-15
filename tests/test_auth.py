from unittest.mock import patch

from github_team_stats.auth import load_stored_token, store_token


def test_auth_setup_uses_keyring_without_printing_token() -> None:
    with patch("keyring.set_password") as set_password:
        store_token("ghp_abcdefghijk")
    set_password.assert_called_once_with(
        "github-member-activity", "github-token", "ghp_abcdefghijk"
    )


def test_load_stored_token_uses_keyring() -> None:
    with patch("keyring.get_password", return_value=" stored-token "):
        assert load_stored_token() == "stored-token"
