from github_team_stats import full_version
from github_team_stats.cli import _parser


def test_version_includes_commit(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_MEMBER_ACTIVITY_BUILD_COMMIT", "abc123")
    import github_team_stats

    monkeypatch.setattr(github_team_stats, "__commit__", "abc123")
    assert full_version() == "0.8.1+abc123"
    with __import__("pytest").raises(SystemExit) as stopped:
        _parser().parse_args(["--version"])
    assert stopped.value.code == 0
    assert "+" in capsys.readouterr().out
