# GitHub Member Activity Agent

A Python 3.11+ agent that reports read-only GitHub activity for one exact GitHub
login and one required month. It does not need or attempt to discover a team.

The full report contains:

- commits with message, URL, date, repository, changed files, additions and deletions;
- exact totals for commits, lines added, lines deleted and lines changed;
- pull requests authored by the member that were opened or merged in the month,
  including state, URL and change totals;
- pull-request reviews submitted by the member in the month;
- GitHub Actions workflow runs triggered by the member, including status and result.
- authorized-team totals and a complete member-by-member breakdown for team leads.

## Safety and orchestration

```text
English prompt
  -> Copilot SDK extracts exact login + period
  -> registered application tool
  -> normalize period to YYYY-MM
  -> MongoDB application_config/default supplies operational configuration
  -> MongoDB team_registry authorizes the authenticated lead and supplies members/repos
  -> fixed per-user cache lookup (MongoDB by default; local SQLite optional)
     | fresh hit: return cached snapshot
     | miss/stale/live request: call GitHub REST with GET only
                            -> calculate exact totals in Python
                            -> store only complete snapshots -> return structured result
  -> Copilot explains the result
```

The model never creates a MongoDB query or GitHub URL. The application exposes only
three registered reporting tools: `get_member_git_activity`, the narrower
`get_member_lines_added`, and `get_team_activity`. It implements no create, update,
merge, approve, rerun or
delete operation. A live/open PR or workflow request bypasses cache and reads GitHub
again. Historical monthly reports are treated as final; current-month snapshots use
`CACHE_TTL_SECONDS` unless live data is requested.

A dedicated Copilot intent-router session understands the meaning of paraphrases and
short clarification replies. It returns a schema-validated decision containing the
supported intent, confidence, member, period, live-data flag, and missing fields.
The application retains that structured decision between chat turns, so a reply that
only supplies the requested login or period is combined with the earlier request.
Application code fails closed on out-of-scope or low-confidence decisions. General
programming, Python, personal, and unrelated questions receive a fixed scope message;
only accepted GitHub-activity decisions reach the reporting agent and its tools.

Repository scope is trusted MongoDB configuration: either one organization or an explicit
repository list in `application_config/default`. Organization discovery excludes forks and
disabled repositories.

Team access is also MongoDB-driven. `team_registry` records map normalized lead logins to
fixed member and repository lists. The requester identity always comes from the validated
GitHub token, never from the prompt. Team members are collected concurrently with a bounded
worker limit, while totals are calculated in Python. A member-level failure produces a
partial result and warning; authentication and rate-limit failures abort the whole report.
Individual member reports permit the authenticated user or a member of one of that user's
registered teams. Other GitHub logins are rejected before cache lookup or GitHub activity
collection, even if a similarly named account exists globally on GitHub. Authorized team
member reports use the union of repositories registered for that member's teams.
Bots and merge commits are excluded. Commit attribution requires GitHub to link the
commit to the exact requested login. All period boundaries use UTC.

Detail arrays are capped by `ACTIVITY_DETAIL_LIMIT` (default 200) to keep model input
bounded. Totals continue to include every matching item, and the response marks any
truncated detail category. Workflow access failures are returned as warnings because
some tokens cannot read Actions data. A repository-level 403, 404, or Actions failure
returns `complete=false` with a structured warning while other repositories continue.
Authentication and rate-limit failures stop the report. Incomplete reports are not cached
as final.

## Package architecture

The source follows a layered `src` package layout. Dependencies point inward: domain
models do not import infrastructure, application use cases depend on protocols, and the
composition root selects concrete GitHub and cache adapters.

```text
src/github_team_stats/
|-- domain/                 # Pydantic models, periods, and typed errors
|-- application/            # Member/team use cases and dependency protocols
|-- agent/
|   |-- routing.py          # Structured intent decisions and prompts
|   |-- runtime.py          # Copilot session orchestration
|   `-- tools/              # Strict read-only tool adapters
|-- infrastructure/
|   |-- github/             # HTTP transport and activity collection
|   |-- persistence/        # Independent MongoDB and SQLite adapters
|   |-- settings.py         # Validated local bootstrap configuration
|   |-- runtime_settings.py # MongoDB-driven operational configuration
|   |-- credentials.py      # Windows Credential Manager integration
|   `-- security.py         # Central token redaction
|-- presentation/
|   |-- cli.py              # Argument parsing and command dispatch
|   |-- terminal.py         # Rich TTY and stable JSON/CSV presentation
|   `-- web/                # Protected localhost dashboard and bundled assets
`-- bootstrap.py            # Application composition root
```

Small modules at the package root are compatibility re-exports for existing imports;
new code should import from the canonical subpackages above. Formatting and import order
are enforced with Ruff, all production code passes `mypy --strict`, and the Windows CI
runs tests with an 80% coverage gate, Bandit, and dependency auditing.

