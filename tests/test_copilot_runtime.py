from typing import Any, cast

import pytest
from pydantic import ValidationError

from github_team_stats.copilot_runtime import CopilotRuntime, CopilotRuntimeError
from github_team_stats.guardrails import IntentDecision


def _decision() -> IntentDecision:
    return IntentDecision(
        intent="lines",
        confidence=0.98,
        member_login=None,
        member_logins=[],
        team_name=None,
        period=None,
        live=False,
        missing_fields=["member", "period"],
        reason="Commit-detail follow-up",
    )


def _malformed_output_error() -> ValidationError:
    with pytest.raises(ValidationError) as captured:
        IntentDecision.model_validate_json('{"intent":"lines"} trailing text')
    return captured.value


class _FakeRouterSession:
    def __init__(self, responses: list[IntentDecision | Exception]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def send_and_wait_typed(
        self, prompt: str, _response_type: type[IntentDecision]
    ) -> IntentDecision:
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _runtime(router: _FakeRouterSession) -> CopilotRuntime:
    runtime = CopilotRuntime(cast(Any, None), cast(Any, None), cast(Any, None))
    runtime._router_session = router
    return runtime


async def test_router_retries_once_after_trailing_text_and_preserves_context() -> None:
    expected = _decision()
    router = _FakeRouterSession([_malformed_output_error(), expected])
    runtime = _runtime(router)
    runtime._routing_context = IntentDecision(
        intent="full_activity",
        confidence=0.99,
        member_login="Rahuldev199",
        member_logins=[],
        team_name=None,
        period="this month",
        live=False,
        missing_fields=[],
        reason="Previous commit report",
    )

    actual = await runtime._route("what did he commit?")

    assert actual == expected
    assert len(router.prompts) == 2
    assert "what did he commit?" in router.prompts[1]
    assert "Rahuldev199" in router.prompts[1]
    assert "exactly one JSON object" in router.prompts[1]


async def test_router_fails_closed_after_second_malformed_response() -> None:
    router = _FakeRouterSession([_malformed_output_error(), _malformed_output_error()])
    runtime = _runtime(router)

    with pytest.raises(CopilotRuntimeError, match="invalid structured output twice"):
        await runtime._route("what did he commit?")

    assert len(router.prompts) == 2
