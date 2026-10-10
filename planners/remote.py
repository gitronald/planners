"""What kind of remote ``origin`` is, and so what the lifecycle can ask of it.

The lifecycle was written for a GitHub ``origin`` that ``gh`` can reach: a draft
PR at ``implement``, an upstream for the feature branch at ``implemented``, a
routine push of the base at ``activate``. Other remotes break each of those in a
different way. A hosted document editor's git bridge accepts one branch only,
and every push to it lands in the document collaborators are editing; another
forge reviews through a different tool; a bare repo has no review surface at
all.

:func:`classify` names the kind from the URL and config alone. It never contacts
the remote. The host table below is the one place host knowledge lives. Two
overrides outrank it, for a host the table does not know: ``kind`` under
``[remote]`` in the committed ``.planners/config.toml``, shared by every clone,
and the per-clone ``planners.remoteKind`` git config key, which wins over both.
"""

from __future__ import annotations

import enum
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from planners import proc

__all__ = [
    "CONFIG_FILE",
    "CONFIG_KEY",
    "Remote",
    "RemoteKind",
    "classify",
    "effects",
    "gh_hosts",
    "url_host",
]

# The per-clone override: `git config planners.remoteKind single-branch`.
CONFIG_KEY = "planners.remoteKind"

# The committed override, repo-relative: `[remote]` then `kind = "single-branch"`.
CONFIG_FILE = Path(".planners/config.toml")


class RemoteKind(enum.StrEnum):
    """How far the lifecycle can lean on ``origin``."""

    github = "github"
    single_branch = "single-branch"
    other_forge = "other-forge"
    bare = "bare"
    none = "none"


# Hosts whose git endpoint accepts a single branch, so a feature branch cannot be
# pushed and every push publishes into a live document.
_SINGLE_BRANCH = {
    # Overleaf's git bridge: "The Overleaf Git system does not support
    # branching", and a push updates the project collaborators have open.
    # Source: https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/git
    "git.overleaf.com",
}

# Forges where branches push normally but review is not a GitHub PR, so `gh`
# cannot open or ready one.
_OTHER_FORGE = {
    # GitLab merge requests (glab). Source: https://docs.gitlab.com/user/project/merge_requests/
    "gitlab.com",
    # Bitbucket pull requests, no gh. Source: https://support.atlassian.com/bitbucket-cloud/
    "bitbucket.org",
    # Forgejo (Codeberg) and Gitea pull requests (tea). Source: https://docs.codeberg.org/
    "codeberg.org",
    "gitea.com",
    # SourceHut reviews by emailed patches. Source: https://man.sr.ht/git.sr.ht/
    "git.sr.ht",
}

_GITHUB = "github.com"

# Other names github.com answers to. `ssh.github.com` serves SSH over port 443.
# Source: https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port
_GITHUB_ALIASES = {"ssh.github.com", "www.github.com"}

# `scheme://[user@]host[:port]/...`
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?(?P<host>\[[^\]]+\]|[^:/]+)", re.I)
# scp-like `[user@]host:path`, which git takes only when no slash precedes the colon.
_SCP = re.compile(r"^(?:[^@/]*@)?(?P<host>[^:/]+):(?!//)")
# A Windows drive path (`C:\\repo`, `C:/repo`), which the scp pattern would read
# as host `c`; git itself treats a one-letter "host" this way.
_DRIVE = re.compile(r"^[a-z]:[\\/]", re.I)


@dataclass(frozen=True)
class Remote:
    """``origin``'s kind, and what it was decided from.

    ``host`` is ``None`` for a local path or no remote; for an SSH URL it is the
    host the SSH config resolves the name to. ``source`` says which rule
    decided the kind, so a surprising answer can be traced. ``note`` carries a
    warning to show, e.g. an override that names no kind.
    """

    kind: RemoteKind
    url: str | None
    host: str | None
    source: str
    note: str | None = None


def url_host(url: str) -> str | None:
    """The lower-cased host in a git remote URL, or ``None`` for a local path."""
    url = url.strip()
    if url.lower().startswith("file://") or _DRIVE.match(url):
        return None
    for pattern in (_URL, _SCP):
        match = pattern.match(url)
        if match:
            return match.group("host").strip("[]").lower()
    return None


def _is_ssh(url: str) -> bool:
    """Whether git reaches ``url`` over SSH, where the host may be a config alias."""
    lowered = url.lower()
    if lowered.startswith(("ssh://", "git+ssh://", "ssh+git://")):
        return True
    return "://" not in url and _SCP.match(url) is not None


def _ssh_hostname(root: Path, host: str) -> str:
    """The host an SSH config alias stands for, via ``ssh -G``, else ``host``.

    ``ssh -G`` only evaluates the config and prints the result; it opens no
    connection. A missing ``ssh`` or a failure leaves the name as written.
    """
    try:
        result = proc.run(root, ["ssh", "-G", host], capture_output=True)
    except OSError:
        return host
    if result.returncode != 0:
        return host
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition(" ")
        if key == "hostname" and value.strip():
            return value.strip().lower()
    return host


