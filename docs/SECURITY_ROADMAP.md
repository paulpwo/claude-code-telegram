# Security Roadmap — claude-code-telegram
Last updated: 2026-04-11
Audit scope: Full codebase review
Status of critical issues: Addressed in `security-hardening` SDD change (branch pending)

---

## Overview

This document tracks HIGH and MEDIUM severity vulnerabilities identified in the security audit conducted on 2026-04-11. Critical issues are handled separately under the `security-hardening` SDD change. The items below are queued for the next sprint (HIGH) and next quarter (MEDIUM).

---

## HIGH Severity — Address Next Sprint

| # | File | Issue | Fix |
|---|------|-------|-----|
| H1 | `src/projects/registry.py:90` | **Symlink path traversal** — `.resolve()` follows symlinks outside approved directory. A project dir containing a symlink to `/etc/` would let Claude read/write outside the sandbox. | Check `is_symlink()` on resolved path and all parents before accepting |
| H2 | `src/api/server.py` | **No rate limiting on `/webhooks/{provider}`** — unlimited requests can trigger repeated Claude executions and drain API budget | Add `slowapi` limiter, 10 req/min per IP |
| H3 | `src/claude/sdk_integration.py:278` | **API key stored in `os.environ` and logged** — `os.environ["ANTHROPIC_API_KEY"] = ...` is visible to all processes on the host; structlog line confirms key is set | Use `.get_secret_value()` only at call site, never store in env; remove the log line |
| H4 | `src/config/settings.py:55` | **`auth_token_secret` has no minimum strength** — accepts `"abc"`, enabling brute-force | Add validator: min 32 chars |
| H5 | `src/main.py:140` | **`InMemoryAuditStorage` in production** — all security events lost on restart, no incident investigation possible | Wire `DatabaseAuditStorage` (same pattern as sessions/messages repos) |
| H6 | `src/config/settings.py:60` | **`DISABLE_SECURITY_PATTERNS` silent** — no startup warning, no audit log entry when enabled | Log `WARNING` at startup; audit-log every request when flag is on |

### Notes on HIGH items

**H1 (Symlink traversal):** This bypasses the existing path traversal protection entirely. The `approved_directory` boundary check in the security validator operates on the resolved path, so a symlink pointing outside the boundary is silently accepted. All project directory registrations must verify that no component of the resolved path is itself a symlink before accepting the path.

**H3 (API key in env):** Pydantic `SecretStr` is already used in `settings.py` for this field, but the key is subsequently written into `os.environ` for the SDK. This defeats the protection. The key must be extracted with `.get_secret_value()` only at the point of the SDK client instantiation and never persisted in the process environment.

**H5 (Audit storage):** `InMemoryAuditStorage` loses all audit events on process restart. In a containerized deployment this means every restart wipes the security log. This is a compliance issue in any environment where incident investigation or access logging is required.

---

## MEDIUM Severity — Address Next Quarter

| # | File | Issue | Fix |
|---|------|-------|-----|
| M1 | `src/api/server.py:234` | **Webhook-triggered Claude jobs have no timeout** — malicious GitHub issue can trigger infinite/expensive Claude run | Add `timeout_seconds` to `ScheduledEvent`; default 300s |
| M2 | `src/bot/handlers/sdd_handler.py:45` | **`working_dir` in SDD prompt not validated against `APPROVED_DIRECTORY`** — path is interpolated into the Claude prompt without boundary check | Validate `working_dir` is within `approved_directory` before building prompt |

### Notes on MEDIUM items

**M1 (Webhook timeout):** A crafted GitHub issue body can trigger a Claude execution that runs indefinitely, exhausting API credits. The existing `ClaudeSDKClient` supports a timeout parameter — it needs to be wired through `ScheduledEvent` and enforced in `AgentHandler`.

**M2 (SDD working dir):** The `working_dir` value is user-controlled and passed directly into the Claude prompt string. While the Claude SDK's tool monitor enforces file path boundaries during execution, the prompt itself could mislead Claude into believing a different working directory is intended. The check should mirror the one in `SecurityValidator.validate_directory()`.

---

## What Is Already Well-Implemented

The following areas were reviewed and found to be correctly implemented:

- **SQL injection:** All database queries use parameterized statements throughout `src/storage/`. No string interpolation in SQL.
- **Path traversal (basic):** The `SecurityValidator` blocks `..` sequences and common traversal patterns. The symlink case (H1) is the only gap.
- **GitHub webhook authentication:** HMAC-SHA256 signature verification is correctly implemented in `src/api/server.py` with constant-time comparison.
- **Telegram rate limiting:** Token bucket rate limiter is implemented and active in `src/bot/middleware/`.
- **Input validation patterns:** Pattern-based blocking of shell metacharacters (`;`, `&&`, `$()`, backticks) is comprehensive — scope extension to agentic mode is tracked separately.

---

## Tracking

A GitHub issue should be created for each item above. Suggested labels: `security`, `priority:high` (for H-series), `priority:medium` (for M-series).

Suggested issue titles:
- `[Security] H1: Symlink path traversal in project registry`
- `[Security] H2: Add rate limiting to webhook endpoint`
- `[Security] H3: API key written to os.environ in sdk_integration`
- `[Security] H4: Enforce minimum length on auth_token_secret`
- `[Security] H5: Replace InMemoryAuditStorage with DatabaseAuditStorage in production`
- `[Security] H6: Warn at startup when DISABLE_SECURITY_PATTERNS is enabled`
- `[Security] M1: Add execution timeout to webhook-triggered Claude jobs`
- `[Security] M2: Validate working_dir against APPROVED_DIRECTORY in SDD handler`
