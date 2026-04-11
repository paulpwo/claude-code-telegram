"""Tests for VoiceSender (TTS outgoing voice replies)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.features.voice_handler import VoiceSender
from src.bot.features.registry import _pyttsx3_importable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tts_config():
    """Mock Settings for VoiceSender tests."""
    cfg = MagicMock()
    cfg.edge_tts_voice = "es-AR-TomasNeural"
    cfg.voice_reply_max_words = 200
    return cfg


@pytest.fixture
def voice_sender(tts_config):
    """VoiceSender instance under test."""
    return VoiceSender(config=tts_config)


def _make_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Build a mock asyncio.Process whose communicate() returns (stdout, stderr)."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


def _make_update(reply_voice_mock: AsyncMock | None = None) -> MagicMock:
    """Build a minimal mock Update with message.reply_voice."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_voice = reply_voice_mock or AsyncMock()
    return update


# ---------------------------------------------------------------------------
# _synthesize_ogg — success path (4.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_success(voice_sender, tmp_path):
    """_synthesize_ogg returns a Path when edge-tts exits 0."""
    good_proc = _make_process(returncode=0)

    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=good_proc)
    ) as mock_exec:
        result = await voice_sender._synthesize_ogg("Hello world", tmp_path)

    assert isinstance(result, Path)
    assert result.name == "reply.ogg"
    assert result.parent == tmp_path
    mock_exec.assert_called_once()
    # Verify voice name is passed
    call_args = mock_exec.call_args[0]
    assert "es-AR-TomasNeural" in call_args


# ---------------------------------------------------------------------------
# _synthesize_ogg — non-zero exit raises RuntimeError (4.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_nonzero_exit_raises(voice_sender, tmp_path):
    """_synthesize_ogg raises RuntimeError when edge-tts returns non-zero exit code."""
    fail_proc = _make_process(returncode=1, stderr=b"error: voice not found")

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fail_proc)):
        with pytest.raises(RuntimeError, match="synthesis failed"):
            await voice_sender._synthesize_ogg("Hello", tmp_path)


# ---------------------------------------------------------------------------
# _synthesize_ogg — FileNotFoundError raises RuntimeError with install hint (4.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_binary_missing_raises(voice_sender, tmp_path):
    """_synthesize_ogg raises RuntimeError with install hint when edge-tts not on PATH."""
    with patch(
        "asyncio.create_subprocess_exec", side_effect=FileNotFoundError("edge-tts")
    ):
        with pytest.raises(RuntimeError, match="pip install edge-tts"):
            await voice_sender._synthesize_ogg("Hello", tmp_path)


# ---------------------------------------------------------------------------
# _synthesize_ogg — timeout kills process and raises RuntimeError (4.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_timeout_kills_process(voice_sender, tmp_path):
    """_synthesize_ogg kills the process and raises RuntimeError on timeout."""
    slow_proc = _make_process(returncode=0)
    slow_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=slow_proc)):
        with pytest.raises(RuntimeError, match="timed out"):
            await voice_sender._synthesize_ogg("Hello", tmp_path)

    slow_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# send_voice_reply — success path: temp dir cleaned up (4.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_voice_reply_success_cleans_tmp(voice_sender, tmp_path):
    """send_voice_reply returns True and cleans up temp dir after successful send."""
    good_proc = _make_process(returncode=0)
    reply_voice = AsyncMock()
    update = _make_update(reply_voice_mock=reply_voice)

    # Patch _synthesize_ogg to write a real (empty) file so open() works
    async def fake_synthesize(text: str, td: Path) -> Path:
        p = td / "reply.ogg"
        p.write_bytes(b"fake-ogg-data")
        return p

    captured_tmp_dirs: list = []

    original_mkdtemp = __import__("tempfile").mkdtemp

    def patched_mkdtemp(**kwargs):  # type: ignore[return]
        d = original_mkdtemp(**kwargs)
        captured_tmp_dirs.append(d)
        return d

    with (
        patch.object(voice_sender, "_synthesize_ogg", side_effect=fake_synthesize),
        patch("tempfile.mkdtemp", side_effect=patched_mkdtemp),
    ):
        result = await voice_sender.send_voice_reply("Hello world", update)

    assert result is True
    reply_voice.assert_awaited_once()

    # All temp dirs created should be gone after the call
    for d in captured_tmp_dirs:
        assert not Path(d).exists(), f"Temp dir {d} was not cleaned up"


