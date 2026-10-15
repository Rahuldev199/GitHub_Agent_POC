"""Authorization policy for individual member reports."""

from __future__ import annotations

from dataclasses import dataclass

from github_team_stats.application.ports import TeamDirectory
from github_team_stats.domain.errors import MemberAccessDenied


@dataclass(frozen=True, slots=True)
class AuthorizedMemberScope:
    """Repository scope granted by the requester's team registrations."""

    repositories: tuple[str, ...]

    @property
    def cache_key(self) -> str:
        repositories = ",".join(repository.casefold() for repository in self.repositories)
        return f"repos:{repositories}"


class MemberAccessPolicy:
    """Allow self-reports and members registered to a lead in MongoDB."""

    def __init__(self, teams: TeamDirectory) -> None:
        self._teams = teams

    def authorize(self, requester_login: str, member_login: str) -> AuthorizedMemberScope | None:
        """Return a team repository scope, or ``None`` for a self-report."""

        requester_key = requester_login.strip().casefold()
        member_key = member_login.strip().casefold()
        if requester_key == member_key:
            return None

        authorized_repositories: dict[str, str] = {}
        for team in self._teams.list_teams_for_lead(requester_login):
            if member_key not in {member.casefold() for member in team.members}:
                continue
            for repository in team.repositories:
                authorized_repositories.setdefault(repository.casefold(), repository)

        if not authorized_repositories:
            raise MemberAccessDenied(
                f"GitHub login {member_login!r} is not an authorized member of any team "
                f"led by {requester_login!r}"
            )

        repositories = tuple(
            authorized_repositories[key] for key in sorted(authorized_repositories)
        )
        return AuthorizedMemberScope(repositories=repositories)
