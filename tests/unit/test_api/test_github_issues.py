"""Unit tests for the GitHub issues webhook filter and helpers.

Tests cover:
- IssueWebhookFilter.should_trigger() — all filtering combinations
- Payload helpers (_get_issue_labels, _get_labeled_label, etc.)
- build_trigger_notification() output shape
- _maybe_trigger_issue_sdd() integration with the event bus (via server)
"""

import hashlib
import hmac
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.github_issues import (
    IssueWebhookFilter,
    _get_issue_labels,
    _get_issue_number,
    _get_issue_url,
    _get_labeled_label,
    _get_repo_full_name,
    build_trigger_notification,
)
from src.api.server import create_api_app
from src.events.bus import EventBus
from src.events.types import AgentResponseEvent, ScheduledEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_issue_payload(
    action: str = "opened",
    labels: List[str] | None = None,
    repo: str = "owner/repo",
    issue_number: int = 7,
    title: str = "Fix bug in login",
    added_label: str | None = None,
    issue_url: str = "https://github.com/owner/repo/issues/7",
) -> Dict[str, Any]:
    """Build a minimal GitHub ``issues`` webhook payload."""
    label_objects = [{"name": lbl, "color": "abc"} for lbl in (labels or [])]
    payload: Dict[str, Any] = {
        "action": action,
        "issue": {
            "number": issue_number,
            "title": title,
            "body": "Detailed description",
            "html_url": issue_url,
            "labels": label_objects,
        },
        "repository": {
            "full_name": repo,
            "name": repo.split("/")[-1],
        },
    }
    if added_label is not None:
        payload["label"] = {"name": added_label, "color": "abc"}
    return payload


def _make_settings(**overrides: Any) -> MagicMock:
    settings = MagicMock()
    settings.development_mode = True
    settings.github_webhook_secret = overrides.get("github_webhook_secret", "gh-secret")
    settings.webhook_api_secret = overrides.get("webhook_api_secret", "api-secret")
    settings.api_server_port = 8080
    settings.debug = False
    settings.enable_issue_webhook = overrides.get("enable_issue_webhook", True)
    settings.issue_webhook_require_label = overrides.get(
        "issue_webhook_require_label", True
    )
    settings.issue_webhook_label = overrides.get("issue_webhook_label", "sdd-analyze")
    settings.issue_webhook_repo_allowlist = overrides.get(
        "issue_webhook_repo_allowlist", []
    )
    settings.sdd_protected_branches = overrides.get(
        "sdd_protected_branches", ["main", "master"]
    )
    settings.notification_chat_ids = overrides.get("notification_chat_ids", [123])
    settings.approved_directory = Path("/tmp")
    return settings


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Payload helper tests
# ---------------------------------------------------------------------------


class TestPayloadHelpers:
    def test_get_issue_labels_returns_names(self) -> None:
        payload = _make_issue_payload(labels=["sdd-analyze", "bug"])
        assert _get_issue_labels(payload) == ["sdd-analyze", "bug"]

    def test_get_issue_labels_empty(self) -> None:
        payload = _make_issue_payload(labels=[])
        assert _get_issue_labels(payload) == []

    def test_get_issue_labels_missing_key(self) -> None:
        assert _get_issue_labels({}) == []

    def test_get_labeled_label_present(self) -> None:
        payload = _make_issue_payload(action="labeled", added_label="sdd-analyze")
        assert _get_labeled_label(payload) == "sdd-analyze"

    def test_get_labeled_label_absent(self) -> None:
        payload = _make_issue_payload(action="opened")
        assert _get_labeled_label(payload) is None

    def test_get_repo_full_name(self) -> None:
        payload = _make_issue_payload(repo="paul/my-project")
        assert _get_repo_full_name(payload) == "paul/my-project"

    def test_get_issue_url(self) -> None:
        payload = _make_issue_payload(issue_url="https://github.com/a/b/issues/1")
        assert _get_issue_url(payload) == "https://github.com/a/b/issues/1"

    def test_get_issue_number(self) -> None:
        payload = _make_issue_payload(issue_number=42)
        assert _get_issue_number(payload) == 42