# ---------------------------------------------------------------------------
# send_voice_reply — failure path: returns False and no file leak (4.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_voice_reply_failure_returns_false(voice_sender, tmp_path):
    """send_voice_reply returns False when synthesis raises, with no file leak."""
    update = _make_update()

    async def fail_synthesize(text: str, td: Path) -> Path:
        raise RuntimeError("edge-tts not found")

    captured_tmp_dirs: list = []
    original_mkdtemp = __import__("tempfile").mkdtemp

    def patched_mkdtemp(**kwargs):  # type: ignore[return]
        d = original_mkdtemp(**kwargs)
        captured_tmp_dirs.append(d)
        return d

    with (
        patch.object(voice_sender, "_synthesize_ogg", side_effect=fail_synthesize),
        patch("tempfile.mkdtemp", side_effect=patched_mkdtemp),
    ):
        result = await voice_sender.send_voice_reply("Hello", update)

    assert result is False
    # Temp dirs must still be cleaned up even on failure
    for d in captured_tmp_dirs:
        assert not Path(d).exists(), f"Temp dir {d} leaked on failure"


# ---------------------------------------------------------------------------
# OpenAI engine fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def openai_tts_config():
    """Mock Settings configured for the openai TTS engine."""
    cfg = MagicMock()
    cfg.tts_engine = "openai"
    cfg.openai_tts_voice = "nova"
    cfg.openai_api_key = MagicMock()
    cfg.openai_api_key_str = "sk-test"
    cfg.edge_tts_voice = "es-AR-TomasNeural"
    cfg.voice_reply_max_words = 200
    return cfg


@pytest.fixture
def openai_voice_sender(openai_tts_config):
    """VoiceSender instance configured for OpenAI engine."""
    return VoiceSender(config=openai_tts_config)


# ---------------------------------------------------------------------------
# 4.2 OpenAI engine — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_openai_success(openai_voice_sender, tmp_path):
    """_synthesize_ogg_openai returns an OGG path on success (mocked API + ffmpeg)."""
    # Mock OpenAI response
    mock_response = MagicMock()
    mock_response.content = b"fake-mp3-bytes"

    mock_openai_client = AsyncMock()
    mock_openai_client.audio.speech.create = AsyncMock(return_value=mock_response)

    good_ffmpeg_proc = _make_process(returncode=0)

    with (
        patch.object(
            openai_voice_sender, "_get_openai_tts_client", return_value=mock_openai_client
        ),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=good_ffmpeg_proc)),
    ):
        result = await openai_voice_sender._synthesize_ogg_openai("Hello world", tmp_path)

    assert isinstance(result, Path)
    assert result.name == "reply.ogg"
    mock_openai_client.audio.speech.create.assert_awaited_once()
    call_kwargs = mock_openai_client.audio.speech.create.call_args[1]
    assert call_kwargs["voice"] == "nova"
    assert call_kwargs["model"] == "tts-1"
    assert call_kwargs["input"] == "Hello world"


# ---------------------------------------------------------------------------
# 4.3 OpenAI engine — ffmpeg missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_openai_ffmpeg_missing(openai_voice_sender, tmp_path):
    """_synthesize_ogg_openai raises RuntimeError with install hint when ffmpeg absent."""
    mock_response = MagicMock()
    mock_response.content = b"fake-mp3-bytes"

    mock_openai_client = AsyncMock()
    mock_openai_client.audio.speech.create = AsyncMock(return_value=mock_response)

    with (
        patch.object(
            openai_voice_sender, "_get_openai_tts_client", return_value=mock_openai_client
        ),
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("ffmpeg"),
        ),
    ):
        with pytest.raises(RuntimeError, match="ffmpeg"):
            await openai_voice_sender._synthesize_ogg_openai("Hello", tmp_path)


# ---------------------------------------------------------------------------
# System engine fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def system_tts_config():
    """Mock Settings configured for the system (pyttsx3) TTS engine."""
    cfg = MagicMock()
    cfg.tts_engine = "system"
    cfg.system_tts_voice = "default"
    cfg.edge_tts_voice = "es-AR-TomasNeural"
    cfg.voice_reply_max_words = 200
    return cfg


@pytest.fixture
def system_voice_sender(system_tts_config):
    """VoiceSender instance configured for system engine."""
    return VoiceSender(config=system_tts_config)


