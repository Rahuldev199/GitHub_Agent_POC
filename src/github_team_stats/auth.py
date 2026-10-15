"""Backward-compatible credential imports."""

from github_team_stats.infrastructure.credentials import Credential, load_stored_token, store_token

__all__ = ["Credential", "load_stored_token", "store_token"]