# ---------------------------------------------------------------------------
# IssueWebhookFilter tests
# ---------------------------------------------------------------------------


class TestIssueWebhookFilter:
    """Tests for all filtering combinations."""

    def _filter(self, **kwargs: Any) -> IssueWebhookFilter:
        defaults = dict(
            enabled=True,
            require_label=True,
            target_label="sdd-analyze",
            repo_allowlist=[],
        )
        defaults.update(kwargs)
        return IssueWebhookFilter(**defaults)  # type: ignore[arg-type]

    # -- feature flag --

    def test_disabled_never_triggers(self) -> None:
        f = self._filter(enabled=False)
        payload = _make_issue_payload(action="opened", labels=["sdd-analyze"])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False
        assert "disabled" in reason

    # -- event type --

    def test_non_issues_event_rejected(self) -> None:
        f = self._filter()
        ok, reason = f.should_trigger("push", {"action": "opened"})
        assert ok is False
        assert "push" in reason

    def test_pull_request_event_rejected(self) -> None:
        f = self._filter()
        payload = _make_issue_payload()
        ok, reason = f.should_trigger("pull_request", payload)
        assert ok is False

    # -- action --

    def test_closed_action_rejected(self) -> None:
        f = self._filter()
        payload = _make_issue_payload(action="closed", labels=["sdd-analyze"])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False
        assert "closed" in reason

    def test_reopened_action_rejected(self) -> None:
        f = self._filter()
        payload = _make_issue_payload(action="reopened", labels=["sdd-analyze"])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False

    # -- opened + label --

    def test_opened_with_correct_label_triggers(self) -> None:
        f = self._filter()
        payload = _make_issue_payload(action="opened", labels=["sdd-analyze"])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is True

    def test_opened_without_label_rejected_when_required(self) -> None:
        f = self._filter(require_label=True)
        payload = _make_issue_payload(action="opened", labels=["bug"])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False
        assert "label" in reason

    def test_opened_no_labels_rejected_when_required(self) -> None:
        f = self._filter(require_label=True)
        payload = _make_issue_payload(action="opened", labels=[])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False

    def test_opened_no_label_required_triggers(self) -> None:
        f = self._filter(require_label=False)
        payload = _make_issue_payload(action="opened", labels=[])
        ok, reason = f.should_trigger("issues", payload)
        assert ok is True

    # -- labeled action --

    def test_labeled_with_correct_label_triggers(self) -> None:
        f = self._filter()
        payload = _make_issue_payload(action="labeled", added_label="sdd-analyze")
        ok, reason = f.should_trigger("issues", payload)
        assert ok is True

    def test_labeled_with_wrong_label_rejected(self) -> None:
        f = self._filter()
        payload = _make_issue_payload(action="labeled", added_label="enhancement")
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False
        assert "enhancement" in reason

    def test_labeled_no_label_in_payload_rejected(self) -> None:
        f = self._filter()
        payload = _make_issue_payload(action="labeled")  # no added_label key
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False

    # -- repo allowlist --

    def test_allowlist_empty_means_all_repos_allowed(self) -> None:
        f = self._filter(repo_allowlist=[], require_label=False)
        payload = _make_issue_payload(action="opened", repo="any/repo")
        ok, _ = f.should_trigger("issues", payload)
        assert ok is True

    def test_allowlist_repo_in_list_triggers(self) -> None:
        f = self._filter(
            repo_allowlist=["owner/repo"], require_label=False
        )
        payload = _make_issue_payload(action="opened", repo="owner/repo")
        ok, _ = f.should_trigger("issues", payload)
        assert ok is True

    def test_allowlist_repo_not_in_list_rejected(self) -> None:
        f = self._filter(
            repo_allowlist=["owner/repo"], require_label=False
        )
        payload = _make_issue_payload(action="opened", repo="other/project")
        ok, reason = f.should_trigger("issues", payload)
        assert ok is False
        assert "allowlist" in reason

    def test_allowlist_is_case_insensitive(self) -> None:
        f = self._filter(repo_allowlist=["Owner/Repo"], require_label=False)
        payload = _make_issue_payload(action="opened", repo="owner/repo")
        ok, _ = f.should_trigger("issues", payload)
        assert ok is True

    # -- combined --

    def test_opened_with_label_and_allowed_repo_triggers(self) -> None:
        f = self._filter(
            require_label=True,
            target_label="sdd-analyze",
            repo_allowlist=["owner/repo"],
        )
        payload = _make_issue_payload(
            action="opened", labels=["sdd-analyze"], repo="owner/repo"
        )
        ok, _ = f.should_trigger("issues", payload)
        assert ok is True

    def test_opened_with_label_but_disallowed_repo_rejected(self) -> None:
        f = self._filter(
            require_label=True,
            target_label="sdd-analyze",
            repo_allowlist=["owner/allowed"],
        )
        payload = _make_issue_payload(
            action="opened", labels=["sdd-analyze"], repo="owner/other"
        )
        ok, _ = f.should_trigger("issues", payload)
        assert ok is False


