"""Conversation audit persistence orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from github_team_stats import __version__
from github_team_stats.infrastructure.security import redact_text as sanitize_text
from github_team_stats.infrastructure.security import redact_value as sanitize_value

ROUTER_VERSION = "semantic-router-v2"


class AuditSink(Protocol):
    def append_conversation_audit(self, document: dict[str, Any]) -> None: ...


class ConversationAuditor:
    """Build and persist append-only, sanitized records for Copilot chat turns."""

    def __init__(
        self,
        sink: AuditSink,
        *,
        model: str,
        retention_days: int,
        include_user_messages: bool,
        include_assistant_responses: bool,
    ) -> None:
        self._sink = sink
        self._model = model
        self._retention = timedelta(days=retention_days)
        self._include_user_messages = include_user_messages
        self._include_assistant_responses = include_assistant_responses
        self.session_id = str(uuid.uuid4())
        self._turn_id = 0

    def begin_turn(
        self, user_message: str, context_before: dict[str, Any] | None
    ) -> dict[str, Any]:
        self._turn_id += 1
        created_at = datetime.now(UTC)
        return {
            "session_id": self.session_id,
            "turn_id": self._turn_id,
            "created_at": created_at,
            "expires_at": created_at + self._retention,
            "user_message": (sanitize_text(user_message) if self._include_user_messages else None),
            "context_before": sanitize_value(context_before),
            "router_decision": None,
            "context_after_merge": None,
            "tool_calls": [],
            "assistant_response": None,
            "outcome": "started",
            "error": None,
            "model": self._model,
            "router_version": ROUTER_VERSION,
            "application_version": __version__,
        }

    @staticmethod
    def record_router(turn: dict[str, Any], decision: dict[str, Any]) -> None:
        turn["router_decision"] = sanitize_value(decision)

    @staticmethod
    def record_merged_context(turn: dict[str, Any], context: dict[str, Any]) -> None:
        turn["context_after_merge"] = sanitize_value(context)

    @staticmethod
    def begin_tool_call(
        turn: dict[str, Any], name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        call = {
            "name": name,
            "arguments": sanitize_value(arguments),
            "status": "started",
            "result_size_bytes": None,
            "error_type": None,
            "error_message": None,
        }
        turn["tool_calls"].append(call)
        return call

    @staticmethod
    def finish_tool_success(call: dict[str, Any], result: str) -> None:
        call["status"] = "success"
        call["result_size_bytes"] = len(result.encode("utf-8"))

    @staticmethod
    def finish_tool_error(call: dict[str, Any], error: Exception) -> None:
        call["status"] = "error"
        call["error_type"] = type(error).__name__
        call["error_message"] = sanitize_text(str(error))

    def finish_turn(
        self,
        turn: dict[str, Any],
        *,
        outcome: str,
        assistant_response: str | None = None,
        error: Exception | None = None,
    ) -> None:
        turn["outcome"] = outcome
        if self._include_assistant_responses and assistant_response is not None:
            turn["assistant_response"] = sanitize_text(assistant_response)
        if error is not None:
            turn["error"] = {
                "type": type(error).__name__,
                "message": sanitize_text(str(error)),
            }
        self._sink.append_conversation_audit(turn)