## Required token permissions

Use a fine-grained personal access token owned by the person running the executable.
Grant access only to the repositories that person is allowed to report on.

| Permission | Access | Used for |
|---|---:|---|
| Metadata | Read | Repository identity and visibility |
| Contents | Read | Commits, commit details, additions, and deletions |
| Pull requests | Read | PRs, PR details, and submitted reviews |
| Actions | Read | Workflow runs; without it, Actions becomes a partial warning |
| Account > Copilot Requests | Read | Required only for natural-language `ask` and `chat` |

The account also needs an active GitHub Copilot entitlement for `ask` and `chat`.
The deterministic `activity`, `lines`, and `auth` paths do not need Copilot; `doctor`
probes Copilot access and reports it separately.

## Quick start for the Windows EXE

1. Put `github-member-activity.exe` in a folder of your choice.
2. Create `%APPDATA%\github-member-activity\config` from `config.example.toml`. On the
   first run, its non-secret operational values seed MongoDB
   `github_member_stats.application_config` document `_id: "default"`.
3. Store the token securely and verify it:

   ```powershell
   .\github-member-activity.exe auth setup
   .\github-member-activity.exe auth status
   ```

4. Check repository, Copilot, and cache access:

   ```powershell
   .\github-member-activity.exe doctor
   ```

5. Run a deterministic report or chat:

   ```powershell
   .\github-member-activity.exe activity --member Rahuldev199 --period "last month"
   .\github-member-activity.exe team-activity --period "last month"
   .\github-member-activity.exe chat
   ```

6. Open the local dashboard:

   ```powershell
   .\github-member-activity.exe ui
   ```

   The application chooses a free port on `127.0.0.1`, opens the default browser,
   and protects the session with a single-use launch token, an HttpOnly cookie, and
   request-Origin validation. Stop it with `Ctrl+C`. GitHub and Copilot credentials
   remain in the executable process and are never returned to browser code.

## Terminal and browser interfaces

Interactive terminal reports use Rich panels, progress indicators, highlighted team
tables, warning markers, and Markdown chat responses. `NO_COLOR` disables color, and
redirected output automatically uses plain text. Explicit machine formats never contain
terminal decoration:

```powershell
.\github-member-activity.exe team-activity --period "last month" --format json
.\github-member-activity.exe team-activity --period "last month" --format csv > report.csv
```

The `ui` dashboard reuses the same authorization, cache, GitHub, aggregation, and agent
services as the CLI. It provides overview totals, a sortable member table, cached GitHub
avatars with initials fallback, commit/PR/daily/trend charts, partial-data warnings,
read-only chat, and XLSX/CSV/standalone-HTML exports. All HTML, CSS, and JavaScript assets
are packaged with the application; no CDN or external script is used. The only browser
write request is a local chat question, and the agent remains constrained to the existing
read-only reporting tools.

## Source setup

1. Install Python 3.11+ and MongoDB. To run without MongoDB, explicitly set
   `cache_backend = "sqlite"`.
2. Run `github-member-activity auth setup`, or provide `GITHUB_TOKEN`/`GH_TOKEN`
   through the environment.
3. Run `python -m pip install --require-hashes -r requirements.lock`, followed by
   `python -m pip install --no-deps -e .`.
4. Copy `config.example.toml` to
   `%APPDATA%\github-member-activity\config` and choose exactly one repository scope.
5. Optionally run `python -m copilot download-runtime`.

Authentication precedence is `GITHUB_TOKEN`, then `GH_TOKEN`, then the token stored
in Windows Credential Manager. Credentials are never stored in
MongoDB, embedded in the executable, printed, or sent as tool results.
The Copilot SDK reuses that resolved token by default. Set `COPILOT_GITHUB_TOKEN`
only when Copilot must use a different supported GitHub credential.

MongoDB document `application_config/default` is authoritative for operational settings.
The environment and `%APPDATA%\github-member-activity\config` provide only bootstrap
values needed to connect to MongoDB and seed that document on the first run. GitHub and
Copilot tokens remain local. The current directory and `./.env` are intentionally ignored.
For `ask` and `chat`, a fine-grained token must be owned by the user's personal
account, include the account-level `Copilot Requests` permission, and be associated
with active Copilot access. The direct `activity` and `lines` commands need only the
GitHub read permissions described above.

## MongoDB-driven configuration

The MongoDB document contains repository scope, GitHub API behavior, cache TTL, detail
limits, audit options, and the Copilot model. It never contains GitHub/Copilot tokens or
the MongoDB URI. After the first successful start, change operational values in:

```text
Database:   github_member_stats
Collection: application_config
Document:   _id = "default"
```

Explicit repositories are stored as a native array, for example:

```json
"github_repositories": ["Rahuldev199/hello-world"]
```

## MongoDB team registry

Create one document per team in `github_member_stats.team_registry`. Start from
`team.example.json`:

