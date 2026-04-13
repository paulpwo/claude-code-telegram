"""Tests for the regex-based secret scrubber."""

import pytest

from src.security.secret_scrubber import scrub_secrets


class TestScrubSecrets:
    """``scrub_secrets`` must redact well-known secret formats and leave the
    rest of the text untouched."""

    @pytest.mark.parametrize(
        "text",
        [
            "",
            None,
            "plain message with no secrets",
            "talking about sk- prefixes abstractly",
            "github_pat_too_short",
        ],
    )
    def test_passthrough_when_no_secret(self, text):
        assert scrub_secrets(text) == text

    def test_github_classic_pat(self):
        token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        out = scrub_secrets(f"/git set {token}")
        assert token not in out
        assert "[REDACTED-GITHUB-PAT]" in out

    def test_github_other_pat_prefixes(self):
        for prefix in ("gho_", "ghs_", "ghr_", "ghu_"):
            token = prefix + "a" * 36
            assert "[REDACTED-GITHUB-PAT]" in scrub_secrets(token)

    def test_github_fine_grained_pat(self):
        token = "github_pat_" + "A" * 82
        out = scrub_secrets(f"my token is {token} thanks")
        assert token not in out
        assert "[REDACTED-GITHUB-PAT-FINE-GRAINED]" in out

    def test_anthropic_key_wins_over_generic_openai(self):
        # Anthropic keys start with `sk-ant-` — they must not be labelled as
        # OpenAI, which also matches `sk-...`. Specific pattern must win.
        key = "sk-ant-" + "x" * 64
        out = scrub_secrets(key)
        assert "[REDACTED-ANTHROPIC-KEY]" in out
        assert "[REDACTED-OPENAI-KEY]" not in out

    def test_openai_key(self):
        key = "sk-" + "a" * 40
        assert "[REDACTED-OPENAI-KEY]" in scrub_secrets(key)

    def test_aws_access_key(self):
        key = "AKIA" + "A" * 16
        assert "[REDACTED-AWS-ACCESS-KEY]" in scrub_secrets(f"key={key}")

    def test_slack_token(self):
        token = "xoxb-" + "a" * 30
        assert "[REDACTED-SLACK-TOKEN]" in scrub_secrets(token)

    def test_google_api_key(self):
        key = "AIza" + "A" * 35
        assert "[REDACTED-GOOGLE-API-KEY]" in scrub_secrets(key)

    def test_multiple_secrets_in_one_string(self):
        text = "ghp_" + "a" * 36 + " and AKIA" + "B" * 16 + " and sk-ant-" + "x" * 64
        out = scrub_secrets(text)
        assert "[REDACTED-GITHUB-PAT]" in out
        assert "[REDACTED-AWS-ACCESS-KEY]" in out
        assert "[REDACTED-ANTHROPIC-KEY]" in out

    def test_surrounding_text_preserved(self):
        token = "ghp_" + "1" * 36
        out = scrub_secrets(f"prefix {token} suffix")
        assert out.startswith("prefix ")
        assert out.endswith(" suffix")