# ---------------------------------------------------------------------------
# build_trigger_notification tests
# ---------------------------------------------------------------------------


class TestBuildTriggerNotification:
    def test_contains_issue_number(self) -> None:
        payload = _make_issue_payload(issue_number=42)
        text = build_trigger_notification(payload)
        assert "#42" in text

    def test_contains_repo_name(self) -> None:
        payload = _make_issue_payload(repo="paul/my-app")
        text = build_trigger_notification(payload)
        assert "paul/my-app" in text

    def test_contains_issue_title(self) -> None:
        payload = _make_issue_payload(title="Fix the login page")
        text = build_trigger_notification(payload)
        assert "Fix the login page" in text

    def test_contains_html_link_when_url_present(self) -> None:
        payload = _make_issue_payload(
            issue_url="https://github.com/a/b/issues/5"
        )
        text = build_trigger_notification(payload)
        assert "https://github.com/a/b/issues/5" in text

    def test_no_link_when_url_absent(self) -> None:
        payload = _make_issue_payload(issue_url="")
        payload["issue"]["html_url"] = ""
        text = build_trigger_notification(payload)
        assert "<a href=" not in text


# ---------------------------------------------------------------------------
# Server integration — events published on matching issue webhook
#
# NOTE: EventBus.publish() enqueues into an asyncio.Queue — handlers are
# only called when the bus processor loop is running.  FastAPI TestClient
# runs a synchronous ASGI transport, so the queue is never drained during
# the request.  We therefore mock event_bus.publish with an AsyncMock so
# we can inspect every call without needing the bus loop.
# ---------------------------------------------------------------------------


