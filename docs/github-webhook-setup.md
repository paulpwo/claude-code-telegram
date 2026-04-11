# GitHub Webhook Setup — Automatic SDD Analysis

This document explains how to configure a GitHub webhook so that the bot
automatically triggers an SDD pre-analysis whenever a qualifying issue is
created or labeled.

---

## How it works

When GitHub sends an `issues` webhook event to `/webhooks/github`, the bot
checks whether the event should trigger an automatic SDD analysis.  Two
actions are handled:

| Action | Trigger condition |
|--------|------------------|
| `opened` | Issue was just created and already has the required label |
| `labeled` | A label was added to an existing issue and it matches the required label |

When the condition is met:
1. An immediate Telegram notification is sent ("SDD auto-analysis started").
2. Claude runs the same workflow as `/sdd <issue-url>`:
   - Creates a branch (`Feat/Issue7FixLogin`, etc.)
   - Writes `.agent/planning/sdd.md`, `.agent/context/files.md`, `.agent/context/approach.md`
   - Commits and pushes the branch
3. Claude's summary is delivered to the configured Telegram chats.

---

## Prerequisites

- The bot must be reachable from the internet (or use a tunnel for local dev).
- `ENABLE_API_SERVER=true` in your `.env`.
- `GITHUB_WEBHOOK_SECRET` must match the secret you set in GitHub.
- `ENABLE_ISSUE_WEBHOOK=true` in your `.env`.

---

## GitHub configuration (Settings → Webhooks)

1. Go to your repository → **Settings** → **Webhooks** → **Add webhook**.
2. Fill in the form:

   | Field | Value |
   |-------|-------|
   | **Payload URL** | `https://<your-domain>/webhooks/github` |
   | **Content type** | `application/json` |
   | **Secret** | A random string (copy it — you'll put it in `.env`) |
   | **Which events?** | Select *Let me select individual events* → tick **Issues** |
   | **Active** | ✅ |

3. Click **Add webhook**.  GitHub will send a `ping` event — the bot returns
   `200 OK` for all successfully verified requests.

---

## Option A — With label (recommended)

Only issues that carry the label `sdd-analyze` (or your configured label)
trigger the analysis.  This lets you opt-in per issue.

**.env settings:**

```dotenv
ENABLE_ISSUE_WEBHOOK=true
ISSUE_WEBHOOK_REQUIRE_LABEL=true
ISSUE_WEBHOOK_LABEL=sdd-analyze        # create this label in your repo
ISSUE_WEBHOOK_REPO_ALLOWLIST=          # empty = all repos allowed
```

**How to trigger:**

- **At creation**: open the issue and add the label `sdd-analyze` before
  submitting (or edit + save immediately after).
- **After creation**: add the label `sdd-analyze` to any existing issue — the
  `labeled` event fires and triggers the analysis.

---

## Option B — Without label (all new issues)

Every new issue triggers an automatic analysis.  Suitable for small repos
where every issue is SDD-worthy.

**.env settings:**

```dotenv
ENABLE_ISSUE_WEBHOOK=true
ISSUE_WEBHOOK_REQUIRE_LABEL=false
ISSUE_WEBHOOK_REPO_ALLOWLIST=owner/my-repo   # restrict to one repo (optional)
```

> **Warning**: with `ISSUE_WEBHOOK_REQUIRE_LABEL=false` and an empty
> allowlist, *every* issue opened in *any* repo that sends webhooks to this
> bot will trigger a Claude run.  Use `ISSUE_WEBHOOK_REPO_ALLOWLIST` to
> restrict to specific repos.

---

## Environment variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_ISSUE_WEBHOOK` | `false` | Master switch for the feature |
| `ISSUE_WEBHOOK_REQUIRE_LABEL` | `true` | Only process labeled issues |
| `ISSUE_WEBHOOK_LABEL` | `sdd-analyze` | Label name that activates analysis |
| `ISSUE_WEBHOOK_REPO_ALLOWLIST` | *(empty)* | Comma-separated `owner/repo` list; empty = all repos |
| `GITHUB_WEBHOOK_SECRET` | *(required)* | HMAC secret set in GitHub webhook settings |
| `ENABLE_API_SERVER` | `false` | Must be `true` to receive webhooks |
| `API_SERVER_PORT` | `8080` | Port the FastAPI server listens on |
| `NOTIFICATION_CHAT_IDS` | *(empty)* | Comma-separated Telegram chat IDs for notifications |

---

## Testing locally with `gh webhook forward`

The GitHub CLI can forward webhooks from GitHub to your local bot without
exposing a public URL:

```bash
# Requires: gh auth login + gh extension install github/gh-webhook
gh webhook forward \
  --repo=owner/my-repo \
  --events=issues \
  --url=http://localhost:8080/webhooks/github
```

> `gh webhook forward` does **not** send HMAC signatures, so you may need to
> temporarily set `GITHUB_WEBHOOK_SECRET` to an empty string and relax
> signature verification for local testing — or use a tool like `ngrok`
> instead to get a real HTTPS URL.

### With ngrok

```bash
ngrok http 8080
# Copy the https URL and set it as the Payload URL in GitHub
```

---

## Verifying it works

1. Set all required env vars and restart the bot.
2. Create a new GitHub issue (Option A: add the `sdd-analyze` label).
3. Check the bot logs for:
   ```
   GitHub issue webhook filter result  should_trigger=True reason=ok
   SDD analysis triggered from GitHub issue webhook  repo=owner/repo  issue_number=7
   ```
4. You should receive a Telegram notification within seconds and a Claude
   response within 1–2 minutes (depending on repo size).
5. Check the repo — a new branch `Feat/Issue7...` should exist with `.agent/`
   documents committed.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| 401 from webhook | Wrong secret | Match `GITHUB_WEBHOOK_SECRET` with GitHub |
| 500 from webhook | Secret not configured | Set `GITHUB_WEBHOOK_SECRET` in `.env` |
| No Telegram message | `NOTIFICATION_CHAT_IDS` empty | Set at least one chat ID |
| Analysis runs but no branch | `gh` CLI not authenticated | Run `gh auth login` in the bot env |
| Every issue triggers, not just labeled | `ISSUE_WEBHOOK_REQUIRE_LABEL=false` | Set to `true` |
