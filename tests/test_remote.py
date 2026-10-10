"""Tests for ``planners.remote`` and the ``remote`` command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app
from planners.remote import RemoteKind, classify, effects, gh_hosts, url_host
from tests.helpers import git, init_git

runner = CliRunner()


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://github.com/owner/repo.git", "github.com"),
        ("https://github.com/owner/repo", "github.com"),
        ("https://user@GitHub.com/owner/repo", "github.com"),
        ("git@github.com:owner/repo.git", "github.com"),
        ("git@github.com:owner/repo", "github.com"),
        ("ssh://git@github.example.com:2222/owner/repo.git", "github.example.com"),
        ("https://git.overleaf.com/0123456789abcdef", "git.overleaf.com"),
        ("git://[::1]/repo.git", "::1"),
        ("/srv/git/repo.git", None),
        ("../repo.git", None),
        ("file:///srv/git/repo.git", None),
    ],
)
def test_url_host(url: str, host: str | None) -> None:
    assert url_host(url) == host


def _repo_with_origin(root: Path, url: str | None) -> Path:
    root.mkdir()
    init_git(root)
    if url is not None:
        git(root, "remote", "add", "origin", url)
    return root


@pytest.mark.parametrize(
    ("url", "kind", "source"),
    [
        ("https://github.com/owner/repo.git", RemoteKind.github, "gh host"),
        ("git@github.com:owner/repo", RemoteKind.github, "gh host"),
        (
            "https://git.overleaf.com/0123456789abcdef",
            RemoteKind.single_branch,
            "host table",
        ),
        ("git@gitlab.com:owner/repo.git", RemoteKind.other_forge, "host table"),
        ("https://codeberg.org/owner/repo", RemoteKind.other_forge, "host table"),
        ("ssh://git@git.example.org/srv/repo.git", RemoteKind.bare, "unknown host"),
        ("https://github.example.com/owner/repo", RemoteKind.bare, "unknown host"),
        ("/srv/git/repo.git", RemoteKind.bare, "local path"),
        (None, RemoteKind.none, "no origin remote"),
    ],
)
def test_classify(
    url: str | None, kind: RemoteKind, source: str, tmp_path: Path
) -> None:
    origin = classify(_repo_with_origin(tmp_path / "repo", url))
    assert (origin.kind, origin.source) == (kind, source)
    assert origin.note is None


def _write_gh_hosts(directory: Path, body: str) -> None:
    (directory / "hosts.yml").write_text(body, encoding="utf-8")


def test_classify_reads_an_enterprise_host_from_gh_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh_dir = tmp_path / "gh"
    gh_dir.mkdir()
    _write_gh_hosts(
        gh_dir,
        "github.com:\n    user: someone\n"
        "github.example.com:\n    git_protocol: ssh\n    users:\n        x: {}\n",
    )
    monkeypatch.setenv("GH_CONFIG_DIR", str(gh_dir))
    assert gh_hosts() == {"github.com", "github.example.com"}
    root = _repo_with_origin(tmp_path / "repo", "git@github.example.com:owner/repo")
    assert classify(root).kind is RemoteKind.github


def test_classify_reads_gh_host_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_HOST", "GitHub.Example.com")
    root = _repo_with_origin(tmp_path / "repo", "https://github.example.com/o/r")
    assert classify(root).kind is RemoteKind.github


def test_the_override_wins_over_the_table(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    git(root, "config", "planners.remoteKind", "single-branch")
    origin = classify(root)
    assert origin.kind is RemoteKind.single_branch
    assert origin.source == "git config planners.remoteKind"


def test_an_unknown_override_is_ignored_with_a_note(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    git(root, "config", "planners.remoteKind", "gitlab")
    origin = classify(root)
    assert origin.kind is RemoteKind.github
    assert origin.note is not None and "'gitlab'" in origin.note


def test_every_kind_has_effects() -> None:
    for kind in RemoteKind:
        assert effects(kind)


def test_remote_command_prints_kind_and_effects(tmp_path: Path) -> None:
    root = _repo_with_origin(
        tmp_path / "repo", "https://git.overleaf.com/0123456789abcdef"
    )
    result = runner.invoke(app, ["remote", str(root)])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "origin: single-branch (git.overleaf.com; host table)"
    assert any("no PR" in line for line in lines[1:])
    assert any("base push publishes live" in line for line in lines[1:])


def test_remote_command_json(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", None)
    result = runner.invoke(app, ["remote", str(root), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "none"
    assert data["url"] is None


def test_remote_command_warns_about_a_bad_override(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    git(root, "config", "planners.remoteKind", "nope")
    result = runner.invoke(app, ["remote", str(root)])
    assert result.exit_code == 0
    assert "warning: planners.remoteKind is 'nope'" in result.output
    assert "origin: github" in result.output
