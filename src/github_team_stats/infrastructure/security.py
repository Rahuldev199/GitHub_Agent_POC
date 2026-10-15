"""Central token redaction for logs, errors, and audit data."""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Mapping
from typing import Any

_TOKEN_PATTERNS = (
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b", re.IGNORECASE),
    re.compile(
        r"(authorization\s*[:=]\s*(?:bearer|token)\s+)[^\s,;]+",
        re.IGNORECASE,
    ),
)
_SENSITIVE_KEYS = frozenset(
    {"authorization", "github_token", "gh_token", "copilot_github_token", "token"}
)


def redact_text(value: str) -> str:
    sanitized = value
    for pattern in _TOKEN_PATTERNS:
        if pattern.groups:
            sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
        else:
            sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]" if str(key).casefold() in _SENSITIVE_KEYS else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_text("".join(traceback.format_exception(*record.exc_info)))
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    if not any(isinstance(item, RedactingFilter) for item in root.filters):
        root.addFilter(RedactingFilter())
