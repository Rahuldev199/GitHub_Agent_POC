"""Command-line presentation layer."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pydantic import ValidationError

from github_team_stats import full_version
from github_team_stats.bootstrap import build_application
from github_team_stats.domain.errors import AppError, ConfigError
from github_team_stats.infrastructure.credentials import store_token
from github_team_stats.infrastructure.security import install_log_redaction, redact_text
from github_team_stats.infrastructure.settings import get_settings, resolve_github_credential
from github_team_stats.presentation.terminal import FORMATS, TerminalPresenter


def _output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format", choices=FORMATS, default="auto",
        help="Output format; auto uses Rich only in an interactive terminal",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only GitHub Member Activity Agent")
    parser.add_argument("--version", action="version", version=full_version())
    commands = parser.add_subparsers(dest="command", required=True)

    lines = commands.add_parser("lines", help="Get lines added without the LLM")
    lines.add_argument("--member", required=True, help="Exact GitHub login")
    lines.add_argument("--period", required=True)
    lines.add_argument("--refresh", action="store_true")
    _output_argument(lines)

    activity = commands.add_parser(
        "activity", help="Get the complete member activity report without the LLM"
    )
    activity.add_argument("--member", required=True, help="Exact GitHub login")
    activity.add_argument("--period", required=True)
    activity.add_argument("--refresh", action="store_true")
    _output_argument(activity)

    team_activity = commands.add_parser(
        "team-activity", help="Get authorized team activity without the LLM"
    )
    team_activity.add_argument("--period", required=True)
    team_activity.add_argument("--team", help="Team name when the lead has multiple teams")
    team_activity.add_argument(
        "--member",
        action="append",
        dest="members",
        help="Authorized member login; repeat to select multiple members",
    )
    team_activity.add_argument("--refresh", action="store_true")
    _output_argument(team_activity)

    ask = commands.add_parser("ask", help="Ask one natural-language question")
    ask.add_argument("prompt", nargs="+")

    commands.add_parser("chat", help="Start an interactive Copilot session")
    commands.add_parser("ui", help="Open the protected local read-only dashboard")

    auth = commands.add_parser("auth", help="Manage local GitHub authentication")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("setup", help="Store a token in Windows Credential Manager")
    auth_commands.add_parser("status", help="Show token source and validity")

    commands.add_parser("doctor", help="Check token, repositories, Copilot, and cache")

    audit = commands.add_parser("audit", help="Read recent conversation audit records")
    audit.add_argument("--session", help="Optional audit session ID")
    audit.add_argument("--limit", type=int, default=50, choices=range(1, 501))
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.command == "auth" and args.auth_command == "setup":
        store_token()
        print("GitHub token stored in Windows Credential Manager.")
        return 0

    if args.command == "auth" and args.auth_command == "status":
        settings = get_settings()
        credential = resolve_github_credential(settings)
        from github_team_stats.infrastructure.github import GitHubRestClient

        async with GitHubRestClient(
            credential.token,
            api_url=settings.github_api_url,
            api_version=settings.github_api_version,
        ) as github:
            login = await github.get_authenticated_login()
        print(json.dumps({"source": credential.source, "valid": True, "login": login}))
        return 0

    app = build_application(get_settings())
    try:
        if args.command == "doctor":
            checks: dict[str, dict[str, object]] = {}
            checks["configuration"] = {
                "ok": True,
                "source": (
                    "mongodb:application_config/default"
                    if app.settings.cache_backend == "mongodb"
                    else "local bootstrap"
                ),
            }
            try:
                login = await app.github.get_authenticated_login()
                checks["token"] = {"ok": True, "login": login}
                repositories = await app.github.resolve_repositories(
                    app.settings.github_organization, app.settings.repositories
                )
                checks["repositories"] = {"ok": True, "visible": len(repositories)}
                teams = app.store.list_teams_for_lead(login)
                checks["teams"] = {
                    "ok": bool(teams),
                    "authorized": [
                        {"name": team.team_name, "members": len(team.members)} for team in teams
                    ],
                }
            except Exception as error:
                checks["token_or_repositories"] = {
                    "ok": False,
                    "message": redact_text(str(error)),
                }
            try:
                await app.runtime.start()
                checks["copilot"] = {"ok": True}
            except Exception as error:
                checks["copilot"] = {"ok": False, "message": redact_text(str(error))}
            checks["cache"] = {
                "ok": True,
                "backend": app.settings.cache_backend,
            }
            print(json.dumps(checks, indent=2))
            return 0 if all(bool(check.get("ok")) for check in checks.values()) else 1

        if args.command == "lines":
            presenter = TerminalPresenter(args.format)
            with presenter.working(f"Fetching {args.member} activity…"):
                lines_result = await app.service.get_member_lines_added(
                    args.member, args.period, force_refresh=args.refresh
                )
            presenter.render_model(lines_result)
            return 0

        if args.command == "activity":
            presenter = TerminalPresenter(args.format)
            with presenter.working(f"Fetching {args.member} activity…"):
                activity_result = await app.activity_service.get_member_activity(
                    args.member, args.period, force_refresh=args.refresh
                )
            presenter.render_model(activity_result)
            return 0

        if args.command == "team-activity":
            presenter = TerminalPresenter(args.format)
            with presenter.progress("Fetching authorized team members…"):
                team_result = await app.team_activity_service.get_team_activity(
                    args.period,
                    team_name=args.team,
                    member_logins=args.members,
                    force_refresh=args.refresh,
                )
            presenter.render_model(team_result)
            return 0

        if args.command == "ask":
            print(await app.runtime.ask(" ".join(args.prompt)))
            return 0

        if args.command == "audit":
            records = app.store.get_conversation_audit(session_id=args.session, limit=args.limit)
            print(json.dumps(records, indent=2, default=str))
            return 0

        presenter = TerminalPresenter()
        presenter.banner()
        print("Type 'exit' to quit.")
        if app.runtime.audit_session_id:
            print(f"Audit session: {app.runtime.audit_session_id}")
        while True:
            try:
                prompt = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if prompt.casefold() in {"exit", "quit"}:
                return 0
            if prompt:
                presenter.chat_user(prompt)
                with presenter.working("Thinking…"):
                    answer = await app.runtime.ask(prompt)
                presenter.chat_agent(answer)
    finally:
        await app.close()


def main() -> None:
    install_log_redaction()
    try:
        args = _parser().parse_args()
        if args.command == "ui":
            from github_team_stats.presentation.web import run_local_ui

            run_local_ui(build_application(get_settings()))
            raise SystemExit(0)
        raise SystemExit(asyncio.run(_run(args)))
    except AppError as error:
        print(f"{type(error).__name__}: {redact_text(str(error))}", file=sys.stderr)
        raise SystemExit(error.exit_code) from error
    except (ValidationError, ValueError) as error:
        mapped = ConfigError(redact_text(str(error)))
        print(f"ConfigError: {mapped}", file=sys.stderr)
        raise SystemExit(mapped.exit_code) from error
