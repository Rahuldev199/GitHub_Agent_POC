"""MongoDB statistics, team-registry, and audit adapter."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

from github_team_stats.domain.activity import MemberGitActivity
from github_team_stats.domain.member import MemberLinesAdded
from github_team_stats.domain.team import TeamDefinition


class MongoStatsStore:
    """MongoDB snapshot store. Queries are fixed and never model-generated."""

    def __init__(
        self,
        uri: str,
        database: str,
        *,
        audit_enabled: bool = False,
    ) -> None:
        self._client: MongoClient[dict[str, Any]] = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._collection: Collection[dict[str, Any]] = self._client[database]["member_month_lines"]
        self._activity_collection: Collection[dict[str, Any]] = self._client[database][
            "member_month_activity"
        ]
        self._audit_collection: Collection[dict[str, Any]] = self._client[database][
            "conversation_audit"
        ]
        self._team_collection: Collection[dict[str, Any]] = self._client[database]["team_registry"]
        self._collection.create_index(
            [
                ("requester_key", ASCENDING),
                ("member_key", ASCENDING),
                ("period", ASCENDING),
                ("scope", ASCENDING),
                ("definitions_version", ASCENDING),
            ],
            unique=True,
            name="requester_member_period_scope_definition_unique",
        )
        self._activity_collection.create_index(
            [
                ("requester_key", ASCENDING),
                ("member_key", ASCENDING),
                ("period", ASCENDING),
                ("scope", ASCENDING),
                ("definitions_version", ASCENDING),
            ],
            unique=True,
            name="requester_member_activity_period_scope_definition_unique",
        )
        self._team_collection.create_index(
            [("lead_logins", ASCENDING), ("enabled", ASCENDING)],
            name="authorized_team_leads",
        )
        if audit_enabled:
            self._audit_collection.create_index(
                [("session_id", ASCENDING), ("turn_id", ASCENDING)],
                unique=True,
                name="conversation_session_turn_unique",
            )
            self._audit_collection.create_index(
                "expires_at",
                expireAfterSeconds=0,
                name="conversation_audit_expiration",
            )

    def get_member_lines_added(
        self, requester_login: str, member_login: str, period: str, scope: str
    ) -> MemberLinesAdded | None:
        document = self._collection.find_one(
            {
                "requester_key": requester_login.strip().casefold(),
                "member_key": member_login.strip().casefold(),
                "period": period,
                "scope": scope,
                "definitions_version": "lines-added-v1",
            },
            {"_id": 0, "member_key": 0, "requester_key": 0},
        )
        return MemberLinesAdded.model_validate(document) if document else None

    def upsert_member_lines_added(self, requester_login: str, stats: MemberLinesAdded) -> None:
        document = stats.model_dump(mode="python")
        document["requester_key"] = requester_login.casefold()
        document["member_key"] = stats.member.login.casefold()
        self._collection.replace_one(
            {
                "requester_key": document["requester_key"],
                "member_key": document["member_key"],
                "period": stats.period,
                "scope": stats.scope,
                "definitions_version": stats.definitions_version,
            },
            document,
            upsert=True,
        )

    def get_member_activity(
        self, requester_login: str, member_login: str, period: str, scope: str
    ) -> MemberGitActivity | None:
        document = self._activity_collection.find_one(
            {
                "requester_key": requester_login.strip().casefold(),
                "member_key": member_login.strip().casefold(),
                "period": period,
                "scope": scope,
                "definitions_version": "member-git-activity-v1",
            },
            {"_id": 0, "member_key": 0, "requester_key": 0},
        )
        return MemberGitActivity.model_validate(document) if document else None

    def upsert_member_activity(self, requester_login: str, activity: MemberGitActivity) -> None:
        document = activity.model_dump(mode="python")
        document["requester_key"] = requester_login.casefold()
        document["member_key"] = activity.member.login.casefold()
        self._activity_collection.replace_one(
            {
                "requester_key": document["requester_key"],
                "member_key": document["member_key"],
                "period": activity.period,
                "scope": activity.scope,
                "definitions_version": activity.definitions_version,
            },
            document,
            upsert=True,
        )

    def list_teams_for_lead(self, lead_login: str) -> list[TeamDefinition]:
        documents = self._team_collection.find(
            {"lead_logins": lead_login.strip().casefold(), "enabled": True}
        )
        return [TeamDefinition.model_validate(document) for document in documents]

    def append_conversation_audit(self, document: dict[str, Any]) -> None:
        """Insert one immutable conversation turn; existing turns are never updated."""

        self._audit_collection.insert_one(document)

    def get_conversation_audit(
        self, *, session_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        query = {"session_id": session_id} if session_id else {}
        sort = [("turn_id", ASCENDING)] if session_id else [("created_at", -1)]
        cursor = self._audit_collection.find(query, {"_id": 0}).sort(sort).limit(limit)
        return list(cursor)

    def close(self) -> None:
        self._client.close()
