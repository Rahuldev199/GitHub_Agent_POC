"""Backward-compatible semantic-routing imports."""

from github_team_stats.agent.routing import (
    OUT_OF_SCOPE_RESPONSE,
    ROUTER_SYSTEM_MESSAGE,
    IntentDecision,
    build_reporting_prompt,
    build_router_prompt,
    build_router_repair_prompt,
    is_allowed_decision,
    merge_with_previous_request,
)

__all__ = [
    "OUT_OF_SCOPE_RESPONSE",
    "ROUTER_SYSTEM_MESSAGE",
    "IntentDecision",
    "build_reporting_prompt",
    "build_router_prompt",
    "build_router_repair_prompt",
    "is_allowed_decision",
    "merge_with_previous_request",
]
