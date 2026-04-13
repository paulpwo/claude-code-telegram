"""Redact well-known secret formats from text before it is persisted or logged.

This is a last-line defensive filter for the case where a user accidentally
pastes a secret into a Telegram message (typos of `/git set`, raw API keys in
prompts, etc.). The goal is *not* to detect every possible secret, only the
common well-known formats whose shape is unambiguous.

Only use this before writing to durable storage (DB) or structured logs — not
before sending to Claude, since Claude may legitimately need the literal value.
"""

import re
from typing import List, Pattern, Tuple

# (label, compiled pattern). Order matters: longer / more specific patterns
# MUST come before their shorter prefixes (e.g. Anthropic `sk-ant-...` before
# generic `sk-...`) so replacements don't collide.
_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    ("GITHUB-PAT-FINE-GRAINED", re.compile(r"github_pat_[A-Za-z0-9_]{82}")),
    ("GITHUB-PAT", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")),
    ("ANTHROPIC-KEY", re.compile(r"sk-ant-[A-Za-z0-9_-]{32,}")),
    ("OPENAI-KEY", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("AWS-ACCESS-KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SLACK-TOKEN", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("GOOGLE-API-KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
]


def scrub_secrets(text: str) -> str:
    """Return ``text`` with any well-known secret formats replaced.

    Matches are replaced with ``[REDACTED-<KIND>]``. Empty / non-string input
    is returned unchanged so callers can pass optional fields without a guard.
    """
    if not text:
        return text
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED-{label}]", text)
    return text
