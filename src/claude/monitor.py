"""Bash directory boundary enforcement and git safety checks for Claude tool calls."""

import re
import shlex
from pathlib import Path
from typing import List, Optional, Set, Tuple

# Subdirectories under ~/.claude/ that Claude Code uses internally.
_CLAUDE_INTERNAL_SUBDIRS: Set[str] = {"plans", "todos", "settings.json"}

# Commands that modify the filesystem or change context and should have paths checked
_FS_MODIFYING_COMMANDS: Set[str] = {
    "mkdir",
    "touch",
    "cp",
    "mv",
    "rm",
    "rmdir",
    "ln",
    "install",
    "tee",
    "cd",
}

# Commands that are read-only or don't take filesystem paths
_READ_ONLY_COMMANDS: Set[str] = {
    "cat",
    "ls",
    "head",
    "tail",
    "less",
    "more",
    "which",
    "whoami",
    "pwd",
    "echo",
    "printf",
    "env",
    "printenv",
    "date",
    "wc",
    "sort",
    "uniq",
    "diff",
    "file",
    "stat",
    "du",
    "df",
    "tree",
    "realpath",
    "dirname",
    "basename",
}

# Actions / expressions that make ``find`` a filesystem-modifying command
_FIND_MUTATING_ACTIONS: Set[str] = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}

# Bash command separators
_COMMAND_SEPARATORS: Set[str] = {"&&", "||", ";", "|", "&"}

# ── Git safety regexes ────────────────────────────────────────────────────────
# Matches any command that starts with "git"
_GIT_COMMAND_RE = re.compile(r"^\s*git\s")

# Force push: git push ... --force or -f (flag anywhere in args)
_GIT_FORCE_PUSH_RE = re.compile(r"^\s*git\s+push\b.*(\s--force\b|\s-f\b)")

# Branch force delete: git branch -D <name>  (uppercase D only)
_GIT_BRANCH_DELETE_RE = re.compile(r"^\s*git\s+branch\b.*\s-D\b")

# Hard reset: git reset --hard <ref>  — captures the ref token
_GIT_RESET_HARD_RE = re.compile(r"^\s*git\s+reset\s+--hard\s+(\S+)")

# Push subcommand start — used to extract positional args
_GIT_PUSH_BRANCH_RE = re.compile(r"^\s*git\s+push\b")


