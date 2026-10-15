"""Per-Windows-user SQLite statistics and audit adapter."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from github_team_stats.domain.activity import MemberGitActivity
from github_team_stats.domain.member import MemberLinesAdded
from github_team_stats.domain.team import TeamDefinition


class SQLiteStatsStore:
    """Store user-isolated cache entries using fixed, parameterized SQL."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                kind TEXT NOT NULL,
                requester_key TEXT NOT NULL,
                member_key TEXT NOT NULL,
                period TEXT NOT NULL,
                scope TEXT NOT NULL,
                definitions_version TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (
                    kind, requester_key, member_key, period, scope, definitions_version
                )
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_audit (
                session_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_id, turn_id)
            )
            """
        )
        self._connection.commit()

    def _get(
        self,
        kind: str,
        requester_login: str,
        member_login: str,
        period: str,
        scope: str,
        definitions_version: str,
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT payload FROM snapshots
            WHERE kind = ? AND requester_key = ? AND member_key = ?
              AND period = ? AND scope = ? AND definitions_version = ?
            """,
            (
                kind,
                requester_login.casefold(),
                member_login.casefold(),
                period,
                scope,
                definitions_version,
            ),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def _upsert(self, kind: str, requester_login: str, payload: dict[str, Any]) -> None:
        member = payload["member"]
        self._connection.execute(
            """
            INSERT OR REPLACE INTO snapshots
              (kind, requester_key, member_key, period, scope, definitions_version, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                requester_login.casefold(),
                str(member["login"]).casefold(),
                payload["period"],
                payload["scope"],
                payload["definitions_version"],
                json.dumps(payload, default=str),
            ),
        )
        self._connection.commit()

    def get_member_lines_added(
        self, requester_login: str, member_login: str, period: str, scope: str
    ) -> MemberLinesAdded | None:
        payload = self._get("lines", requester_login, member_login, period, scope, "lines-added-v1")
        return MemberLinesAdded.model_validate(payload) if payload else None

    def upsert_member_lines_added(self, requester_login: str, stats: MemberLinesAdded) -> None:
        self._upsert("lines", requester_login, stats.model_dump(mode="json"))

    def get_member_activity(
        self, requester_login: str, member_login: str, period: str, scope: str
    ) -> MemberGitActivity | None:
        payload = self._get(
            "activity",
            requester_login,
            member_login,
            period,
            scope,
            "member-git-activity-v1",
        )
        return MemberGitActivity.model_validate(payload) if payload else None

    def upsert_member_activity(self, requester_login: str, activity: MemberGitActivity) -> None:
        self._upsert("activity", requester_login, activity.model_dump(mode="json"))

    def list_teams_for_lead(self, _lead_login: str) -> list[TeamDefinition]:
        return []

    def append_conversation_audit(self, document: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO conversation_audit (session_id, turn_id, payload) VALUES (?, ?, ?)",
            (document["session_id"], document["turn_id"], json.dumps(document, default=str)),
        )
        self._connection.commit()

    def get_conversation_audit(
        self, *, session_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if session_id:
            rows = self._connection.execute(
                "SELECT payload FROM conversation_audit WHERE session_id = ? "
                "ORDER BY turn_id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT payload FROM conversation_audit ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()
