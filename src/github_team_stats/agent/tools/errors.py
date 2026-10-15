"""Safe structured errors returned to the reporting model."""

from __future__ import annotations

import json

from github_team_stats.domain.errors import MemberAccessDenied
from github_team_stats.infrastructure.security import redact_text


def member_access_error(error: MemberAccessDenied) -> str:
    """Describe a denied member without exposing secrets or fabricated metrics."""

    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": "member_not_authorized",
                "message": redact_text(str(error)),
            },
        },
        indent=2,
    )