def _gh_config_dir() -> Path:
    """Where ``gh`` keeps ``hosts.yml``, by the precedence ``gh`` itself uses."""
    if explicit := os.environ.get("GH_CONFIG_DIR"):
        return Path(explicit)
    if xdg := os.environ.get("XDG_CONFIG_HOME"):
        return Path(xdg) / "gh"
    return Path.home() / ".config" / "gh"


def gh_hosts() -> set[str]:
    """The hosts ``gh`` is configured for: ``github.com`` plus any enterprise host.

    Read from ``GH_HOST`` and the top-level keys of ``gh``'s ``hosts.yml``. A
    missing or unreadable file contributes nothing, so a machine without ``gh``
    still classifies ``github.com``.
    """
    hosts = {_GITHUB}
    if env := os.environ.get("GH_HOST"):
        hosts.add(env.strip().lower())
    try:
        text = (_gh_config_dir() / "hosts.yml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return hosts
    for line in text.splitlines():
        match = re.match(r"^([^\s#:][^:]*):\s*$", line)
        if match:
            hosts.add(match.group(1).strip().strip("'\"").lower())
    return hosts


def _parse_kind(value: str, where: str) -> tuple[RemoteKind | None, str | None]:
    """``value`` as a kind, forgiving case and ``_``, or a note naming ``where``."""
    try:
        return RemoteKind(value.strip().lower().replace("_", "-")), None
    except ValueError:
        choices = ", ".join(kind.value for kind in RemoteKind)
        return None, f"{where} is '{value}', not one of {choices}; ignored"


def _committed_kind(root: Path) -> tuple[RemoteKind | None, str | None]:
    """The kind ``[remote] kind`` names in the committed config file, if any."""
    top = proc.git_out(root, ["rev-parse", "--show-toplevel"])
    path = (Path(top.strip()) if top else root) / CONFIG_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return None, f"{CONFIG_FILE.as_posix()} cannot be read ({exc}); ignored"
    remote = data.get("remote")
    value = remote.get("kind") if isinstance(remote, dict) else None
    if value is None:
        return None, None
    return _parse_kind(str(value), f"remote.kind in {CONFIG_FILE.as_posix()}")


def _override(root: Path) -> tuple[RemoteKind | None, str, str | None]:
    """The overriding kind, where it came from, and any note on a bad value.

    The per-clone git key wins over the committed file, so one clone can differ
    from what the repo says without a commit.
    """
    notes: list[str] = []
    value = proc.git_out(root, ["config", "--get", CONFIG_KEY])
    if value is not None and value.strip():
        kind, note = _parse_kind(value.strip(), CONFIG_KEY)
        if kind is not None:
            return kind, f"git config {CONFIG_KEY}", None
        notes.append(note or "")
    kind, note = _committed_kind(root)
    if note:
        notes.append(note)
    if kind is not None:
        return kind, CONFIG_FILE.as_posix(), "; ".join(notes) or None
    return None, "", "; ".join(notes) or None


def classify(root: Path) -> Remote:
    """Classify the ``origin`` remote of the repo at ``root``, offline.

    An override wins: the ``planners.remoteKind`` git key, then ``[remote] kind``
    in ``.planners/config.toml``. Otherwise no ``origin`` is
    ``none``, a host ``gh`` is configured for is ``github``, the host table
    decides the known single-branch hosts and forges, and anything else, a local
    path included, is ``bare``.
    """
    url = proc.git_out(root, ["remote", "get-url", "origin"])
    url = url.strip() if url is not None else None
    host = url_host(url) if url else None
    if url and host is not None and _is_ssh(url):
        host = _ssh_hostname(root, host)
    kind, source, note = _override(root)
    if kind is not None:
        return Remote(kind, url, host, source, note)
    if not url:
        return Remote(RemoteKind.none, None, None, "no origin remote", note)
    if host is None:
        return Remote(RemoteKind.bare, url, None, "local path", note)
    if host in gh_hosts() or host in _GITHUB_ALIASES:
        return Remote(RemoteKind.github, url, host, "gh host", note)
    if host in _SINGLE_BRANCH:
        return Remote(RemoteKind.single_branch, url, host, "host table", note)
    if host in _OTHER_FORGE:
        return Remote(RemoteKind.other_forge, url, host, "host table", note)
    return Remote(RemoteKind.bare, url, host, "unknown host", note)


def effects(kind: RemoteKind) -> list[str]:
    """What the lifecycle does differently for ``kind``, one line per difference."""
    no_pr = "no PR: implement skips the draft PR; close uses the no-PR path"
    if kind is RemoteKind.github:
        return ["PR: implement opens a draft PR with gh; close merges it"]
    if kind is RemoteKind.single_branch:
        return [
            no_pr,
            "no feature-branch push: implemented checks only uncommitted changes",
            "base push publishes live: ask before pushing the base",
        ]
    if kind is RemoteKind.none:
        return [
            "no remote: nothing to push or review; close uses the no-PR path",
        ]
    return [
        no_pr,
        "feature-branch push optional: implemented does not require an upstream",
    ]
