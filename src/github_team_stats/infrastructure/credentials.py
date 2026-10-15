"""Secure local credential storage adapter."""

from __future__ import annotations

import getpass
from dataclasses import dataclass

_SERVICE = "github-member-activity"
_ACCOUNT = "github-token"


@dataclass(frozen=True, slots=True)
class Credential:
    token: str
    source: str


def store_token(token: str | None = None) -> None:
    value = (token if token is not None else getpass.getpass("GitHub token: ")).strip()
    if not value:
        raise ValueError("GitHub token cannot be empty")
    try:
        import keyring
    except ImportError as error:
        raise ValueError("Credential storage requires the 'keyring' package") from error
    keyring.set_password(_SERVICE, _ACCOUNT, value)


def load_stored_token() -> str | None:
    try:
        import keyring
    except ImportError:
        return None
    value = keyring.get_password(_SERVICE, _ACCOUNT)
    return value.strip() if value and value.strip() else None