def check_bash_directory_boundary(
    command: str,
    working_directory: Path,
    approved_directory: Path,
) -> Tuple[bool, Optional[str]]:
    """Check if a bash command's paths stay within the approved directory."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        # If we can't parse the command, let it through —
        # the sandbox will catch it at the OS level
        return True, None

    if not tokens:
        return True, None

    # Split tokens into individual commands based on separators
    command_chains: list[list[str]] = []
    current_chain: list[str] = []

    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current_chain:
                command_chains.append(current_chain)
            current_chain = []
        else:
            current_chain.append(token)

    if current_chain:
        command_chains.append(current_chain)

    resolved_approved = approved_directory.resolve()

    # Check each command in the chain
    for cmd_tokens in command_chains:
        if not cmd_tokens:
            continue

        base_command = Path(cmd_tokens[0]).name

        # Read-only commands are always allowed
        if base_command in _READ_ONLY_COMMANDS:
            continue

        # Determine if this specific command in the chain needs path validation
        needs_check = False
        if base_command == "find":
            needs_check = any(t in _FIND_MUTATING_ACTIONS for t in cmd_tokens[1:])
        elif base_command in _FS_MODIFYING_COMMANDS:
            needs_check = True

        if not needs_check:
            continue

        # Check each argument for paths outside the boundary
        for token in cmd_tokens[1:]:
            # Skip flags
            if token.startswith("-"):
                continue

            # Resolve both absolute and relative paths against the working
            # directory so that traversal sequences like ``../../evil`` are
            # caught instead of being silently allowed.
            try:
                if token.startswith("/"):
                    resolved = Path(token).resolve()
                else:
                    resolved = (working_directory / token).resolve()

                if not _is_within_directory(resolved, resolved_approved):
                    return False, (
                        f"Directory boundary violation: '{base_command}' targets "
                        f"'{token}' which is outside approved directory "
                        f"'{resolved_approved}'"
                    )
            except (ValueError, OSError):
                # If path resolution fails, the command might be malformed or
                # using bash features we can't statically analyze.
                # We skip checking this token and rely on the OS-level sandbox.
                continue

    return True, None


def check_git_safety(
    command: str,
    protected_branches: List[str],
    allow_force_push: bool,
    allow_delete_branch: bool,
) -> Tuple[bool, Optional[str]]:
    """Check whether a git command violates configured safety rules.

    Returns:
        (True, None) if the command is allowed.
        (False, error_message) if the command is blocked.

    Only Bash tool commands that start with ``git`` are inspected; all other
    commands pass through immediately.
    """
    # Early-exit: not a git command — nothing to check
    if not _GIT_COMMAND_RE.match(command):
        return True, None

    # ── Force push ────────────────────────────────────────────────────────────
    if not allow_force_push and _GIT_FORCE_PUSH_RE.match(command):
        return False, (
            "Operación git bloqueada: force-push deshabilitado. "
            "Configurá GIT_ALLOW_FORCE_PUSH=true para habilitarlo."
        )

    # ── Force branch delete ───────────────────────────────────────────────────
    if not allow_delete_branch and _GIT_BRANCH_DELETE_RE.match(command):
        return False, (
            "Operación git bloqueada: eliminación forzada de rama (git branch -D) "
            "deshabilitada. Configurá GIT_ALLOW_DELETE_BRANCH=true para habilitarlo."
        )

    # ── Push to protected branch ──────────────────────────────────────────────
    if protected_branches and _GIT_PUSH_BRANCH_RE.match(command):
        # Tokenise the push command to extract positional (non-flag) args.
        # git push [<remote>] [<branch>]  — the branch is the last positional arg.
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()

        # Drop the leading "git" and "push" tokens
        push_args = tokens[2:] if len(tokens) > 2 else []
        positional = [t for t in push_args if not t.startswith("-")]

        # The branch is the last positional arg (after optional remote)
        candidate = positional[-1] if positional else None

        if candidate:
            for branch in protected_branches:
                # Use whitespace-boundary anchors instead of \b so that hyphens
                # inside branch names (e.g. "my-main-fix") do not produce false
                # positives.  We compare the whole token instead.
                if candidate == branch:
                    return False, (
                        f"Operación git bloqueada: push a rama protegida '{branch}'. "
                        f"Las ramas protegidas son: {', '.join(protected_branches)}."
                    )

    # ── Hard reset to a protected ref ─────────────────────────────────────────
    reset_match = _GIT_RESET_HARD_RE.match(command)
    if reset_match:
        ref = reset_match.group(1)
        for branch in protected_branches:
            # Match exact ref or remote/branch forms (e.g. origin/main)
            if ref == branch or ref.endswith(f"/{branch}"):
                return False, (
                    f"Operación git bloqueada: reset --hard a ref protegida '{ref}'. "
                    f"Las ramas protegidas son: {', '.join(protected_branches)}."
                )

    return True, None


def _is_claude_internal_path(file_path: str) -> bool:
    """Check whether *file_path* points inside ``~/.claude/`` (allowed subdirs only)."""
    try:
        resolved = Path(file_path).resolve()
        home = Path.home().resolve()
        claude_dir = home / ".claude"

        # Path must be inside ~/.claude/
        try:
            rel = resolved.relative_to(claude_dir)
        except ValueError:
            return False

        # Must be in one of the known subdirectories (or a known file)
        top_part = rel.parts[0] if rel.parts else ""
        return top_part in _CLAUDE_INTERNAL_SUBDIRS

    except Exception:
        return False


def _is_within_directory(path: Path, directory: Path) -> bool:
    """Check if path is within directory."""
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False