class TestServerIssueWebhookIntegration:
    """Verify that the server publishes the right events for issue webhooks."""

    def _post_issue_webhook(
        self,
        client: TestClient,
        payload: Dict[str, Any],
        secret: str = "gh-secret",
        event_type: str = "issues",
        delivery_id: str = "delivery-001",
    ) -> Any:
        import json

        body = json.dumps(payload).encode()
        sig = _sign(body, secret)
        return client.post(
            "/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": event_type,
                "X-GitHub-Delivery": delivery_id,
            },
        )

    def _make_bus_with_mock_publish(self) -> tuple[EventBus, AsyncMock]:
        """Return a bus whose publish() is replaced with an AsyncMock."""
        bus = EventBus()
        mock_publish = AsyncMock()
        bus.publish = mock_publish  # type: ignore[method-assign]
        return bus, mock_publish

    def _published_types(self, mock_publish: AsyncMock) -> set[str]:
        return {type(call.args[0]).__name__ for call in mock_publish.call_args_list}

    def test_issue_opened_with_label_publishes_scheduled_event(self) -> None:
        """Matching issue triggers notification + ScheduledEvent on bus."""
        bus, mock_pub = self._make_bus_with_mock_publish()
        settings = _make_settings(enable_issue_webhook=True)

        app = create_api_app(
            bus,
            settings,
            working_directory=Path("/tmp"),
            notification_chat_ids=[456],
        )
        client = TestClient(app)

        payload = _make_issue_payload(action="opened", labels=["sdd-analyze"])
        resp = self._post_issue_webhook(client, payload)

        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        # We expect 3 publish calls: WebhookEvent + AgentResponseEvent + ScheduledEvent
        published = self._published_types(mock_pub)
        assert "WebhookEvent" in published
        assert "ScheduledEvent" in published
        assert "AgentResponseEvent" in published

    def test_issue_opened_without_label_does_not_trigger_sdd(self) -> None:
        """Issue without required label only publishes WebhookEvent."""
        bus, mock_pub = self._make_bus_with_mock_publish()
        settings = _make_settings(
            enable_issue_webhook=True, issue_webhook_require_label=True
        )

        app = create_api_app(bus, settings, working_directory=Path("/tmp"))
        client = TestClient(app)

        payload = _make_issue_payload(action="opened", labels=["bug"])
        resp = self._post_issue_webhook(
            client, payload, delivery_id="delivery-no-label"
        )

        assert resp.status_code == 200
        published = self._published_types(mock_pub)
        assert "WebhookEvent" in published
        assert "ScheduledEvent" not in published
        assert "AgentResponseEvent" not in published

    def test_issue_webhook_disabled_does_not_trigger_sdd(self) -> None:
        """Feature flag off: no ScheduledEvent published even for matching issue."""
        bus, mock_pub = self._make_bus_with_mock_publish()
        settings = _make_settings(enable_issue_webhook=False)

        app = create_api_app(bus, settings, working_directory=Path("/tmp"))
        client = TestClient(app)

        payload = _make_issue_payload(action="opened", labels=["sdd-analyze"])
        resp = self._post_issue_webhook(
            client, payload, delivery_id="delivery-disabled"
        )

        assert resp.status_code == 200
        published = self._published_types(mock_pub)
        assert "ScheduledEvent" not in published

    def test_labeled_action_triggers_sdd(self) -> None:
        """Issue labeled with the target label after creation also triggers SDD."""
        bus, mock_pub = self._make_bus_with_mock_publish()
        settings = _make_settings(enable_issue_webhook=True)

        app = create_api_app(bus, settings, working_directory=Path("/tmp"))
        client = TestClient(app)

        payload = _make_issue_payload(action="labeled", added_label="sdd-analyze")
        resp = self._post_issue_webhook(
            client, payload, delivery_id="delivery-labeled"
        )

        assert resp.status_code == 200
        published = self._published_types(mock_pub)
        assert "ScheduledEvent" in published

    def test_push_event_does_not_trigger_sdd(self) -> None:
        """Non-issues events pass through without triggering SDD."""
        bus, mock_pub = self._make_bus_with_mock_publish()
        settings = _make_settings(enable_issue_webhook=True)

        app = create_api_app(bus, settings, working_directory=Path("/tmp"))
        client = TestClient(app)

        import json

        body = json.dumps({"ref": "refs/heads/main"}).encode()
        sig = _sign(body, "gh-secret")
        resp = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-push",
            },
        )

        assert resp.status_code == 200
        published = self._published_types(mock_pub)
        assert "ScheduledEvent" not in published

    def test_no_notification_when_no_chat_ids(self) -> None:
        """No AgentResponseEvent published when chat IDs are not configured."""
        bus, mock_pub = self._make_bus_with_mock_publish()
        settings = _make_settings(
            enable_issue_webhook=True, notification_chat_ids=[]
        )

        app = create_api_app(
            bus,
            settings,
            working_directory=Path("/tmp"),
            notification_chat_ids=[],
        )
        client = TestClient(app)

        payload = _make_issue_payload(action="opened", labels=["sdd-analyze"])
        resp = self._post_issue_webhook(
            client, payload, delivery_id="delivery-no-chats"
        )

        assert resp.status_code == 200
        published = self._published_types(mock_pub)
        # ScheduledEvent still published (Claude still runs), but no notification
        assert "ScheduledEvent" in published
        assert "AgentResponseEvent" not in published
