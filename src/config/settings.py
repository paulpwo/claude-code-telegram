"""Configuration management using Pydantic Settings.

Features:
- Environment variable loading
- Type validation
- Default values
- Computed properties
- Environment-specific settings
"""

import json
from pathlib import Path
from typing import Any, List, Literal, Optional

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict

from src.utils.constants import (
    DEFAULT_CLAUDE_MAX_COST_PER_REQUEST,
    DEFAULT_CLAUDE_MAX_COST_PER_USER,
    DEFAULT_CLAUDE_MAX_TURNS,
    DEFAULT_CLAUDE_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_URL,
    DEFAULT_MAX_SESSIONS_PER_USER,
    DEFAULT_PROJECT_THREADS_SYNC_ACTION_INTERVAL_SECONDS,
    DEFAULT_RATE_LIMIT_BURST,
    DEFAULT_RATE_LIMIT_REQUESTS,
    DEFAULT_RATE_LIMIT_WINDOW,
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_MAX_DELAY,
    DEFAULT_SESSION_TIMEOUT_HOURS,
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Bot settings
    telegram_bot_token: SecretStr = Field(
        ..., description="Telegram bot token from BotFather"
    )
    telegram_bot_username: str = Field(..., description="Bot username without @")

    # Security
    approved_directory: Path = Field(..., description="Base directory for projects")
    allowed_users: Optional[List[int]] = Field(
        None, description="Allowed Telegram user IDs"
    )
    enable_token_auth: bool = Field(
        False, description="Enable token-based authentication"
    )
    auth_token_secret: Optional[SecretStr] = Field(
        None, description="Secret for auth tokens"
    )
    admin_user_ids: List[int] = Field(
        default_factory=list,
        description="Telegram user IDs with admin privileges (ADMIN_USER_IDS env var)",
    )

    # Security relaxation (for trusted environments)
    disable_security_patterns: bool = Field(
        False,
        description=(
            "Disable dangerous pattern validation (pipes, redirections, etc.)"
        ),
    )
    disable_tool_validation: bool = Field(
        False,
        description="Allow all Claude tools by bypassing tool validation checks",
    )

    # Git safety
    git_protected_branches: List[str] = Field(
        default=["main", "develop", "master"],
        description="Branches Claude cannot push to or reset --hard on",
    )
    git_allow_force_push: bool = Field(
        False,
        description="Allow git push --force / -f (default: blocked)",
    )
    git_allow_delete_branch: bool = Field(
        False,
        description="Allow git branch -D (force-delete) (default: blocked)",
    )

    # Git PAT encryption
    git_token_encryption_key: Optional[SecretStr] = Field(
        None,
        description=(
            "Fernet key (base64url, 32 bytes) used to encrypt GitHub PATs at rest. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        ),
    )

    # SDD command
    enable_sdd: bool = Field(True, description="Enable /sdd command")
    sdd_protected_branches: List[str] = Field(
        default=["main", "master", "develop"],
        description="Branches /sdd must never push to",
    )

    # Claude settings
    claude_binary_path: Optional[str] = Field(
        None, description="Path to Claude CLI binary (deprecated)"
    )
    claude_cli_path: Optional[str] = Field(
        None, description="Path to Claude CLI executable"
    )
    anthropic_api_key: Optional[SecretStr] = Field(
        None,
        description="Anthropic API key for SDK (optional if CLI logged in)",
    )
    claude_model: Optional[str] = Field(
        None, description="Claude model to use (defaults to CLI default if unset)"
    )
    claude_max_turns: int = Field(
        DEFAULT_CLAUDE_MAX_TURNS, description="Max conversation turns"
    )
    claude_timeout_seconds: int = Field(
        DEFAULT_CLAUDE_TIMEOUT_SECONDS, description="Claude timeout"
    )
    claude_max_cost_per_user: float = Field(
        DEFAULT_CLAUDE_MAX_COST_PER_USER, description="Max cost per user"
    )
    claude_max_cost_per_request: float = Field(
        DEFAULT_CLAUDE_MAX_COST_PER_REQUEST,
        description="Max cost per individual request (SDK budget cap)",
    )
    # NOTE: When changing this list, also update docs/tools.md,
    # docs/configuration.md, .env.example,
    # src/claude/facade.py (_get_admin_instructions),
    # and src/bot/orchestrator.py (_TOOL_ICONS).
    claude_allowed_tools: Optional[List[str]] = Field(
        default=[
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "LS",
            "Task",
            "TaskOutput",
            "MultiEdit",
            "NotebookRead",
            "NotebookEdit",
            "WebFetch",
            "TodoRead",
            "TodoWrite",
            "WebSearch",
            "Skill",
        ],
        description="List of allowed Claude tools",
    )
    claude_disallowed_tools: Optional[List[str]] = Field(
        default=[],
        description="List of explicitly disallowed Claude tools/commands",
    )

    # Retry settings
    claude_retry_max_attempts: int = Field(
        DEFAULT_RETRY_MAX_ATTEMPTS,
        ge=0,
        description="Max retry attempts for transient SDK errors (0 = disabled)",
    )
    claude_retry_base_delay: float = Field(
        DEFAULT_RETRY_BASE_DELAY,
        ge=0,
        description=(
            "Base delay in seconds between retries. "
            "0 means retries are attempted immediately with no pause."
        ),
    )
    claude_retry_backoff_factor: float = Field(
        DEFAULT_RETRY_BACKOFF_FACTOR,
        gt=0,
        description="Exponential backoff multiplier",
    )
    claude_retry_max_delay: float = Field(
        DEFAULT_RETRY_MAX_DELAY,
        ge=0,
        description=(
            "Maximum delay cap in seconds. "
            "0 disables the cap entirely (delays grow unbounded with backoff)."
        ),
    )

    # Sandbox settings
    sandbox_enabled: bool = Field(
        True,
        description="Enable OS-level bash sandboxing for approved dir",
    )
    sandbox_excluded_commands: Optional[List[str]] = Field(
        default=["git", "npm", "pip", "poetry", "make", "docker"],
        description="Commands that run outside the sandbox (need system access)",
    )

    # Rate limiting
    rate_limit_requests: int = Field(
        DEFAULT_RATE_LIMIT_REQUESTS, description="Requests per window"
    )
    rate_limit_window: int = Field(
        DEFAULT_RATE_LIMIT_WINDOW, description="Rate limit window seconds"
    )
    rate_limit_burst: int = Field(
        DEFAULT_RATE_LIMIT_BURST, description="Burst capacity"
    )

    # Storage
    database_url: str = Field(
        DEFAULT_DATABASE_URL, description="Database connection URL"
    )
    session_timeout_hours: int = Field(
        DEFAULT_SESSION_TIMEOUT_HOURS, description="Session timeout"
    )
    session_timeout_minutes: int = Field(
        default=120,
        description="Session timeout in minutes",
        ge=10,
        le=1440,  # Max 24 hours
    )
    max_sessions_per_user: int = Field(
        DEFAULT_MAX_SESSIONS_PER_USER, description="Max concurrent sessions"
    )

    # Features
    enable_mcp: bool = Field(False, description="Enable Model Context Protocol")
    mcp_config_path: Optional[Path] = Field(
        None, description="MCP configuration file path"
    )
    enable_git_integration: bool = Field(True, description="Enable git commands")
    enable_file_uploads: bool = Field(True, description="Enable file upload handling")
    enable_voice_messages: bool = Field(
        True, description="Enable voice message transcription"
    )
    voice_provider: Literal["mistral", "openai", "local"] = Field(
        "mistral",
        description="Voice transcription provider: 'mistral', 'openai', or 'local'",
    )
    mistral_api_key: Optional[SecretStr] = Field(
        None, description="Mistral API key for voice transcription"
    )
    openai_api_key: Optional[SecretStr] = Field(
        None, description="OpenAI API key for Whisper voice transcription"
    )
    voice_transcription_model: Optional[str] = Field(
        None,
        description=(
            "Model for voice transcription. "
            "Defaults to 'voxtral-mini-latest' (Mistral) or 'whisper-1' (OpenAI)"
        ),
    )
    voice_max_file_size_mb: int = Field(
        20,
        description=(
            "Maximum Telegram voice message size (MB) that will be downloaded "
            "for transcription"
        ),
        ge=1,
        le=200,
    )
    whisper_cpp_binary_path: Optional[str] = Field(
        None,
        description=(
            "Path to whisper.cpp binary. "
            "Required when VOICE_PROVIDER=local. Auto-detected from PATH if unset."
        ),
    )
    whisper_cpp_model_path: Optional[str] = Field(
        None,
        description=(
            "Path to whisper.cpp GGML model file, or model name "
            "(e.g. 'base', 'small'). Defaults to 'base'. "
            "Named models resolve to ~/.cache/whisper-cpp/ggml-{name}.bin"
        ),
    )
    whisper_cpp_language: str = Field(
        "auto",
        description=(
            "Language hint passed to whisper.cpp via -l flag. "
            "Use a whisper language code ('es', 'en', 'pt', etc.) or 'auto' for "
            "automatic detection. Auto-detection is unreliable for short utterances "
            "and may produce output in the wrong language."
        ),
    )
    # Voice TTS (text-to-speech outgoing replies)
    enable_voice_replies: bool = Field(
        False, description="Enable outgoing voice note replies via edge-tts"
    )
    voice_reply_mode: Literal["manual", "auto"] = Field(
        "manual",
        description=(
            "Voice reply mode: 'manual' (always voice when enabled via /voice on) "
            "or 'auto' (voice only when reply is short enough)"
        ),
    )
    voice_reply_max_words: int = Field(
        200,
        ge=1,
        le=500,
        description="Maximum word count for auto voice mode",
    )
    edge_tts_voice: str = Field(
        "es-CO-GonzaloNeural",
        description="edge-tts voice name for TTS synthesis",
    )
    tts_engine: Literal["edge-tts", "openai", "system"] = Field(
        "edge-tts",
        description=(
            "TTS engine for outgoing voice replies: "
            "'edge-tts' (default, CLI binary), "
            "'openai' (OpenAI TTS API, requires OPENAI_API_KEY), "
            "or 'system' (pyttsx3 offline, requires pip install pyttsx3)"
        ),
    )
    openai_tts_voice: str = Field(
        "nova",
        description="OpenAI TTS voice name (used when VOICE_ENGINE=openai)",
    )
    system_tts_voice: str = Field(
        "default",
        description=(
            "pyttsx3 voice ID (used when VOICE_ENGINE=system; "
            "'default' uses the engine default)"
        ),
    )

    enable_quick_actions: bool = Field(True, description="Enable quick action buttons")
    agentic_mode: bool = Field(
        True,
        description="Conversational agentic mode (default) vs classic command mode",
    )

    # Reply quoting
    reply_quote: bool = Field(
        True,
        description=(
            "Quote the original user message when replying. "
            "Set to false for cleaner thread-based conversations."
        ),
    )

    # Output verbosity (0=quiet, 1=normal, 2=detailed)
    verbose_level: int = Field(
        1,
        description=(
            "Bot output verbosity: 0=quiet (final response only), "
            "1=normal (tool names + reasoning), "
            "2=detailed (tool inputs + longer reasoning)"
        ),
        ge=0,
        le=2,
    )

    # Streaming drafts (Telegram sendMessageDraft)
    enable_stream_drafts: bool = Field(
        False,
        description="Stream partial responses via sendMessageDraft (private chats only)",
    )
    stream_draft_interval: float = Field(
        0.3,
        description="Minimum seconds between draft updates (0.1-5.0)",
        ge=0.1,
        le=5.0,
    )

    # Monitoring
    log_level: str = Field("INFO", description="Logging level")
    enable_telemetry: bool = Field(False, description="Enable anonymous telemetry")
    sentry_dsn: Optional[str] = Field(None, description="Sentry DSN for error tracking")

    # Development
    debug: bool = Field(False, description="Enable debug mode")
    development_mode: bool = Field(False, description="Enable development features")

    # Webhook settings (optional)
    webhook_url: Optional[str] = Field(None, description="Webhook URL for bot")
    webhook_port: int = Field(8443, description="Webhook port")
    webhook_path: str = Field("/webhook", description="Webhook path")

    # Agentic platform settings
    enable_api_server: bool = Field(False, description="Enable FastAPI webhook server")
    api_server_port: int = Field(8080, description="Webhook API server port")
    enable_scheduler: bool = Field(False, description="Enable job scheduler")
    github_webhook_secret: Optional[str] = Field(
        None, description="GitHub webhook HMAC secret"
    )
    webhook_api_secret: Optional[str] = Field(
        None, description="Shared secret for generic webhook providers"
    )
    notification_chat_ids: Optional[List[int]] = Field(
        None, description="Default Telegram chat IDs for proactive notifications"
    )
    # GitHub issues webhook — automatic SDD trigger
    enable_issue_webhook: bool = Field(
        False,
        description=(
            "Auto-trigger SDD analysis when a GitHub issue is opened or labeled"
        ),
    )
    issue_webhook_require_label: bool = Field(
        True,
        description=(
            "When True, only issues that carry issue_webhook_label are processed"
        ),
    )
    issue_webhook_label: str = Field(
        "sdd-analyze",
        description="GitHub label that triggers automatic SDD analysis",
    )
    issue_webhook_repo_allowlist: List[str] = Field(
        default=[],
        description=(
            "Repos allowed to trigger analysis (owner/repo format). "
            "Empty list means all repos are allowed."
        ),
    )

    enable_project_threads: bool = Field(
        False,
        description="Enable strict routing by Telegram forum project threads",
    )
    project_threads_mode: Literal["private", "group"] = Field(
        "private",
        description="Project thread mode: private chat topics or group forum topics",
    )
    project_threads_chat_id: Optional[int] = Field(
        None, description="Telegram forum chat ID where project topics are managed"
    )
    projects_config_path: Optional[Path] = Field(
        None, description="Path to YAML project registry for thread mode"
    )
    project_threads_sync_action_interval_seconds: float = Field(
        DEFAULT_PROJECT_THREADS_SYNC_ACTION_INTERVAL_SECONDS,
        description=(
            "Minimum delay between Telegram API calls during project topic sync"
        ),
        ge=0.0,
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):  # type: ignore[override]
        """Override env sources to handle comma-separated lists (pydantic-settings 2.x).

        pydantic-settings 2.x tries json.loads() on List fields before field_validators run.
        This override returns the raw string for comma-separated values so the existing
        parse_protected_branches / parse_int_list validators can split them properly.
        """
        from pydantic_settings import DotEnvSettingsSource

        def _patch(source_cls):  # type: ignore[no-untyped-def]
            class _CommaFriendly(source_cls):  # type: ignore[valid-type]
                def decode_complex_value(
                    self, field_name: str, field: FieldInfo, value: Any
                ) -> Any:
                    if isinstance(value, str) and not value.strip().startswith(("[", "{")):
                        return value  # let field_validator handle comma-separated
                    return super().decode_complex_value(field_name, field, value)

            return _CommaFriendly

        sources = super().settings_customise_sources(settings_cls, **kwargs)
        patched = []
        for s in sources:
            if type(s) is DotEnvSettingsSource:
                patched.append(_patch(DotEnvSettingsSource)(settings_cls))
            elif type(s) is EnvSettingsSource:
                patched.append(_patch(EnvSettingsSource)(settings_cls))
            else:
                patched.append(s)
        return tuple(patched)

    @field_validator("allowed_users", "notification_chat_ids", "admin_user_ids", mode="before")
    @classmethod
    def parse_int_list(cls, v: Any) -> Optional[List[int]]:
        """Parse comma-separated integer lists."""
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        if isinstance(v, list):
            return [int(uid) for uid in v]
        return v  # type: ignore[no-any-return]

    @field_validator("claude_allowed_tools", mode="before")
    @classmethod
    def parse_claude_allowed_tools(cls, v: Any) -> Optional[List[str]]:
        """Parse comma-separated tool names."""
        if v is None:
            return None
        if isinstance(v, str):
            return [tool.strip() for tool in v.split(",") if tool.strip()]
        if isinstance(v, list):
            return [str(tool) for tool in v]
        return v  # type: ignore[no-any-return]

    @field_validator("issue_webhook_repo_allowlist", mode="before")
    @classmethod
    def parse_repo_allowlist(cls, v: Any) -> List[str]:
        """Parse comma-separated repo allowlist from env var string."""
        if isinstance(v, str):
            return [r.strip() for r in v.split(",") if r.strip()]
        if isinstance(v, list):
            return [str(r) for r in v]
        return v  # type: ignore[no-any-return]

    @field_validator("git_protected_branches", "sdd_protected_branches", mode="before")
    @classmethod
    def parse_protected_branches(cls, v: Any) -> List[str]:
        """Parse comma-separated branch names from env var string."""
        if isinstance(v, str):
            return [b.strip() for b in v.split(",") if b.strip()]
        if isinstance(v, list):
            return [str(b) for b in v]
        return v  # type: ignore[no-any-return]

    @field_validator("approved_directory")
    @classmethod
    def validate_approved_directory(cls, v: Any) -> Path:
        """Ensure approved directory exists and is absolute."""
        if isinstance(v, str):
            v = Path(v)

        path = v.resolve()
        if not path.exists():
            raise ValueError(f"Approved directory does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Approved directory is not a directory: {path}")
        return path  # type: ignore[no-any-return]

    @field_validator("mcp_config_path", mode="before")
    @classmethod
    def validate_mcp_config(cls, v: Any, info: Any) -> Optional[Path]:
        """Validate MCP configuration path if MCP is enabled."""
        if not v:
            return v  # type: ignore[no-any-return]
        if isinstance(v, str):
            v = Path(v)
        if not v.exists():
            raise ValueError(f"MCP config file does not exist: {v}")
        # Validate that the file contains valid JSON with mcpServers
        try:
            with open(v) as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"MCP config file is not valid JSON: {e}")
        if not isinstance(config_data, dict):
            raise ValueError("MCP config file must contain a JSON object")
        if "mcpServers" not in config_data:
            raise ValueError(
                "MCP config file must contain a 'mcpServers' key. "
                'Format: {"mcpServers": {"name": {"command": ...}}}'
            )
        if not isinstance(config_data["mcpServers"], dict):
            raise ValueError(
                "'mcpServers' must be an object mapping server names to configurations"
            )
        if not config_data["mcpServers"]:
            raise ValueError(
                "'mcpServers' must contain at least one server configuration"
            )
        return v  # type: ignore[no-any-return]

    @field_validator("projects_config_path", mode="before")
    @classmethod
    def validate_projects_config_path(cls, v: Any) -> Optional[Path]:
        """Validate projects config path if provided."""
        if not v:
            return None
        if isinstance(v, str):
            value = v.strip()
            if not value:
                return None
            v = Path(value)
        if not v.exists():
            raise ValueError(f"Projects config file does not exist: {v}")
        if not v.is_file():
            raise ValueError(f"Projects config path is not a file: {v}")
        return v  # type: ignore[no-any-return]

    @field_validator("project_threads_mode", mode="before")
    @classmethod
    def validate_project_threads_mode(cls, v: Any) -> str:
        """Validate project thread mode."""
        if v is None:
            return "private"
        mode = str(v).strip().lower()
        if mode not in {"private", "group"}:
            raise ValueError("project_threads_mode must be one of ['private', 'group']")
        return mode

    @field_validator("voice_provider", mode="before")
    @classmethod
    def validate_voice_provider(cls, v: Any) -> str:
        """Validate and normalize voice transcription provider."""
        if v is None:
            return "mistral"
        provider = str(v).strip().lower()
        if provider not in {"mistral", "openai", "local"}:
            raise ValueError(
                "voice_provider must be one of ['mistral', 'openai', 'local']"
            )
        return provider

    @field_validator("voice_reply_mode", mode="before")
    @classmethod
    def validate_voice_reply_mode(cls, v: Any) -> str:
        """Validate and normalize voice reply mode."""
        if v is None:
            return "manual"
        mode = str(v).strip().lower()
        if mode not in {"manual", "auto"}:
            raise ValueError("voice_reply_mode must be one of ['manual', 'auto']")
        return mode

    @field_validator("tts_engine", mode="before")
    @classmethod
    def validate_tts_engine(cls, v: Any) -> str:
        """Validate and normalize TTS engine selection."""
        if v is None:
            return "edge-tts"
        engine = str(v).strip().lower()
        if engine not in {"edge-tts", "openai", "system"}:
            raise ValueError(
                "tts_engine must be one of ['edge-tts', 'openai', 'system']"
            )
        return engine

    @field_validator("project_threads_chat_id", mode="before")
    @classmethod
    def validate_project_threads_chat_id(cls, v: Any) -> Optional[int]:
        """Allow empty chat ID for private mode by treating blank values as None."""
        if v is None:
            return None
        if isinstance(v, str):
            value = v.strip()
            if not value:
                return None
            return int(value)
        if isinstance(v, int):
            return v
        return v  # type: ignore[no-any-return]

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: Any) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()  # type: ignore[no-any-return]

    @model_validator(mode="after")
    def validate_cross_field_dependencies(self) -> "Settings":
        """Validate dependencies between fields."""
        # Check auth token requirements
        if self.enable_token_auth and not self.auth_token_secret:
            raise ValueError(
                "auth_token_secret required when enable_token_auth is True"
            )

        # Check MCP requirements
        if self.enable_mcp and not self.mcp_config_path:
            raise ValueError("mcp_config_path required when enable_mcp is True")

        if self.enable_project_threads:
            if (
                self.project_threads_mode == "group"
                and self.project_threads_chat_id is None
            ):
                raise ValueError(
                    "project_threads_chat_id required when "
                    "project_threads_mode is 'group'"
                )
            # projects_config_path is optional — DB-only mode is valid
            # (load_project_registry_from_db is used at startup when unset)

        return self

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return not (self.debug or self.development_mode)

    @property
    def database_path(self) -> Optional[Path]:
        """Extract path from SQLite database URL."""
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "")
            return Path(db_path).resolve()
        return None

    @property
    def telegram_token_str(self) -> str:
        """Get Telegram token as string."""
        return self.telegram_bot_token.get_secret_value()

    @property
    def auth_secret_str(self) -> Optional[str]:
        """Get auth token secret as string."""
        if self.auth_token_secret:
            return self.auth_token_secret.get_secret_value()
        return None

    @property
    def anthropic_api_key_str(self) -> Optional[str]:
        """Get Anthropic API key as string."""
        return (
            self.anthropic_api_key.get_secret_value()
            if self.anthropic_api_key
            else None
        )

    @property
    def mistral_api_key_str(self) -> Optional[str]:
        """Get Mistral API key as string."""
        return self.mistral_api_key.get_secret_value() if self.mistral_api_key else None

    @property
    def openai_api_key_str(self) -> Optional[str]:
        """Get OpenAI API key as string."""
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    @property
    def resolved_voice_model(self) -> str:
        """Get the voice transcription model, with provider-specific defaults."""
        if self.voice_transcription_model:
            return self.voice_transcription_model
        if self.voice_provider == "openai":
            return "whisper-1"
        if self.voice_provider == "local":
            return self.whisper_cpp_model_path or "base"
        return "voxtral-mini-latest"

    @property
    def voice_max_file_size_bytes(self) -> int:
        """Maximum allowed voice message size in bytes."""
        return self.voice_max_file_size_mb * 1024 * 1024

    @property
    def voice_provider_api_key_env(self) -> str:
        """API key environment variable required for the configured voice provider."""
        if self.voice_provider == "openai":
            return "OPENAI_API_KEY"
        if self.voice_provider == "local":
            return ""
        return "MISTRAL_API_KEY"

    @property
    def voice_provider_display_name(self) -> str:
        """Human-friendly label for the configured voice provider."""
        if self.voice_provider == "openai":
            return "OpenAI Whisper"
        if self.voice_provider == "local":
            return "Local whisper.cpp"
        return "Mistral Voxtral"

    @property
    def tts_engine_display_name(self) -> str:
        """Human-friendly label for the configured TTS engine."""
        if self.tts_engine == "openai":
            return "OpenAI TTS"
        if self.tts_engine == "system":
            return "System TTS (pyttsx3)"
        return "edge-tts"

    @property
    def resolved_whisper_cpp_binary(self) -> str:
        """Resolve whisper.cpp binary path, defaulting to 'whisper-cpp' on PATH."""
        return self.whisper_cpp_binary_path or "whisper-cpp"

    @property
    def resolved_whisper_cpp_model_path(self) -> str:
        """Resolve whisper.cpp model file path from name or explicit path."""
        path_or_name = self.whisper_cpp_model_path or "base"
        if "/" in path_or_name or path_or_name.endswith(".bin"):
            return path_or_name
        return str(Path.home() / ".cache" / "whisper-cpp" / f"ggml-{path_or_name}.bin")