```json
{
  "_id": "backend",
  "team_name": "Backend",
  "lead_logins": ["lead-github-login"],
  "members": ["member-one", "member-two"],
  "repositories": ["company/api", "company/payments"],
  "enabled": true
}
```

Store `lead_logins` in lowercase. A lead with exactly one authorized team can ask
“Show my team activity last month” without naming the team. If the lead has multiple
authorized teams, the prompt or `--team` argument must specify one. Prompt-supplied member
lists can select one or more existing team members but cannot expand the MongoDB-authorized
membership; if any requested login is outside the team, the entire request is denied.

Bootstrap/first-run examples:

Organization scope:

```toml
github_organization = "your-company"
github_repositories_json = "[]"
cache_backend = "mongodb"
mongodb_uri = "mongodb://localhost:27017"
mongodb_database = "github_member_stats"
```

Explicit scope:

```toml
github_organization = ""
github_repositories_json = '["your-company/api","your-company/payments"]'
cache_backend = "mongodb"
mongodb_uri = "mongodb://localhost:27017"
mongodb_database = "github_member_stats"
```

MongoDB cache (default):

```toml
cache_backend = "mongodb"
mongodb_uri = "mongodb://localhost:27017"
mongodb_database = "github_member_stats"
```

Optional local SQLite fallback:

```toml
cache_backend = "sqlite"
```

## Run

Complete deterministic report without an LLM:

```powershell
github-member-activity activity --member rahul-github --period 2026-09
```

Authorized team report without an LLM:

```powershell
github-member-activity team-activity --period 2026-09
github-member-activity team-activity --team Backend --period "last month" --refresh
github-member-activity team-activity --member user1 --member user2 --period "last month"
```

Force a fresh GitHub read:

```powershell
github-member-activity activity --member rahul-github --period "this month" --refresh
```

Lines-only command:

```powershell
github-member-activity lines --member rahul-github --period 2026-09
```

Natural language or persistent chat (requires Copilot Requests permission):

```powershell
github-member-activity ask "Show all GitHub activity for rahul-github this month"
github-member-activity ask "Show my team's total lines added last month"
github-member-activity ask "Show reports for team members user1 and user2 last month"
github-member-activity chat
```

If the login or period is absent, the agent asks for it before making a statistics
tool call. The response includes `cache_status`, normalized month, scope, exact totals,
detail lists, truncation flags, warnings, and timestamps.

## Test and package

```powershell
python -m ruff check src tests
python -m mypy --strict src
python -m pytest --cov=github_team_stats --cov-fail-under=80
python -m bandit -r src -c pyproject.toml
python -m pip_audit -r requirements.lock
.\scripts\build_exe.ps1
```

The build produces `dist/github-member-activity.exe` and
`dist/github-member-activity.exe.sha256`. Confirm the embedded version and checksum:

```powershell
.\dist\github-member-activity.exe --version
Get-FileHash .\dist\github-member-activity.exe -Algorithm SHA256
Get-Content .\dist\github-member-activity.exe.sha256
```

## Troubleshooting

- `AuthError` / exit code 401: the token is invalid or expired. Run `auth setup` again,
  then `auth status`.
- `PermissionDenied` / exit code 403: add the missing read permission or repository
  grant. A non-rate-limited error confined to one repository appears as a partial warning.
- `NotFound` / exit code 404: verify `owner/repository`; for private repositories, verify
  that the fine-grained token includes that repository.
- `RateLimited` / exit code 429: wait until the reported reset time. The client honors
  `Retry-After`, primary reset headers, and secondary-rate-limit responses.
- Copilot authentication failure: use a user-owned fine-grained token with
  `Account > Copilot Requests: Read` and verify the account has active Copilot access.
- Repository settings appear ignored: edit `%APPDATA%\github-member-activity\config`.
  The current directory and `./.env` are intentionally not read.
- Cache problems: run `doctor`. The default MongoDB connection is
  `mongodb://localhost:27017`, database `github_member_stats`. If SQLite is selected,
  its file is `%LOCALAPPDATA%\github-member-activity\cache.sqlite3`.
- `complete=false`: inspect each warning's `repository`, `source`, `code`, and `message`;
  successful repositories are still included, and the incomplete result was not finalized.

## API cost

On a cache miss the client lists commits and pull requests for each repository, reads
each counted commit/PR for change totals, reads reviews for period-relevant PRs, and
lists workflow runs. Large organizations can use many GitHub API requests. The per-user
cache avoids repeating work for the same requester, member, month, scope, and definition.
Natural-language `ask` and `chat` use one structured Copilot routing decision before
the reporting-agent turn, so accepted questions normally use two model turns.

## Metric definitions

See [`docs/metrics.md`](docs/metrics.md) for the exact UTC month boundaries, default-branch
behavior, squash-merge treatment, unlinked-email exclusion, fork policy, and definitions
for commits, lines, pull requests, reviews, and workflow runs.
