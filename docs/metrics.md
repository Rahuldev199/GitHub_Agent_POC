# Metric definitions

All metrics are calculated by application code from read-only GitHub REST responses.

## Time boundary

- A requested month is normalized to `YYYY-MM`.
- The interval is `[00:00:00 UTC on day 1, 00:00:00 UTC on day 1 of the next month)`.
- A pull request can count once as opened and once as merged when both events occur in the month.

## Commits and branches

- Commit searches use GitHub's repository commit endpoint with the requested author and UTC range.
- GitHub searches the repository's default branch unless the API is called for another SHA. This agent
  therefore reports commits reachable through the repository view returned by GitHub; it is not an
  exhaustive scan of every unmerged branch.
- Merge commits (commits with more than one parent) are excluded.
- A squash merge is a normal single-parent commit. It counts when GitHub links that commit's author to
  the requested login; its additions and deletions are the squash commit's totals.
- Commits whose email is not linked by GitHub to the requested account are excluded, even if the commit
  name or email text appears similar. The agent does not guess identity from an unlinked email.
- Lines changed equals additions plus deletions. GitHub's per-commit statistics are the source.

## Pull requests and reviews

- `pull_requests_opened` counts PRs authored by the member whose `created_at` is inside the UTC month.
- `pull_requests_merged` counts authored PRs whose `merged_at` is inside the UTC month.
- Reviews count submitted review events by the member with `submitted_at` inside the UTC month.
- PR additions, deletions, and changed files come from the PR detail response.

## Workflows

- Workflow runs count runs whose actor is the member and whose creation time is inside the UTC month.
- Missing Actions permission is a partial repository warning; it does not invent a zero-confidence value.

## Repository scope and forks

- Explicit repository configuration is used exactly as supplied.
- Organization discovery excludes repositories marked as forks and repositories marked disabled.
- Activity occurring only in a fork is not counted unless that fork is explicitly configured.
- Repository access failures produce an incomplete report with structured warnings. Incomplete reports
  are never stored as final cache entries.
