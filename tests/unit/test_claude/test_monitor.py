"""Test bash directory boundary checking and git safety."""

from pathlib import Path
from unittest.mock import patch

from src.claude.monitor import (
    _is_claude_internal_path,
    check_bash_directory_boundary,
    check_git_safety,
)


class TestCheckBashDirectoryBoundary:
    """Test the check_bash_directory_boundary function."""

    def setup_method(self) -> None:
        self.approved = Path("/root/projects")
        self.cwd = Path("/root/projects/myapp")

    def test_mkdir_outside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "mkdir -p /root/web1", self.cwd, self.approved
        )
        assert not valid
        assert "directory boundary violation" in error.lower()
        assert "/root/web1" in error

    def test_mkdir_inside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "mkdir -p /root/projects/newdir", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_touch_outside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "touch /tmp/evil.txt", self.cwd, self.approved
        )
        assert not valid
        assert "/tmp/evil.txt" in error

    def test_cp_outside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "cp file.txt /etc/passwd", self.cwd, self.approved
        )
        assert not valid
        assert "/etc/passwd" in error

    def test_mv_outside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "mv /root/projects/file.txt /tmp/file.txt", self.cwd, self.approved
        )
        assert not valid
        assert "/tmp/file.txt" in error

    def test_relative_paths_inside_approved_pass(self) -> None:
        valid, error = check_bash_directory_boundary(
            "mkdir -p subdir/nested", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_relative_path_traversal_escaping_approved_dir(self) -> None:
        """mkdir ../../evil from /root/projects/myapp resolves to /root/evil."""
        valid, error = check_bash_directory_boundary(
            "mkdir ../../evil", self.cwd, self.approved
        )
        assert not valid
        assert "directory boundary violation" in error.lower()
        assert "../../evil" in error

    def test_relative_path_traversal_staying_inside_approved_dir(self) -> None:
        """mkdir ../sibling from /root/projects/myapp -> /root/projects/sibling (ok)."""
        valid, error = check_bash_directory_boundary(
            "mkdir ../sibling", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_relative_path_dot_dot_at_boundary_root(self) -> None:
        """mkdir .. from approved root itself should be blocked."""
        cwd_at_root = Path("/root/projects")
        valid, error = check_bash_directory_boundary(
            "touch ../outside.txt", cwd_at_root, self.approved
        )
        assert not valid
        assert "directory boundary violation" in error.lower()

    def test_read_only_commands_pass(self) -> None:
        for cmd in ["cat /etc/hosts", "ls /tmp", "head /var/log/syslog"]:
            valid, error = check_bash_directory_boundary(cmd, self.cwd, self.approved)
            assert valid, f"Expected read-only command to pass: {cmd}"
            assert error is None

    def test_non_fs_commands_pass(self) -> None:
        """Commands not in the filesystem-modifying set pass through."""
        for cmd in ["python script.py", "node app.js", "cargo build"]:
            valid, error = check_bash_directory_boundary(cmd, self.cwd, self.approved)
            assert valid, f"Expected non-fs command to pass: {cmd}"
            assert error is None

    def test_empty_command(self) -> None:
        valid, error = check_bash_directory_boundary("", self.cwd, self.approved)
        assert valid
        assert error is None

    def test_flags_are_skipped(self) -> None:
        valid, error = check_bash_directory_boundary(
            "mkdir -p -v /root/projects/dir", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_unparseable_command_passes_through(self) -> None:
        """Malformed quoting should pass through (sandbox catches it at OS level)."""
        valid, error = check_bash_directory_boundary(
            "mkdir 'unclosed quote", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_rm_outside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "rm /var/tmp/somefile", self.cwd, self.approved
        )
        assert not valid
        assert "/var/tmp/somefile" in error

    def test_ln_outside_approved_directory(self) -> None:
        valid, error = check_bash_directory_boundary(
            "ln -s /root/projects/file /tmp/link", self.cwd, self.approved
        )
        assert not valid
        assert "/tmp/link" in error

    # --- find command handling ---

    def test_find_without_mutating_flags_passes(self) -> None:
        """Plain find (read-only) should pass regardless of search path."""
        valid, error = check_bash_directory_boundary(
            "find /tmp -name '*.log'", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_find_delete_outside_approved_dir(self) -> None:
        """find /tmp -delete should be blocked because /tmp is outside."""
        valid, error = check_bash_directory_boundary(
            "find /tmp -name '*.log' -delete", self.cwd, self.approved
        )
        assert not valid
        assert "directory boundary violation" in error.lower()
        assert "/tmp" in error

    def test_find_exec_outside_approved_dir(self) -> None:
        """find /var -exec rm {} ; should be blocked."""
        valid, error = check_bash_directory_boundary(
            "find /var -exec rm {} ;", self.cwd, self.approved
        )
        assert not valid
        assert "/var" in error

    def test_find_delete_inside_approved_dir(self) -> None:
        """find inside approved dir with -delete should pass."""
        valid, error = check_bash_directory_boundary(
            "find /root/projects/myapp -name '*.pyc' -delete",
            self.cwd,
            self.approved,
        )
        assert valid
        assert error is None

    def test_find_delete_relative_path_inside(self) -> None:
        """find . -delete from inside approved dir should pass."""
        valid, error = check_bash_directory_boundary(
            "find . -name '*.pyc' -delete", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_find_execdir_outside_approved_dir(self) -> None:
        """find with -execdir outside approved dir should be blocked."""
        valid, error = check_bash_directory_boundary(
            "find /etc -execdir cat {} ;", self.cwd, self.approved
        )
        assert not valid
        assert "/etc" in error

    # --- cd and command chaining handling ---

    def test_cd_outside_approved_directory(self) -> None:
        """cd to an outside directory should be blocked."""
        valid, error = check_bash_directory_boundary("cd /tmp", self.cwd, self.approved)
        assert not valid
        assert "directory boundary violation" in error.lower()
        assert "/tmp" in error

    def test_cd_inside_approved_directory(self) -> None:
        """cd to an inside directory should pass."""
        valid, error = check_bash_directory_boundary(
            "cd subdir", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_chained_commands_outside_blocked(self) -> None:
        """Any command in a chain targeting outside should be blocked."""
        # Chained with &&
        valid, error = check_bash_directory_boundary(
            "ls && rm /etc/passwd", self.cwd, self.approved
        )
        assert not valid
        assert "/etc/passwd" in error

        # Chained with ;
        valid, error = check_bash_directory_boundary(
            "mkdir newdir; mv file.txt /tmp/", self.cwd, self.approved
        )
        assert not valid
        assert "/tmp/" in error

    def test_chained_commands_inside_pass(self) -> None:
        """Chain of valid commands should pass."""
        valid, error = check_bash_directory_boundary(
            "cd subdir && touch file.txt && ls -la", self.cwd, self.approved
        )
        assert valid
        assert error is None

    def test_chained_cd_outside_blocked(self) -> None:
        """cd /tmp && something should be blocked."""
        valid, error = check_bash_directory_boundary(
            "cd /tmp && ls", self.cwd, self.approved
        )
        assert not valid
        assert "/tmp" in error


class TestIsClaudeInternalPath:
    """Test the _is_claude_internal_path helper function."""

    def test_plan_file_is_internal(self, tmp_path: Path) -> None:
        """~/.claude/plans/some-plan.md should be recognised as internal."""
        with patch("src.claude.monitor.Path.home", return_value=tmp_path):
            (tmp_path / ".claude" / "plans").mkdir(parents=True)
            plan_file = tmp_path / ".claude" / "plans" / "my-plan.md"
            plan_file.touch()
            assert _is_claude_internal_path(str(plan_file)) is True

    def test_todo_file_is_internal(self, tmp_path: Path) -> None:
        """~/.claude/todos/todo.md should be recognised as internal."""
        with patch("src.claude.monitor.Path.home", return_value=tmp_path):
            (tmp_path / ".claude" / "todos").mkdir(parents=True)
            todo_file = tmp_path / ".claude" / "todos" / "todo.md"
            todo_file.touch()
            assert _is_claude_internal_path(str(todo_file)) is True

    def test_settings_json_is_internal(self, tmp_path: Path) -> None:
        """~/.claude/settings.json should be recognised as internal."""
        with patch("src.claude.monitor.Path.home", return_value=tmp_path):
            (tmp_path / ".claude").mkdir(parents=True)
            settings_file = tmp_path / ".claude" / "settings.json"
            settings_file.touch()
            assert _is_claude_internal_path(str(settings_file)) is True

    def test_arbitrary_file_under_claude_dir_rejected(self, tmp_path: Path) -> None:
        """Files directly under ~/.claude/ (not in known subdirs) are rejected."""
        with patch("src.claude.monitor.Path.home", return_value=tmp_path):
            (tmp_path / ".claude").mkdir(parents=True)
            secret = tmp_path / ".claude" / "credentials.json"
            secret.touch()
            assert _is_claude_internal_path(str(secret)) is False

    def test_path_outside_claude_dir_rejected(self, tmp_path: Path) -> None:
        """Paths outside ~/.claude/ entirely are rejected."""
        with patch("src.claude.monitor.Path.home", return_value=tmp_path):
            assert _is_claude_internal_path("/etc/passwd") is False
            assert _is_claude_internal_path("/tmp/evil.txt") is False

    def test_empty_path_rejected(self, tmp_path: Path) -> None:
        """Empty paths are rejected."""
        assert _is_claude_internal_path("") is False

    def test_unknown_subdir_rejected(self, tmp_path: Path) -> None:
        """Unknown subdirectories under ~/.claude/ are rejected."""
        with patch("src.claude.monitor.Path.home", return_value=tmp_path):
            (tmp_path / ".claude" / "secrets").mkdir(parents=True)
            bad_file = tmp_path / ".claude" / "secrets" / "key.pem"
            bad_file.touch()
            assert _is_claude_internal_path(str(bad_file)) is False


class TestCheckGitSafety:
    """Tests for the check_git_safety function."""

    _PROTECTED = ["main", "develop", "master"]

    # ── Non-git commands pass through ─────────────────────────────────────────

    def test_non_git_command_passes(self) -> None:
        ok, err = check_git_safety("ls -la", self._PROTECTED, False, False)
        assert ok is True
        assert err is None

    def test_python_command_passes(self) -> None:
        ok, err = check_git_safety("python script.py", self._PROTECTED, False, False)
        assert ok is True
        assert err is None

    # ── Push to protected branch ──────────────────────────────────────────────

    def test_push_to_main_is_blocked(self) -> None:
        ok, err = check_git_safety(
            "git push origin main", self._PROTECTED, False, False
        )
        assert ok is False
        assert err is not None
        assert "main" in err

    def test_push_to_develop_is_blocked(self) -> None:
        ok, err = check_git_safety(
            "git push origin develop", self._PROTECTED, False, False
        )
        assert ok is False
        assert "develop" in err

    def test_push_to_feature_branch_is_allowed(self) -> None:
        ok, err = check_git_safety(
            "git push origin feature/my-feature", self._PROTECTED, False, False
        )
        assert ok is True
        assert err is None

    def test_push_to_branch_containing_main_as_substring_is_allowed(self) -> None:
        """'my-main-fix' must NOT be blocked when 'main' is protected."""
        ok, err = check_git_safety(
            "git push origin my-main-fix", self._PROTECTED, False, False
        )
        assert ok is True
        assert err is None

    def test_push_to_branch_with_remote_upstream_is_blocked(self) -> None:
        ok, err = check_git_safety(
            "git push upstream main", self._PROTECTED, False, False
        )
        assert ok is False
        assert err is not None

    # ── Force push ────────────────────────────────────────────────────────────

    def test_force_push_blocked_by_default(self) -> None:
        ok, err = check_git_safety(
            "git push --force origin feature/x", self._PROTECTED, False, False
        )
        assert ok is False
        assert err is not None

    def test_force_push_short_flag_blocked(self) -> None:
        ok, err = check_git_safety("git push -f", self._PROTECTED, False, False)
        assert ok is False
        assert err is not None

    def test_force_push_allowed_when_enabled(self) -> None:
        ok, err = check_git_safety(
            "git push --force origin feature/x", self._PROTECTED, True, False
        )
        assert ok is True
        assert err is None

    # ── Branch force delete ───────────────────────────────────────────────────

    def test_branch_force_delete_blocked_by_default(self) -> None:
        ok, err = check_git_safety(
            "git branch -D feature/old", self._PROTECTED, False, False
        )
        assert ok is False
        assert err is not None

    def test_branch_soft_delete_always_allowed(self) -> None:
        ok, err = check_git_safety(
            "git branch -d feature/old", self._PROTECTED, False, False
        )
        assert ok is True
        assert err is None

    def test_branch_force_delete_allowed_when_enabled(self) -> None:
        ok, err = check_git_safety(
            "git branch -D feature/old", self._PROTECTED, False, True
        )
        assert ok is True
        assert err is None

    # ── Hard reset ────────────────────────────────────────────────────────────

    def test_reset_hard_to_protected_ref_blocked(self) -> None:
        ok, err = check_git_safety(
            "git reset --hard origin/main", self._PROTECTED, False, False
        )
        assert ok is False
        assert err is not None
        assert "origin/main" in err

    def test_reset_hard_to_non_protected_ref_allowed(self) -> None:
        ok, err = check_git_safety(
            "git reset --hard HEAD~1", self._PROTECTED, False, False
        )
        assert ok is True
        assert err is None

    def test_reset_hard_to_protected_branch_by_name_blocked(self) -> None:
        ok, err = check_git_safety(
            "git reset --hard main", self._PROTECTED, False, False
        )
        assert ok is False
        assert err is not None

    # ── Empty protected branches list ─────────────────────────────────────────

    def test_push_with_empty_protected_branches_allowed(self) -> None:
        ok, err = check_git_safety("git push origin main", [], False, False)
        assert ok is True
        assert err is None
