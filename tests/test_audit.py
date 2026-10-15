from github_team_stats.audit import ConversationAuditor, sanitize_text, sanitize_value


class FakeSink:
    def __init__(self) -> None:
        self.records = []

    def append_conversation_audit(self, document) -> None:
        self.records.append(document)


def test_audit_records_context_tool_outcome_and_response() -> None:
    sink = FakeSink()
    auditor = ConversationAuditor(
        sink,
        model="test-model",
        retention_days=30,
        include_user_messages=True,
        include_assistant_responses=True,
    )
    turn = auditor.begin_turn(
        "Rahuldev199",
        {
            "intent": "pull_requests",
            "member_login": None,
            "period": "last month",
            "missing_fields": ["member"],
        },
    )
    auditor.record_router(
        turn,
        {
            "intent": "pull_requests",
            "member_login": "Rahuldev199",
            "period": None,
        },
    )
    auditor.record_merged_context(
        turn,
        {
            "intent": "pull_requests",
            "member_login": "Rahuldev199",
            "period": "last month",
            "missing_fields": [],
        },
    )
    call = auditor.begin_tool_call(
        turn,
        "get_member_git_activity",
        {"member_login": "Rahuldev199", "period": "last month", "live": False},
    )
    auditor.finish_tool_error(call, RuntimeError("GitHub resource not found"))
    auditor.finish_turn(
        turn,
        outcome="completed",
        assistant_response="The repository could not be accessed.",
    )

    record = sink.records[0]
    assert record["session_id"] == auditor.session_id
    assert record["turn_id"] == 1
    assert record["context_before"]["period"] == "last month"
    assert record["context_after_merge"]["member_login"] == "Rahuldev199"
    assert record["tool_calls"][0]["status"] == "error"
    assert record["tool_calls"][0]["error_type"] == "RuntimeError"
    assert record["assistant_response"] == "The repository could not be accessed."
    assert record["expires_at"] > record["created_at"]


def test_audit_redacts_tokens_and_sensitive_keys() -> None:
    token = "github_pat_1234567890abcdefghijklmnopqrstuvwxyz"
    assert token not in sanitize_text(f"Authorization: Bearer {token}")
    sanitized = sanitize_value({"github_token": token, "nested": {"message": token}})
    assert sanitized["github_token"] == "[REDACTED]"
    assert sanitized["nested"]["message"] == "[REDACTED]"


def test_audit_can_omit_message_content() -> None:
    sink = FakeSink()
    auditor = ConversationAuditor(
        sink,
        model="test-model",
        retention_days=7,
        include_user_messages=False,
        include_assistant_responses=False,
    )
    turn = auditor.begin_turn("sensitive question", None)
    auditor.finish_turn(turn, outcome="rejected", assistant_response="sensitive response")

    assert sink.records[0]["user_message"] is None
    assert sink.records[0]["assistant_response"] is None
