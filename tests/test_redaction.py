import logging
import sys

from github_team_stats.redaction import RedactingFilter, redact_text, redact_value


def test_redacts_github_tokens_and_authorization_values() -> None:
    text = (
        "ghp_abcdefghijklmnopqrstuvwxyz "
        "github_pat_11AAabcdefghijklmnopqrstuvwxyz "
        "Authorization: Bearer secret-value"
    )
    redacted = redact_text(text)
    assert "ghp_" not in redacted
    assert "github_pat_" not in redacted
    assert "secret-value" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_redacts_nested_sensitive_values() -> None:
    assert redact_value({"github_token": "plain-secret", "nested": ["ghp_abcdefghijk"]}) == {
        "github_token": "[REDACTED]",
        "nested": ["[REDACTED]"],
    }


def test_log_filter_redacts_message_and_exception() -> None:
    try:
        raise RuntimeError("Authorization: token hidden-secret")
    except RuntimeError:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "failed with %s",
            ("ghp_abcdefghijk",),
            exc_info=sys.exc_info(),
        )
    assert RedactingFilter().filter(record)
    assert "ghp_" not in record.getMessage()
    assert record.exc_text is not None
    assert "hidden-secret" not in record.exc_text
