"""Tests for VoiceSender (TTS outgoing voice replies)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.features.voice_handler import VoiceSender


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
