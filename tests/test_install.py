"""Tests for the skillstub holder and pre-commit wiring."""

import re
import subprocess
from pathlib import Path

import pytest

from planners import install as install_mod
from planners.install import (
    GITATTRIBUTES_REL,
    HOLDER,
    HOLDER_REL,
    HOOK_ID,
    INDEX_ATTR_LINE,
    INDEX_ATTR_PATTERN,
    INDEX_MERGE_ATTR,
    RULE,
    RULE_REL,
    RuleCheck,
    SkillStub,
    _precommit_hook_block,
    _recover_mode,
    activate_precommit,
    artifact_path,
    bare_cli_available,
    both_holders_present,
    check,
    check_artifact,
    check_gitattributes,
    check_holder,
    check_rule,
    ensure_precommit_dependency,
    holder_path,
    installed_index_attr,
    invocation,
    is_generated_artifact,
    is_generated_holder,
    remove_stale,
    remove_stale_holder,
    render_holder,
    render_rule,
    report_hook,
    resolve_installed,
    resolve_installed_holder,
    resolve_mode,
    superseded_legacy_rule,
    wire_gitattributes,
    wire_precommit,
    write_artifact,
    write_holder,
)
from planners.skill import SKILL_NAMES

# The two generated artifacts share one path/stamp/drift/cleanup layer; the
# file-machinery tests run over both so neither can silently diverge.
_ARTIFACTS = [
    pytest.param(HOLDER, HOLDER_REL, id="holder"),
    pytest.param(RULE, RULE_REL, id="rule"),
]


def test_precommit_hook_regex_matches_only_plan_dir_level() -> None:
    # The hook's files: regex must match exactly .planners/plans/<NNN-slug>/plan.md
    # and nothing nested deeper — a non-matching (drifted) regex would silently
    # disable validation, and an over-broad one would block commits of sidecar
    # files named plan.md inside a plan directory.
    line = next(
        ln for ln in _precommit_hook_block("local").splitlines() if "files:" in ln
    )
    rx = re.compile(line.split("files:", 1)[1].strip())
    assert rx.match(".planners/plans/001-foo/plan.md")
    # a sidecar plan.md nested below the plan dir must NOT be swept in
    assert not rx.match(".planners/plans/001-foo/notes/plan.md")
    # the old flat layout path must not match
    assert not rx.match("docs/plans/001-foo.md")


def test_render_is_deterministic_and_version_stamped() -> None:
    first = render_holder("1.2.3")
    assert render_holder("1.2.3") == first  # no clock / no randomness
    assert "planners 1.2.3" in first
    assert "name: planners" in first
    assert "description:" in first
    assert "install --check" in first
    for sub in SKILL_NAMES:
        assert f"`{sub}`" in first


def test_description_absorbs_union_of_triggers() -> None:
    desc = SkillStub(version="0").description
    for phrase in (
        "plan",
        "implement",
        "close",
        "pipeline",
        "index",
        "backfill",
        "retire",
    ):
        assert phrase in desc