# ---------------------------------------------------------------------------
# 4.5 System engine — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_system_success(system_voice_sender, tmp_path):
    """_synthesize_ogg_system returns an OGG path; pyttsx3 runs via asyncio.to_thread."""
    mock_pyttsx3_engine = MagicMock()

    mock_pyttsx3 = MagicMock()
    mock_pyttsx3.init.return_value = mock_pyttsx3_engine

    good_ffmpeg_proc = _make_process(returncode=0)

    to_thread_called = []

    async def fake_to_thread(fn, *args, **kwargs):
        to_thread_called.append(True)
        fn()  # run synchronously in test for simplicity

    with (
        patch.dict("sys.modules", {"pyttsx3": mock_pyttsx3}),
        patch("asyncio.to_thread", side_effect=fake_to_thread),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=good_ffmpeg_proc)),
    ):
        result = await system_voice_sender._synthesize_ogg_system("Hello world", tmp_path)

    assert isinstance(result, Path)
    assert result.name == "reply.ogg"
    assert len(to_thread_called) == 1, "pyttsx3 must run inside asyncio.to_thread"
    mock_pyttsx3.init.assert_called_once()
    mock_pyttsx3_engine.save_to_file.assert_called_once()
    mock_pyttsx3_engine.runAndWait.assert_called_once()


# ---------------------------------------------------------------------------
# 4.6 System engine — pyttsx3 not installed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_system_pyttsx3_missing(system_voice_sender, tmp_path):
    """_synthesize_ogg_system raises RuntimeError with install hint when pyttsx3 absent."""
    import sys

    # Remove pyttsx3 from sys.modules and make import fail
    with patch.dict("sys.modules", {"pyttsx3": None}):  # type: ignore[dict-item]
        with pytest.raises(RuntimeError, match="pyttsx3"):
            await system_voice_sender._synthesize_ogg_system("Hello", tmp_path)


# ---------------------------------------------------------------------------
# 4.7 Dispatcher routes to openai engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_dispatcher_routes_openai(openai_voice_sender, tmp_path):
    """_synthesize_ogg delegates to _synthesize_ogg_openai when tts_engine='openai'."""
    expected_path = tmp_path / "reply.ogg"

    with patch.object(
        openai_voice_sender,
        "_synthesize_ogg_openai",
        new_callable=AsyncMock,
        return_value=expected_path,
    ) as mock_openai:
        result = await openai_voice_sender._synthesize_ogg("Hello", tmp_path)

    mock_openai.assert_awaited_once_with("Hello", tmp_path)
    assert result == expected_path


# ---------------------------------------------------------------------------
# 4.8 Dispatcher routes to system engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_ogg_dispatcher_routes_system(system_voice_sender, tmp_path):
    """_synthesize_ogg delegates to _synthesize_ogg_system when tts_engine='system'."""
    expected_path = tmp_path / "reply.ogg"

    with patch.object(
        system_voice_sender,
        "_synthesize_ogg_system",
        new_callable=AsyncMock,
        return_value=expected_path,
    ) as mock_system:
        result = await system_voice_sender._synthesize_ogg("Hello", tmp_path)

    mock_system.assert_awaited_once_with("Hello", tmp_path)
    assert result == expected_path


# ---------------------------------------------------------------------------
# 4.9 Registry guard — openai engine, no API key → voice_sender absent
# ---------------------------------------------------------------------------


def test_registry_skips_voice_sender_openai_no_key():
    """FeatureRegistry skips voice_sender when tts_engine=openai but no API key."""
    from src.bot.features.registry import FeatureRegistry

    config = MagicMock()
    config.enable_file_uploads = False
    config.enable_git_integration = False
    config.enable_quick_actions = False
    config.agentic_mode = True
    config.enable_voice_messages = False
    config.enable_voice_replies = True
    config.tts_engine = "openai"
    config.openai_api_key = None  # missing key

    storage = MagicMock()
    security = MagicMock()

    # ImageHandler needs real config attrs — patch it out
    with patch("src.bot.features.registry.ImageHandler"):
        registry = FeatureRegistry(config=config, storage=storage, security=security)

    assert "voice_sender" not in registry.features


# ---------------------------------------------------------------------------
# 4.10 Registry guard — system engine, pyttsx3 not importable → voice_sender absent
# ---------------------------------------------------------------------------


def test_registry_skips_voice_sender_system_no_pyttsx3():
    """FeatureRegistry skips voice_sender when tts_engine=system and pyttsx3 missing."""
    from src.bot.features.registry import FeatureRegistry

    config = MagicMock()
    config.enable_file_uploads = False
    config.enable_git_integration = False
    config.enable_quick_actions = False
    config.agentic_mode = True
    config.enable_voice_messages = False
    config.enable_voice_replies = True
    config.tts_engine = "system"

    storage = MagicMock()
    security = MagicMock()

    with (
        patch("src.bot.features.registry.ImageHandler"),
        patch("src.bot.features.registry._pyttsx3_importable", return_value=False),
    ):
        registry = FeatureRegistry(config=config, storage=storage, security=security)

    assert "voice_sender" not in registry.features
