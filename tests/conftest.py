"""Shared pytest fixtures.

Hook detection and activation shell out to git (``git rev-parse``,
``git config``), so the suite has to be insulated from the machine's git
environment on two axes:

* **Ambient config.** git reads the developer's *global* and *system* config by
  default. A contributor with a global ``core.hooksPath`` set (e.g. a global
  pre-commit setup) would otherwise see it leak in and flip outcomes —
  ``activate_precommit`` would report ``hookspath_blocked`` where a test expects
  ``activated``/``config_only``.
* **Ambient repo discovery.** ``git rev-parse`` walks *up* the directory tree to
  find a repository. If pytest's temp dirs happen to live inside a real git repo
  (e.g. ``pytest --basetemp=./tmp`` run inside the checkout, or a ``$TMPDIR``
  under a repo), a test that uses a synthetic or absent ``.git`` would resolve to
  the *enclosing* repo's hooks and mis-detect the validate hook as already
  active. Capping discovery at the temp-dir boundary keeps each test anchored to
  the repo it actually created.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Insulate every test from the machine's ambient git config and repos.

    Local (per-repo) config — which tests set themselves via ``git config`` in a
    repo they created — is unaffected, and a real repo created at or below
    ``tmp_path`` is still discovered; only escape *above* the test's temp dir is
    blocked.
    """
    empty = tmp_path / ".gitconfig-empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    # Stop `git rev-parse`/discovery from walking above the per-test temp dir into
    # any repo that encloses pytest's basetemp. The ceiling is the temp dir's
    # parent so the test's own repo (at tmp_path or below) is still found.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