def test_check_reports_missing_then_ok_then_drifted(
    tmp_path: Path, monkeypatch
) -> None:
    # $HOME must be isolated: check() resolves the global holder first, so without
    # this it would consult the real ~/.claude/skills/planners/SKILL.md and break
    # the moment a global holder is installed (exactly when this feature is used).
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert check(repo, "1.0.0") == "missing"

    write_holder(repo, "1.0.0")
    assert check(repo, "1.0.0") == "ok"

    # a different version is drift (the stamp changes)
    assert check(repo, "2.0.0") == "drifted"

    # hand-editing the holder is drift
    path = holder_path(repo, "local")
    path.write_text(path.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    assert check(repo, "1.0.0") == "drifted"


def test_write_holder_creates_parents(tmp_path: Path) -> None:
    path = write_holder(tmp_path, "1.0.0")
    assert path.exists()
    assert path == tmp_path / ".claude" / "skills" / "planners" / "SKILL.md"


def test_wire_precommit_creates_config_when_absent(tmp_path: Path) -> None:
    assert wire_precommit(tmp_path) is True
    config = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert HOOK_ID in config
    # second run is a no-op
    assert wire_precommit(tmp_path) is False
    assert (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8") == config


def test_wire_precommit_appends_to_existing_config(tmp_path: Path) -> None:
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text("repos:\n  - repo: local\n    hooks: []\n", encoding="utf-8")
    assert wire_precommit(tmp_path) is True
    text = config.read_text(encoding="utf-8")
    assert HOOK_ID in text
    assert text.startswith("repos:")
    assert wire_precommit(tmp_path) is False


# --- mode: invocation prefix -------------------------------------------------


def test_invocation_prefix_per_mode() -> None:
    assert invocation("local") == "uv run planners"
    assert invocation("global") == "planners"


def test_holder_uses_mode_correct_invocation_and_stamp() -> None:
    local = render_holder("1.0.0", "local")
    assert "uv run planners install --check" in local
    assert "uv run planners skill <sub>" in local
    assert "uv run planners index ." in local
    assert "(mode=local)" in local

    glob = render_holder("1.0.0", "global")
    # bare `planners`, never the `uv run` prefix, under global
    assert "uv run planners" not in glob
    assert "planners install --check" in glob
    assert "planners skill <sub>" in glob
    assert "planners index ." in glob
    assert "(mode=global)" in glob


def test_precommit_entry_is_mode_aware() -> None:
    assert "entry: uv run planners validate" in _precommit_hook_block("local")
    assert "entry: planners validate" in _precommit_hook_block("global")


# --- mode: recovery, resolution, and drift -----------------------------------


def test_recover_mode_from_stamp_and_none_when_unstamped() -> None:
    assert _recover_mode(render_holder("1.0.0", "local")) == "local"
    assert _recover_mode(render_holder("1.0.0", "global")) == "global"
    assert _recover_mode("a holder with no mode stamp") is None


def test_holder_path_global_lives_under_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows parity
    assert (
        holder_path(tmp_path, "global")
        == tmp_path / ".claude" / "skills" / "planners" / "SKILL.md"
    )


def test_check_recovers_global_mode_without_passing_the_flag(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    write_holder(repo, "1.0.0", "global")
    # check() is no-arg: it must recover global from the stamp and report ok.
    assert check(repo, "1.0.0") == "ok"
    assert check(repo, "2.0.0") == "drifted"


def test_resolve_prefers_global_over_local(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    write_holder(repo, "1.0.0", "local")
    write_holder(repo, "1.0.0", "global")
    found = resolve_installed_holder(repo)
    assert found is not None
    _, mode = found
    assert mode == "global"


def test_check_holder_is_mode_specific(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    write_holder(repo, "1.0.0", "local")
    assert check_holder(repo, "1.0.0", "local") == "ok"
    # the global holder doesn't exist yet -> missing for that mode
    assert check_holder(repo, "1.0.0", "global") == "missing"


# --- mode: switching and PATH ------------------------------------------------


def test_remove_stale_holder_only_drops_local_on_global_install(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    local = write_holder(repo, "1.0.0", "local")
    write_holder(repo, "1.0.0", "global")

    removed = remove_stale_holder(repo, "global")
    assert removed == local
    assert not local.exists()
    # the global holder survives — it serves every other repo
    assert holder_path(repo, "global").exists()

    # a local install never removes the global holder
    assert remove_stale_holder(repo, "local") is None
    assert holder_path(repo, "global").exists()


def test_remove_stale_holder_noop_when_root_is_home(
    tmp_path: Path, monkeypatch
) -> None:
    # Running a global install from $HOME makes the local and global holder
    # paths coincide; remove_stale_holder must NOT delete the global holder it
    # was just handed (otherwise the global install ends up with no holder).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    holder = write_holder(tmp_path, "1.0.0", "global")
    assert holder == holder_path(tmp_path, "local")  # paths coincide
    assert remove_stale_holder(tmp_path, "global") is None
    assert holder.exists()


def test_remove_stale_holder_refuses_foreign_file(tmp_path: Path, monkeypatch) -> None:
    # A non-planners file sitting at the local holder path must never be deleted
    # — only a file carrying our generated marker is ours to remove.
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    foreign = holder_path(repo, "local")
    foreign.parent.mkdir(parents=True)
    foreign.write_text("name: planners\n\nsomeone else's skill\n", encoding="utf-8")
    assert remove_stale_holder(repo, "global") is None
    assert foreign.exists()


def test_remove_stale_holder_refuses_symlink(tmp_path: Path, monkeypatch) -> None:
    # The local holder path being a symlink must not cause an unlink that could
    # traverse the link; refuse and leave both the link and its target intact.
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    target = tmp_path / "real-holder.md"
    target.write_text(render_holder("1.0.0", "local"), encoding="utf-8")
    link = holder_path(repo, "local")
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    assert remove_stale_holder(repo, "global") is None
    assert link.is_symlink()
    assert target.exists()


def test_is_generated_holder_distinguishes_ours_from_foreign(tmp_path: Path) -> None:
    ours = tmp_path / "ours.md"
    ours.write_text(render_holder("1.0.0", "local"), encoding="utf-8")
    assert is_generated_holder(ours) is True

    foreign = tmp_path / "foreign.md"
    foreign.write_text("name: planners\nbody\n", encoding="utf-8")
    assert is_generated_holder(foreign) is False

    assert is_generated_holder(tmp_path / "missing.md") is False
    assert is_generated_holder(tmp_path) is False  # a directory


def test_wire_precommit_resyncs_entry_on_mode_switch(tmp_path: Path) -> None:
    assert wire_precommit(tmp_path, "local") is True
    config = tmp_path / ".pre-commit-config.yaml"
    assert "entry: uv run planners validate" in config.read_text(encoding="utf-8")

    # switching to global rewrites the entry rather than no-opping on HOOK_ID
    assert wire_precommit(tmp_path, "global") is True
    text = config.read_text(encoding="utf-8")
    assert "entry: planners validate" in text
    assert "entry: uv run planners validate" not in text

    # and it's idempotent once already in the new mode
    assert wire_precommit(tmp_path, "global") is False


def test_wire_precommit_keeps_entry_when_not_resyncing(tmp_path: Path) -> None:
    # resync=False is the same-mode re-install case: an entry already in the
    # other invocation form is a deliberate committed choice and must be left
    # alone rather than rewritten to match the install mode.
    assert wire_precommit(tmp_path, "local") is True
    config = tmp_path / ".pre-commit-config.yaml"
    assert "entry: uv run planners validate" in config.read_text(encoding="utf-8")

    assert wire_precommit(tmp_path, "global", resync=False) is False
    text = config.read_text(encoding="utf-8")
    assert "entry: uv run planners validate" in text
    assert "entry: planners validate" not in text


def test_resolve_mode_honors_stamp_over_location(tmp_path: Path, monkeypatch) -> None:
    # A holder sitting at the GLOBAL location but stamped local must resolve as
    # local — the stamp is authoritative (matches check()), not the location.
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    glob = holder_path(repo, "global")
    glob.parent.mkdir(parents=True)
    glob.write_text(render_holder("9.9.9", "local"), encoding="utf-8")
    assert resolve_mode(repo) == "local"


def test_resolve_mode_defaults_global_without_holder(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert resolve_mode(repo) == "global"


def test_both_holders_present(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert both_holders_present(repo) is False
    write_holder(repo, "1.0.0", "local")
    assert both_holders_present(repo) is False  # only local
    write_holder(repo, "1.0.0", "global")
    assert both_holders_present(repo) is True  # both, distinct paths

    # when the root is $HOME the two paths coincide -> not "both"
    assert both_holders_present(home) is False


def test_bare_cli_available_reflects_path(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/planners")
    assert bare_cli_available() is True
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert bare_cli_available() is False


# --- hook activation ---------------------------------------------------------


def test_activate_precommit_reports_already_active(tmp_path: Path, monkeypatch) -> None:
    # An existing registered hook is reported without re-running the installer.
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: True)
    monkeypatch.setattr(
        install_mod,
        "_run_precommit_install",
        lambda _root: pytest.fail("must not shell out when already active"),
    )
    assert activate_precommit(tmp_path) == "already_active"


def test_activate_precommit_config_only_when_not_attempted(tmp_path: Path) -> None:
    # --no-activate: never shells out, reports config_only.
    assert activate_precommit(tmp_path, attempt=False) == "config_only"


def test_activate_precommit_config_only_when_not_a_git_repo(
    tmp_path: Path, monkeypatch
) -> None:
    # No .git: pre-commit install would fail anyway, so the shell-out is skipped.
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: False)
    monkeypatch.setattr(
        install_mod,
        "_run_precommit_install",
        lambda _root: pytest.fail("must not shell out outside a git repo"),
    )
    assert activate_precommit(tmp_path) == "config_only"


def test_activate_precommit_activated_when_install_succeeds(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: False)
    # Pin core.hooksPath as unset: activate_precommit now consults it (real git
    # config) before shelling out, so without this the developer's own global
    # core.hooksPath would flip this to hookspath_blocked.
    monkeypatch.setattr(install_mod, "core_hookspath_set", lambda _root: False)
    monkeypatch.setattr(install_mod, "_run_precommit_install", lambda _root: True)
    assert activate_precommit(tmp_path) == "activated"


def test_activate_precommit_config_only_when_install_fails(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: False)
    monkeypatch.setattr(install_mod, "core_hookspath_set", lambda _root: False)
    monkeypatch.setattr(install_mod, "_run_precommit_install", lambda _root: False)
    assert activate_precommit(tmp_path) == "config_only"


def test_run_precommit_install_is_best_effort(tmp_path: Path, monkeypatch) -> None:
    # A missing tool (FileNotFoundError) and a non-zero exit both degrade to
    # False rather than raising, so install never crashes on a fresh consumer.
    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(install_mod.proc, "run", missing)
    assert install_mod._run_precommit_install(tmp_path) is False

    class _Fail:
        returncode = 1

    monkeypatch.setattr(install_mod.proc, "run", lambda *_a, **_k: _Fail())
    assert install_mod._run_precommit_install(tmp_path) is False

    class _Ok:
        returncode = 0

    monkeypatch.setattr(install_mod.proc, "run", lambda *_a, **_k: _Ok())
    assert install_mod._run_precommit_install(tmp_path) is True


def test_ensure_precommit_dependency_is_best_effort(
    tmp_path: Path, monkeypatch
) -> None:
    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(install_mod.proc, "run", missing)
    assert ensure_precommit_dependency(tmp_path) is False

    class _Fail:
        returncode = 1

    monkeypatch.setattr(install_mod.proc, "run", lambda *_a, **_k: _Fail())
    assert ensure_precommit_dependency(tmp_path) is False

    class _Ok:
        returncode = 0

    monkeypatch.setattr(install_mod.proc, "run", lambda *_a, **_k: _Ok())
    assert ensure_precommit_dependency(tmp_path) is True


def test_precommit_hook_registered_detects_marker(tmp_path: Path) -> None:
    # A real repo anchors detection at tmp_path. Detection now routes through
    # `git rev-parse` (to honour core.hooksPath), and a synthetic .git dir would
    # let rev-parse escape upward into an ambient repo above tmp_path; a real repo
    # is found at tmp_path first, so the test is immune to that.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    hooks = tmp_path / ".git" / "hooks"
    assert install_mod._precommit_hook_registered(tmp_path) is False
    (hooks / "pre-commit").write_text(
        "#!/bin/sh\n# File generated by pre-commit\n", encoding="utf-8"
    )
    assert install_mod._precommit_hook_registered(tmp_path) is True
    # an unrelated hand-written hook is not our pre-commit hook
    (hooks / "pre-commit").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    assert install_mod._precommit_hook_registered(tmp_path) is False


def test_precommit_hook_registered_resolves_worktree_gitdir(tmp_path: Path) -> None:
    # In a linked worktree, `.git` is a FILE pointing at the real git dir; the
    # hook lives under that gitdir, not <root>/.git/hooks. Without resolving the
    # pointer this returns False forever and re-runs needlessly re-activate.
    real_gitdir = tmp_path / "main" / ".git" / "worktrees" / "wt"
    (real_gitdir / "hooks").mkdir(parents=True)
    (real_gitdir / "hooks" / "pre-commit").write_text(
        "#!/bin/sh\n# File generated by pre-commit\n", encoding="utf-8"
    )
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {real_gitdir}\n", encoding="utf-8")
    assert install_mod._precommit_hook_registered(wt) is True


def test_is_git_repo_detects_dir_and_worktree_file(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert install_mod.is_git_repo(plain) is False
    (plain / ".git").mkdir()
    assert install_mod.is_git_repo(plain) is True
    # a linked worktree's `.git` file also counts as a git repo
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /somewhere/.git/worktrees/wt\n", encoding="utf-8")
    assert install_mod.is_git_repo(wt) is True


# --- core.hooksPath: detection and activation --------------------------------

_PRECOMMIT_HOOK = "#!/bin/sh\n# File generated by pre-commit\n"


def _git_init(path: Path) -> None:
    """Initialize a real git repo at ``path`` (the only way to test hooksPath)."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _set_hookspath(path: Path, value: str) -> None:
    subprocess.run(["git", "config", "core.hooksPath", value], cwd=path, check=True)


def test_effective_hooks_dir_honors_core_hookspath(tmp_path: Path) -> None:
    _git_init(tmp_path)
    # default: the effective hooks dir is <root>/.git/hooks
    assert install_mod._effective_hooks_dir(tmp_path) == tmp_path / ".git" / "hooks"
    # a relative core.hooksPath resolves against the repo root
    _set_hookspath(tmp_path, "custom-hooks")
    assert install_mod._effective_hooks_dir(tmp_path) == tmp_path / "custom-hooks"
    # an absolute core.hooksPath is honored verbatim
    abs_hooks = tmp_path / "abs-hooks"
    _set_hookspath(tmp_path, str(abs_hooks))
    assert install_mod._effective_hooks_dir(tmp_path) == abs_hooks


def test_effective_hooks_dir_falls_back_on_nonzero_exit(
    tmp_path: Path, monkeypatch
) -> None:
    # git present but failing (a non-repo / synthetic scaffold) -> pure-Python
    # fallback. Forced deterministically via a stubbed non-zero result rather than
    # relying on a real `git rev-parse` actually failing: a synthetic .git dir does
    # NOT stop git's upward discovery, so a real call would resolve to an ambient
    # repo above tmp_path if one exists (e.g. `pytest --basetemp` inside a checkout).
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    class _Fail:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(install_mod.proc, "run", lambda *_a, **_k: _Fail())
    assert install_mod._effective_hooks_dir(tmp_path) == tmp_path / ".git" / "hooks"


def test_effective_hooks_dir_falls_back_when_git_missing(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(install_mod.proc, "run", missing)
    assert install_mod._effective_hooks_dir(tmp_path) == tmp_path / ".git" / "hooks"


def test_precommit_hook_registered_honors_core_hookspath(tmp_path: Path) -> None:
    _git_init(tmp_path)
    hooks = tmp_path / "custom-hooks"
    hooks.mkdir()
    _set_hookspath(tmp_path, "custom-hooks")
    # nothing installed at the configured path yet
    assert install_mod._precommit_hook_registered(tmp_path) is False
    # a pre-commit hook living at the configured core.hooksPath IS detected, even
    # though it is not under .git/hooks (the field case)
    (hooks / "pre-commit").write_text(_PRECOMMIT_HOOK, encoding="utf-8")
    assert install_mod._precommit_hook_registered(tmp_path) is True
    # and a stale hook left at the default .git/hooks must NOT count once
    # core.hooksPath points elsewhere — detection follows the override, not .git
    default = tmp_path / ".git" / "hooks"
    default.mkdir(parents=True, exist_ok=True)
    (default / "pre-commit").write_text(_PRECOMMIT_HOOK, encoding="utf-8")
    (hooks / "pre-commit").unlink()
    assert install_mod._precommit_hook_registered(tmp_path) is False


def test_core_hookspath_set_detects_any_value(tmp_path: Path) -> None:
    _git_init(tmp_path)
    assert install_mod.core_hookspath_set(tmp_path) is False
    # even the default path counts: pre-commit refuses whenever it is set at all
    _set_hookspath(tmp_path, ".git/hooks")
    assert install_mod.core_hookspath_set(tmp_path) is True


def test_core_hookspath_set_best_effort_when_git_missing(
    tmp_path: Path, monkeypatch
) -> None:
    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(install_mod.proc, "run", missing)
    assert install_mod.core_hookspath_set(tmp_path) is False


def test_activate_precommit_hookspath_blocked_without_shelling_out(
    tmp_path: Path, monkeypatch
) -> None:
    # core.hooksPath set + hook not yet registered: `pre-commit install` is
    # guaranteed to refuse, so activation short-cuts to hookspath_blocked and must
    # NOT shell out to the doomed install.
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: False)
    monkeypatch.setattr(install_mod, "core_hookspath_set", lambda _root: True)
    monkeypatch.setattr(
        install_mod,
        "_run_precommit_install",
        lambda _root: pytest.fail("must not shell out when core.hooksPath blocks it"),
    )
    assert install_mod.activate_precommit(tmp_path) == "hookspath_blocked"


def test_activate_precommit_already_active_beats_hookspath_check(
    tmp_path: Path, monkeypatch
) -> None:
    # A hook already live (at any path) reports already_active and never reaches
    # the core.hooksPath check — the ordering guard that keeps a live hook at a
    # configured hooksPath from being mislabeled "blocked".
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: True)
    monkeypatch.setattr(
        install_mod,
        "core_hookspath_set",
        lambda _root: pytest.fail("already_active must short-circuit first"),
    )
    assert install_mod.activate_precommit(tmp_path) == "already_active"


def test_activate_precommit_already_active_at_custom_hookspath_end_to_end(
    tmp_path: Path,
) -> None:
    # The field case, end to end with a real repo and no monkeypatching: a
    # pre-commit hook living at a configured core.hooksPath is reported
    # already_active — not a false config_only that re-attempts a doomed install.
    _git_init(tmp_path)
    hooks = tmp_path / "myhooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text(_PRECOMMIT_HOOK, encoding="utf-8")
    _set_hookspath(tmp_path, "myhooks")
    assert install_mod.activate_precommit(tmp_path) == "already_active"


# --- GeneratedArtifact: holder and rule share one file layer -----------------


def _home_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Isolated ``$HOME`` + a repo dir, the setup the artifact tests share."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home, repo


@pytest.mark.parametrize(("art", "rel"), _ARTIFACTS)
def test_artifact_path_local_and_global(art, rel, tmp_path: Path, monkeypatch) -> None:
    home, repo = _home_repo(tmp_path, monkeypatch)
    assert artifact_path(repo, "local", art) == repo / rel
    assert artifact_path(repo, "global", art) == home / rel


@pytest.mark.parametrize(("art", "rel"), _ARTIFACTS)
def test_write_artifact_creates_parents_and_stamps(
    art, rel, tmp_path: Path, monkeypatch
) -> None:
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    path = write_artifact(repo, "1.0.0", "local", art)
    assert path == repo / rel
    text = path.read_text(encoding="utf-8")
    assert "generated by planners 1.0.0" in text  # the shared stamp
    assert "(mode=local)" in text


@pytest.mark.parametrize(("art", "rel"), _ARTIFACTS)
def test_check_artifact_missing_ok_drifted(
    art, rel, tmp_path: Path, monkeypatch
) -> None:
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    assert check_artifact(repo, "1.0.0", "local", art) == "missing"
    write_artifact(repo, "1.0.0", "local", art)
    assert check_artifact(repo, "1.0.0", "local", art) == "ok"
    assert check_artifact(repo, "2.0.0", "local", art) == "drifted"  # version stamp


@pytest.mark.parametrize(("art", "rel"), _ARTIFACTS)
def test_check_artifact_reports_directory_as_drifted(
    art, rel, tmp_path: Path, monkeypatch
) -> None:
    """A directory squatting at the artifact path is drift, never a crash."""
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    path = artifact_path(repo, "local", art)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()  # something foreign (not our plain file) sits where art belongs
    assert check_artifact(repo, "1.0.0", "local", art) == "drifted"


@pytest.mark.parametrize(("art", "rel"), _ARTIFACTS)
def test_resolve_installed_prefers_global(
    art, rel, tmp_path: Path, monkeypatch
) -> None:
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    assert resolve_installed(repo, art) is None
    write_artifact(repo, "1.0.0", "local", art)
    write_artifact(repo, "1.0.0", "global", art)
    found = resolve_installed(repo, art)
    assert found is not None
    assert found[1] == "global"


@pytest.mark.parametrize(("art", "rel"), _ARTIFACTS)
def test_remove_stale_drops_local_on_global_switch(
    art, rel, tmp_path: Path, monkeypatch
) -> None:
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    local = write_artifact(repo, "1.0.0", "local", art)
    write_artifact(repo, "1.0.0", "global", art)
    removed = remove_stale(repo, "global", art)
    assert removed == local
    assert not local.exists()
    # the global copy survives — it serves every other repo
    assert artifact_path(repo, "global", art).exists()
    # a local install never removes the global copy
    assert remove_stale(repo, "local", art) is None


def test_render_rule_stamp_and_mode_correct_invocation() -> None:
    local = render_rule("1.0.0", "local")
    assert local.startswith("<!-- generated by planners 1.0.0 (mode=local)")
    assert "# Plan Files" in local
    assert "`uv run planners index .`" in local

    glob = render_rule("1.0.0", "global")
    assert "(mode=global)" in glob
    assert "uv run planners" not in glob
    assert "`planners index .`" in glob


def test_is_generated_artifact_distinguishes_ours_from_foreign(tmp_path: Path) -> None:
    ours = tmp_path / "ours.md"
    ours.write_text(render_rule("1.0.0", "local"), encoding="utf-8")
    assert is_generated_artifact(ours) is True

    foreign = tmp_path / "foreign.md"
    foreign.write_text("# Plan Files\n\nhand-written\n", encoding="utf-8")
    assert is_generated_artifact(foreign) is False

    assert is_generated_artifact(tmp_path / "missing.md") is False
    assert is_generated_artifact(tmp_path) is False  # a directory


def test_superseded_legacy_rule_detects_handmaintained_plan_files(
    tmp_path: Path, monkeypatch
) -> None:
    home, repo = _home_repo(tmp_path, monkeypatch)
    # nothing to supersede yet
    assert superseded_legacy_rule(repo, "local") is None

    legacy = repo / ".claude" / "rules" / "plan-files.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Plan Files\n", encoding="utf-8")
    assert superseded_legacy_rule(repo, "local") == legacy
    # global mode looks under $HOME, not the repo
    assert superseded_legacy_rule(repo, "global") is None

    glob_legacy = home / ".claude" / "rules" / "plan-files.md"
    glob_legacy.parent.mkdir(parents=True)
    glob_legacy.write_text("# Plan Files\n", encoding="utf-8")
    assert superseded_legacy_rule(repo, "global") == glob_legacy


def test_check_rule_missing_when_neither_location_has_it(
    tmp_path: Path, monkeypatch
) -> None:
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    result = check_rule(repo, "1.0.0")
    assert result == RuleCheck("missing", {})


def test_check_rule_finds_local_only_rule(tmp_path: Path, monkeypatch) -> None:
    # A local-only rule (no holder, no global rule) is FOUND, not misreported
    # missing — the bug where the holder-resolved mode fell back to global and
    # looked only under $HOME.
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    write_artifact(repo, "1.0.0", "local", RULE)
    assert check_rule(repo, "1.0.0") == RuleCheck("ok", {"local": "ok"})


def test_check_rule_finds_global_only_rule(tmp_path: Path, monkeypatch) -> None:
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    write_artifact(repo, "1.0.0", "global", RULE)
    assert check_rule(repo, "1.0.0") == RuleCheck("ok", {"global": "ok"})


def test_check_rule_drifted_for_stale_local_after_global_switch(
    tmp_path: Path, monkeypatch
) -> None:
    # The case that slipped through as ok: a current global rule plus a STALE
    # per-repo rule (old version stamp) left behind by a switch to global. Both are
    # auto-loaded, so the stale local one is real drift and is named per location.
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    write_artifact(repo, "1.0.0", "global", RULE)  # current global rule
    write_artifact(repo, "0.9.0", "local", RULE)  # stale per-repo leftover
    assert check_rule(repo, "1.0.0") == RuleCheck(
        "drifted", {"global": "ok", "local": "drifted"}
    )


def test_check_rule_counts_coinciding_paths_once(tmp_path: Path, monkeypatch) -> None:
    # When the repo root IS $HOME the global and local paths coincide; only one
    # location is inspected so a single rule is not double-counted.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    write_artifact(home, "1.0.0", "global", RULE)
    assert check_rule(home, "1.0.0") == RuleCheck("ok", {"global": "ok"})


def test_check_rule_flags_content_ok_local_rule_as_stale_under_global_holder(
    tmp_path: Path, monkeypatch
) -> None:
    # The stale-leftover case content drift alone misses: a per-repo rule whose
    # content still EXACTLY matches its render, left behind after the repo switched
    # to global (a global holder pins it). It is an extra rule auto-loaded
    # alongside the global one, so it is drifted even though check_artifact(local)
    # on its own would call it ok.
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    write_holder(repo, "1.0.0", "global")  # repo is genuinely global
    write_artifact(repo, "1.0.0", "global", RULE)  # canonical global rule, ok
    write_artifact(repo, "1.0.0", "local", RULE)  # current-content per-repo leftover
    # the local file matches its own render — not *content* drift...
    assert check_artifact(repo, "1.0.0", "local", RULE) == "ok"
    # ...but check_rule flags it as a stale leftover under the global holder
    assert check_rule(repo, "1.0.0") == RuleCheck(
        "drifted", {"global": "ok", "local": "drifted"}
    )


def test_check_rule_local_install_rule_is_not_stale(
    tmp_path: Path, monkeypatch
) -> None:
    # The asymmetry guard from the local side: a normal local install (local
    # holder + content-ok local rule) reads ok — the stale-leftover flag fires
    # only under a *global* holder, never a local one.
    _home_repo(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    write_holder(repo, "1.0.0", "local")
    write_artifact(repo, "1.0.0", "local", RULE)
    assert check_rule(repo, "1.0.0") == RuleCheck("ok", {"local": "ok"})


# --- .gitattributes: the index's merge semantics ------------------------------


def _attrs(root: Path) -> str:
    return (root / GITATTRIBUTES_REL).read_text(encoding="utf-8")


def test_wire_gitattributes_creates_file_when_absent(tmp_path: Path) -> None:
    assert wire_gitattributes(tmp_path) is True
    assert _attrs(tmp_path) == INDEX_ATTR_LINE + "\n"
    # second run is a no-op that changes nothing
    assert wire_gitattributes(tmp_path) is False
    assert _attrs(tmp_path) == INDEX_ATTR_LINE + "\n"


def test_wire_gitattributes_appends_and_preserves_other_attributes(
    tmp_path: Path,
) -> None:
    # The file is repo content: an unrelated attribute a repo already set must
    # survive, the way wire_precommit preserves entries already in the config.
    existing = "*.png binary\n*.md text\n"
    (tmp_path / GITATTRIBUTES_REL).write_text(existing, encoding="utf-8")
    assert wire_gitattributes(tmp_path) is True
    assert _attrs(tmp_path) == existing + INDEX_ATTR_LINE + "\n"
    assert wire_gitattributes(tmp_path) is False


def test_wire_gitattributes_adds_missing_trailing_newline(tmp_path: Path) -> None:
    # Without this the appended line would be glued onto the last attribute,
    # silently rewriting *that* pattern's attributes.
    (tmp_path / GITATTRIBUTES_REL).write_text("*.png binary", encoding="utf-8")
    assert wire_gitattributes(tmp_path) is True
    assert _attrs(tmp_path) == "*.png binary\n" + INDEX_ATTR_LINE + "\n"


def test_wire_gitattributes_leaves_a_different_attribute_alone(tmp_path: Path) -> None:
    # A line naming the index but granting something else (e.g. the hand-rolled
    # merge=ours stopgap) is deliberate repo content: report it, don't clobber it.
    stopgap = f"{INDEX_ATTR_PATTERN} merge=ours\n"
    (tmp_path / GITATTRIBUTES_REL).write_text(stopgap, encoding="utf-8")
    assert wire_gitattributes(tmp_path) is False
    assert _attrs(tmp_path) == stopgap
    assert check_gitattributes(tmp_path) == "drifted"


def test_wire_gitattributes_force_rewrites_only_that_line(tmp_path: Path) -> None:
    (tmp_path / GITATTRIBUTES_REL).write_text(
        f"*.png binary\n{INDEX_ATTR_PATTERN} merge=ours\n*.md text\n", encoding="utf-8"
    )
    assert wire_gitattributes(tmp_path, force=True) is True
    assert _attrs(tmp_path) == f"*.png binary\n{INDEX_ATTR_LINE}\n*.md text\n"
    assert check_gitattributes(tmp_path) == "ok"


def test_check_gitattributes_missing_ok_drifted(tmp_path: Path) -> None:
    assert check_gitattributes(tmp_path) == "missing"  # no file at all
    (tmp_path / GITATTRIBUTES_REL).write_text("*.png binary\n", encoding="utf-8")
    assert check_gitattributes(tmp_path) == "missing"  # file, but not our pattern
    wire_gitattributes(tmp_path)
    assert check_gitattributes(tmp_path) == "ok"


def test_index_attr_matching_ignores_comments_and_extra_whitespace(
    tmp_path: Path,
) -> None:
    # A commented-out line must not read as present (that would leave the repo
    # with no attribute and install reporting success); a real line with padded
    # whitespace is the same line to git, so it must not read as drift.
    (tmp_path / GITATTRIBUTES_REL).write_text(
        f"# {INDEX_ATTR_LINE}\n", encoding="utf-8"
    )
    assert check_gitattributes(tmp_path) == "missing"
    (tmp_path / GITATTRIBUTES_REL).write_text(
        f"  {INDEX_ATTR_PATTERN}   {INDEX_MERGE_ATTR}  \n", encoding="utf-8"
    )
    assert check_gitattributes(tmp_path) == "ok"
    assert wire_gitattributes(tmp_path) is False


def test_index_attr_is_a_builtin_driver_needing_no_per_clone_config() -> None:
    # The whole reason this is one committed line and not three parts: `union` is
    # built into git, so a fresh clone that never ran `install` still merges the
    # index cleanly. A driver that needs `git config merge.<name>.driver` would be
    # inert until someone ran that command by hand — the invisible failure plan
    # 004 rejected. Pin the value so a future edit has to face that.
    assert INDEX_MERGE_ATTR == "merge=union"


def test_installed_index_attr_reports_what_is_there(tmp_path: Path) -> None:
    assert installed_index_attr(tmp_path) is None
    (tmp_path / GITATTRIBUTES_REL).write_text(
        f"{INDEX_ATTR_PATTERN}  merge=ours\n", encoding="utf-8"
    )
    assert installed_index_attr(tmp_path) == f"{INDEX_ATTR_PATTERN} merge=ours"


def test_unreadable_gitattributes_is_reported_not_clobbered(tmp_path: Path) -> None:
    # An unreadable file must not read as `missing`: that is the state install
    # repairs by *writing the line*, and writing it here would replace bytes
    # nothing has seen. Reported as its own status, and left on disk untouched.
    config = tmp_path / GITATTRIBUTES_REL
    original = b"*.png binary\n\xff\xfe not utf-8\n"
    config.write_bytes(original)

    assert check_gitattributes(tmp_path) == "unreadable"
    assert installed_index_attr(tmp_path) is None
    assert wire_gitattributes(tmp_path) is False
    assert config.read_bytes() == original


def test_force_does_not_overwrite_an_unreadable_gitattributes(tmp_path: Path) -> None:
    # --force rewrites a line install has *read*; it is not a licence to discard
    # a file it could not read. Before the guard this path raised instead.
    config = tmp_path / GITATTRIBUTES_REL
    original = b"\xff\xfe not utf-8\n"
    config.write_bytes(original)
    assert wire_gitattributes(tmp_path, force=True) is False
    assert config.read_bytes() == original


# --- report_hook: the per-clone registration --check can see -----------------


def test_report_hook_names_a_missing_config_before_a_missing_hook(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    assert report_hook(tmp_path) == "config_missing"


def test_report_hook_not_registered_when_config_present_but_hook_absent(
    tmp_path: Path,
) -> None:
    # The fresh-clone case: the config is committed and travels, the registration
    # does not — so validation silently never fires.
    _git_init(tmp_path)
    wire_precommit(tmp_path)
    assert report_hook(tmp_path) == "not_registered"


def test_report_hook_active_when_the_hook_is_registered(tmp_path: Path) -> None:
    _git_init(tmp_path)
    wire_precommit(tmp_path)
    (tmp_path / ".git" / "hooks" / "pre-commit").write_text(
        _PRECOMMIT_HOOK, encoding="utf-8"
    )
    assert report_hook(tmp_path) == "active"


def test_report_hook_blames_hookspath_when_it_blocks_registration(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    wire_precommit(tmp_path)
    _set_hookspath(tmp_path, "myhooks")
    assert report_hook(tmp_path) == "hookspath_blocked"


def test_report_hook_no_git_repo(tmp_path: Path) -> None:
    wire_precommit(tmp_path)
    assert report_hook(tmp_path) == "no_git_repo"


def test_report_hook_does_not_call_a_foreign_precommit_hook_ours(
    tmp_path: Path,
) -> None:
    # A repo that already used pre-commit for its own hooks (ruff, say) has the
    # git hook registered while `planners-validate` is nowhere in the config.
    # Testing registration first reported "active" for a hook that cannot fire —
    # the exact silence report_hook exists to break — because
    # _precommit_hook_registered answers "is pre-commit wired in", not "will our
    # hook run".
    _git_init(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: ruff\n", encoding="utf-8"
    )
    (tmp_path / ".git" / "hooks" / "pre-commit").write_text(
        _PRECOMMIT_HOOK, encoding="utf-8"
    )
    assert HOOK_ID not in (tmp_path / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert report_hook(tmp_path) == "config_missing"


def test_report_hook_survives_an_unreadable_config(tmp_path: Path) -> None:
    # --check must degrade to a reported status, never a traceback: a config that
    # is not valid UTF-8 is a config that does not name the hook.
    _git_init(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_bytes(b"repos: \xff\xfe not utf-8\n")
    assert report_hook(tmp_path) == "config_missing"


def test_index_attr_matching_obeys_the_last_line_like_git(tmp_path: Path) -> None:
    # git resolves attributes by the LAST matching line, so a file that grants
    # union and then ours is a repo running `ours` — which silently drops the
    # incoming branch's rows. Reading the first match would report it `ok`.
    (tmp_path / GITATTRIBUTES_REL).write_text(
        f"{INDEX_ATTR_LINE}\n{INDEX_ATTR_PATTERN} merge=ours\n", encoding="utf-8"
    )
    assert installed_index_attr(tmp_path) == f"{INDEX_ATTR_PATTERN} merge=ours"
    assert check_gitattributes(tmp_path) == "drifted"

    # and --force rewrites the line git actually obeys, restoring `ok`
    assert wire_gitattributes(tmp_path, force=True) is True
    assert check_gitattributes(tmp_path) == "ok"
