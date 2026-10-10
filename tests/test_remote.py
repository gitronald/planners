"""Tests for ``planners.remote`` and the ``remote`` command."""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app
from planners.remote import RemoteKind, classify, effects, gh_hosts, url_host
from tests.helpers import git, init_git, write_script

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
        ("C:\\repos\\x.git", None),
        ("C:/repos/x.git", None),
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


def test_classify_knows_github_s_ssh_over_https_host(tmp_path: Path) -> None:
    root = _repo_with_origin(
        tmp_path / "repo", "ssh://git@ssh.github.com:443/owner/repo.git"
    )
    assert classify(root).kind is RemoteKind.github


def _fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_script(bin_dir / "ssh", body)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_classify_resolves_an_ssh_config_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ssh(tmp_path, monkeypatch, 'echo "user git"\necho "hostname github.com"\n')
    root = _repo_with_origin(tmp_path / "repo", "git@gh-work:owner/repo.git")
    origin = classify(root)
    assert (origin.kind, origin.host) == (RemoteKind.github, "github.com")


def test_classify_keeps_the_name_when_ssh_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ssh(tmp_path, monkeypatch, "exit 255\n")
    root = _repo_with_origin(tmp_path / "repo", "git@gh-work:owner/repo.git")
    origin = classify(root)
    assert (origin.kind, origin.host) == (RemoteKind.bare, "gh-work")


def test_classify_does_not_ask_ssh_about_https(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ssh(tmp_path, monkeypatch, 'echo "hostname github.com"\n')
    root = _repo_with_origin(tmp_path / "repo", "https://gitlab.com/owner/repo")
    assert classify(root).kind is RemoteKind.other_forge


@pytest.mark.parametrize("value", ["Single-Branch", "single_branch"])
def test_the_override_is_forgiving_about_spelling(value: str, tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    git(root, "config", "planners.remoteKind", value)
    assert classify(root).kind is RemoteKind.single_branch


def _commit_config(root: Path, body: str) -> None:
    path = root / ".planners" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_the_committed_config_overrides_the_table(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://git.example.org/o/r")
    _commit_config(root, '[remote]\nkind = "single-branch"\n')
    origin = classify(root)
    assert (origin.kind, origin.source) == (
        RemoteKind.single_branch,
        ".planners/config.toml",
    )


def test_the_committed_config_is_found_from_a_subdirectory(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    _commit_config(root, '[remote]\nkind = "bare"\n')
    sub = root / "src"
    sub.mkdir()
    assert classify(sub).kind is RemoteKind.bare


def test_git_config_wins_over_the_committed_config(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    _commit_config(root, '[remote]\nkind = "single-branch"\n')
    git(root, "config", "planners.remoteKind", "github")
    origin = classify(root)
    assert (origin.kind, origin.source) == (
        RemoteKind.github,
        "git config planners.remoteKind",
    )


@pytest.mark.parametrize(
    ("body", "note"),
    [
        ('[remote]\nkind = "gitlab"\n', "remote.kind in .planners/config.toml"),
        ("[remote\n", ".planners/config.toml cannot be read"),
    ],
)
def test_a_bad_committed_config_is_ignored_with_a_note(
    body: str, note: str, tmp_path: Path
) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    _commit_config(root, body)
    origin = classify(root)
    assert origin.kind is RemoteKind.github
    assert origin.note is not None and note in origin.note


def test_a_config_without_a_remote_table_is_no_override(tmp_path: Path) -> None:
    root = _repo_with_origin(tmp_path / "repo", "https://github.com/owner/repo")
    _commit_config(root, "[other]\nkey = 1\n")
    origin = classify(root)
    assert (origin.kind, origin.note) == (RemoteKind.github, None)


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
