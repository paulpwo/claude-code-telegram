"""Handle voice message transcription via Mistral (Voxtral), OpenAI (Whisper), or local whisper.cpp.

Also provides VoiceSender for outgoing TTS voice replies via edge-tts.
"""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import structlog
from telegram import Update, Voice

from src.config.settings import Settings

logger = structlog.get_logger(__name__)


@dataclass
class ProcessedVoice:
    """Result of voice message processing."""

    prompt: str
    transcription: str
    duration: int


class VoiceHandler:
    """Transcribe Telegram voice messages using Mistral, OpenAI, or local whisper.cpp."""

    # Timeout (seconds) for ffmpeg and whisper.cpp subprocess calls.
    LOCAL_SUBPROCESS_TIMEOUT: int = 120

    def __init__(self, config: Settings):
        self.config = config
        self._mistral_client: Optional[Any] = None
        self._openai_client: Optional[Any] = None
        self._resolved_whisper_binary: Optional[str] = None

    def _ensure_allowed_file_size(self, file_size: Optional[int]) -> None:
        """Reject files that exceed the configured max size."""
        if (
            isinstance(file_size, int)
            and file_size > self.config.voice_max_file_size_bytes
        ):
            raise ValueError(
                "Voice message too large "
                f"({file_size / 1024 / 1024:.1f}MB). "
                f"Max allowed: {self.config.voice_max_file_size_mb}MB. "
                "Adjust VOICE_MAX_FILE_SIZE_MB if needed."
            )

    async def process_voice_message(
        self, voice: Voice, caption: Optional[str] = None
    ) -> ProcessedVoice:
        """Download and transcribe a voice message.

        1. Download .ogg bytes from Telegram
        2. Call the configured transcription provider (Mistral, OpenAI, or local)
        3. Build a prompt combining caption + transcription
        """
        initial_file_size = getattr(voice, "file_size", None)
        self._ensure_allowed_file_size(initial_file_size)

        # Resolve Telegram file metadata before downloading bytes.
        file = await voice.get_file()
        resolved_file_size = getattr(file, "file_size", None)
        self._ensure_allowed_file_size(resolved_file_size)

        # Refuse unknown-size payloads to avoid unbounded downloads.
        if not isinstance(initial_file_size, int) and not isinstance(
            resolved_file_size, int
        ):
            raise ValueError(
                "Unable to determine voice message size before download. "
                "Please retry with a smaller voice message."
            )

        # Download voice data
        voice_bytes = bytes(await file.download_as_bytearray())
        self._ensure_allowed_file_size(len(voice_bytes))

        logger.info(
            "Transcribing voice message",
            provider=self.config.voice_provider,
            duration=voice.duration,
            file_size=initial_file_size or resolved_file_size or len(voice_bytes),
        )

        if self.config.voice_provider == "local":
            transcription = await self._transcribe_local(voice_bytes)
        elif self.config.voice_provider == "openai":
            transcription = await self._transcribe_openai(voice_bytes)
        else:
            transcription = await self._transcribe_mistral(voice_bytes)

        logger.info(
            "Voice transcription complete",
            transcription_length=len(transcription),
            duration=voice.duration,
        )

        # Build prompt
        label = caption if caption else "Voice message transcription:"
        prompt = f"{label}\n\n{transcription}"

        dur = voice.duration
        duration_secs = int(dur.total_seconds()) if isinstance(dur, timedelta) else dur

        return ProcessedVoice(
            prompt=prompt,
            transcription=transcription,
            duration=duration_secs,
        )

    # -- Mistral provider --

    async def _transcribe_mistral(self, voice_bytes: bytes) -> str:
        """Transcribe audio using the Mistral API (Voxtral)."""
        client = self._get_mistral_client()
        try:
            response = await client.audio.transcriptions.complete_async(
                model=self.config.resolved_voice_model,
                file={
                    "content": voice_bytes,
                    "file_name": "voice.ogg",
                },
            )
        except Exception as exc:
            logger.warning(
                "Mistral transcription request failed",
                error_type=type(exc).__name__,
            )
            raise RuntimeError("Mistral transcription request failed.") from exc

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("Mistral transcription returned an empty response.")
        return text

    def _get_mistral_client(self) -> Any:
        """Create and cache a Mistral client on first use."""
        if self._mistral_client is not None:
            return self._mistral_client

        try:
            from mistralai import Mistral
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Optional dependency 'mistralai' is missing for voice transcription. "
                "Install voice extras: "
                'pip install "claude-code-telegram[voice]"'
            ) from exc

        api_key = self.config.mistral_api_key_str
        if not api_key:
            raise RuntimeError("Mistral API key is not configured.")

        self._mistral_client = Mistral(api_key=api_key)
        return self._mistral_client

    # -- OpenAI provider --

    async def _transcribe_openai(self, voice_bytes: bytes) -> str:
        """Transcribe audio using the OpenAI Whisper API."""
        client = self._get_openai_client()
        try:
            response = await client.audio.transcriptions.create(
                model=self.config.resolved_voice_model,
                file=("voice.ogg", voice_bytes),
            )
        except Exception as exc:
            logger.warning(
                "OpenAI transcription request failed",
                error_type=type(exc).__name__,
            )
            raise RuntimeError("OpenAI transcription request failed.") from exc

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("OpenAI transcription returned an empty response.")
        return text

    def _get_openai_client(self) -> Any:
        """Create and cache an OpenAI client on first use."""
        if self._openai_client is not None:
            return self._openai_client

        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Optional dependency 'openai' is missing for voice transcription. "
                "Install voice extras: "
                'pip install "claude-code-telegram[voice]"'
            ) from exc

        api_key = self.config.openai_api_key_str
        if not api_key:
            raise RuntimeError("OpenAI API key is not configured.")

        self._openai_client = AsyncOpenAI(api_key=api_key)
        return self._openai_client

    # -- Local whisper.cpp provider --

    async def _transcribe_local(self, voice_bytes: bytes) -> str:
        """Transcribe audio locally using whisper.cpp binary."""
        binary = self._resolve_whisper_binary()
        model_path = self.config.resolved_whisper_cpp_model_path

        if not Path(model_path).is_file():
            raise RuntimeError(
                f"whisper.cpp model not found at {model_path}. "
                "Download it with: "
                "curl -L -o ~/.cache/whisper-cpp/ggml-base.bin "
                "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
            )

        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="voice_")
            ogg_path = Path(tmp_dir) / "voice.ogg"
            wav_path = Path(tmp_dir) / "voice.wav"

            ogg_path.write_bytes(voice_bytes)

            # Convert OGG/Opus -> WAV (16kHz mono PCM)
            await self._convert_ogg_to_wav(ogg_path, wav_path)

            # Run whisper.cpp
            text = await self._run_whisper_cpp(binary, model_path, wav_path)

        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        text = text.strip()
        if not text:
            raise ValueError(
                "Local whisper.cpp transcription returned an empty response."
            )
        return text

    async def _convert_ogg_to_wav(self, ogg_path: Path, wav_path: Path) -> None:
        """Convert OGG/Opus to WAV (16kHz mono PCM) using ffmpeg."""
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-i",
                str(ogg_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(wav_path),
                "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.LOCAL_SUBPROCESS_TIMEOUT,
            )

            if process.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg conversion failed (exit {process.returncode}): "
                    f"{stderr.decode()[:200]}"
                )
        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(
                f"ffmpeg conversion timed out after {self.LOCAL_SUBPROCESS_TIMEOUT}s."
            )
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg is required for local voice transcription but was not found. "
                "Install it with: apt install ffmpeg"
            )

    async def _run_whisper_cpp(
        self, binary: str, model_path: str, wav_path: Path
    ) -> str:
        """Execute whisper.cpp binary and return transcription text."""
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                "-m",
                model_path,
                "-f",
                str(wav_path),
                "--no-timestamps",
                "-l",
                self.config.whisper_cpp_language,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.LOCAL_SUBPROCESS_TIMEOUT,
            )

            if process.returncode != 0:
                logger.warning(
                    "whisper.cpp transcription failed",
                    return_code=process.returncode,
                    stderr=stderr.decode()[:300],
                )
                raise RuntimeError("Local whisper.cpp transcription failed.")

            return stdout.decode()

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(
                f"whisper.cpp transcription timed out after "
                f"{self.LOCAL_SUBPROCESS_TIMEOUT}s."
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"whisper.cpp binary not found at '{binary}'. "
                "Set WHISPER_CPP_BINARY_PATH or install whisper.cpp."
            )
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning(
                "whisper.cpp transcription request failed",
                error_type=type(exc).__name__,
            )
            raise RuntimeError("Local whisper.cpp transcription failed.") from exc

    def _resolve_whisper_binary(self) -> str:
        """Resolve and validate the whisper.cpp binary path on first use."""
        if self._resolved_whisper_binary is not None:
            return self._resolved_whisper_binary

        binary = self.config.resolved_whisper_cpp_binary
        resolved = shutil.which(binary)
        if not resolved:
            raise RuntimeError(
                f"whisper.cpp binary '{binary}' not found on PATH. "
                "Set WHISPER_CPP_BINARY_PATH to the full path."
            )
        self._resolved_whisper_binary = resolved
        return resolved


class VoiceSender:
    """Synthesize outgoing voice replies using a configurable TTS engine.

    Complementary to VoiceHandler (STT) — this class handles TTS (text-to-speech).
    Supported engines (VOICE_ENGINE env var):
    - ``edge-tts`` (default): requires the edge-tts CLI binary on PATH
    - ``openai``: requires OPENAI_API_KEY and ffmpeg
    - ``system``: requires pyttsx3 (``pip install pyttsx3``) and ffmpeg
    """

    # Maximum seconds to wait for TTS subprocess operations.
    TTS_SUBPROCESS_TIMEOUT: int = 60

    def __init__(self, config: Settings) -> None:
        self.config = config
        self._openai_client: Optional[Any] = None

    # -- Dispatcher --

    async def _synthesize_ogg(
        self, text: str, tmp_dir: Path, voice_override: Optional[str] = None
    ) -> Path:
        """Dispatch to the configured TTS engine and return an OGG/Opus file path.

        Args:
            text: The text to synthesize.
            tmp_dir: Temporary directory for output files.
            voice_override: Override the configured voice name (edge-tts only).

        Returns:
            Path to the generated OGG file.

        Raises:
            RuntimeError: On subprocess failure, timeout, missing binary/dep, or bad config.
        """
        if self.config.tts_engine == "openai":
            return await self._synthesize_ogg_openai(text, tmp_dir)
        elif self.config.tts_engine == "system":
            return await self._synthesize_ogg_system(text, tmp_dir)
        else:  # "edge-tts" default
            return await self._synthesize_ogg_edge_tts(text, tmp_dir, voice_override=voice_override)

    # -- edge-tts engine --

    async def _synthesize_ogg_edge_tts(
        self, text: str, tmp_dir: Path, voice_override: Optional[str] = None
    ) -> Path:
        """Synthesize OGG/Opus audio via the edge_tts Python API (no subprocess needed).

        Args:
            text: The text to synthesize.
            tmp_dir: Temporary directory for the output file.
            voice_override: Use this voice instead of the configured default.

        Returns:
            Path to the generated OGG file.

        Raises:
            RuntimeError: On synthesis failure or missing dependency.
        """
        try:
            import edge_tts
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Optional dependency 'edge-tts' is missing. "
                "Install it with: pip install edge-tts"
            ) from exc

        voice = voice_override or self.config.edge_tts_voice
        mp3_path = tmp_dir / "reply.mp3"

        try:
            communicate = edge_tts.Communicate(text, voice)
            await asyncio.wait_for(
                communicate.save(str(mp3_path)),
                timeout=self.TTS_SUBPROCESS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"edge-tts synthesis timed out after {self.TTS_SUBPROCESS_TIMEOUT}s."
            )
        except Exception as exc:
            raise RuntimeError(f"edge-tts synthesis failed: {exc}") from exc

        ogg_path = tmp_dir / "reply.ogg"
        await self._ffmpeg_convert(mp3_path, ogg_path)
        return ogg_path

    # -- OpenAI engine --

    def _get_openai_tts_client(self) -> Any:
        """Create and cache an AsyncOpenAI client for TTS on first use."""
        if self._openai_client is not None:
            return self._openai_client

        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Optional dependency 'openai' is missing for TTS. "
                "Install voice extras: "
                'pip install "claude-code-telegram[voice]"'
            ) from exc

        api_key = self.config.openai_api_key_str
        if not api_key:
            raise RuntimeError(
                "OpenAI API key is not configured. "
                "Set OPENAI_API_KEY to use the openai TTS engine."
            )

        self._openai_client = AsyncOpenAI(api_key=api_key)
        return self._openai_client

    async def _synthesize_ogg_openai(self, text: str, tmp_dir: Path) -> Path:
        """Synthesize audio via OpenAI TTS API, convert to OGG/Opus via ffmpeg.

        Args:
            text: The text to synthesize.
            tmp_dir: Temporary directory for intermediate and output files.

        Returns:
            Path to the generated OGG file.

        Raises:
            RuntimeError: On API failure, ffmpeg missing/failure, or missing API key.
        """
        client = self._get_openai_tts_client()

        try:
            response = await client.audio.speech.create(
                model="tts-1",
                voice=self.config.openai_tts_voice,
                input=text,
            )
        except Exception as exc:
            logger.warning(
                "OpenAI TTS request failed",
                error_type=type(exc).__name__,
            )
            raise RuntimeError("OpenAI TTS request failed.") from exc

        mp3_path = tmp_dir / "reply.mp3"
        mp3_path.write_bytes(response.content)

        ogg_path = tmp_dir / "reply.ogg"
        await self._ffmpeg_convert(mp3_path, ogg_path)
        return ogg_path

    # -- System (pyttsx3) engine --

    async def _synthesize_ogg_system(self, text: str, tmp_dir: Path) -> Path:
        """Synthesize audio via pyttsx3 (offline), convert to OGG/Opus via ffmpeg.

        pyttsx3.runAndWait() is synchronous — it is wrapped in asyncio.to_thread()
        to avoid blocking the event loop.

        Args:
            text: The text to synthesize.
            tmp_dir: Temporary directory for intermediate and output files.

        Returns:
            Path to the generated OGG file.

        Raises:
            RuntimeError: On pyttsx3 missing, ffmpeg missing/failure.
        """
        try:
            import pyttsx3
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Optional dependency 'pyttsx3' is missing for system TTS. "
                "Install it with: "
                'pip install "claude-code-telegram[tts]" or pip install pyttsx3'
            ) from exc

        wav_path = tmp_dir / "reply.wav"
        voice_id: Optional[str] = (
            self.config.system_tts_voice
            if self.config.system_tts_voice != "default"
            else None
        )

        def _run_pyttsx3() -> None:
            engine = pyttsx3.init()
            if voice_id is not None:
                engine.setProperty("voice", voice_id)
            engine.save_to_file(text, str(wav_path))
            engine.runAndWait()

        await asyncio.to_thread(_run_pyttsx3)

        ogg_path = tmp_dir / "reply.ogg"
        await self._ffmpeg_convert(wav_path, ogg_path)
        return ogg_path

    # -- Shared ffmpeg helper --

    async def _ffmpeg_convert(self, input_path: Path, output_path: Path) -> None:
        """Convert an audio file to OGG/Opus using ffmpeg.

        Args:
            input_path: Source audio file (MP3, WAV, etc.).
            output_path: Destination OGG/Opus file.

        Raises:
            RuntimeError: On ffmpeg missing, non-zero exit, or timeout.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-i",
                str(input_path),
                "-c:a",
                "libopus",
                str(output_path),
                "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.TTS_SUBPROCESS_TIMEOUT,
                )
            except asyncio.TimeoutError:
                process.kill()
                raise RuntimeError(
                    f"ffmpeg conversion timed out after {self.TTS_SUBPROCESS_TIMEOUT}s."
                )

            if process.returncode != 0:
                err_msg = stderr.decode(errors="replace")[:300] if stderr else ""
                raise RuntimeError(
                    f"ffmpeg conversion failed (exit {process.returncode}): {err_msg}"
                )

        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg is required for audio conversion but was not found on PATH. "
                "Install it with: apt install ffmpeg  (or brew install ffmpeg on macOS)"
            )

    async def send_voice_reply(
        self,
        text: str,
        update: Update,
        reply_to_message_id: Optional[int] = None,
        voice_override: Optional[str] = None,
    ) -> bool:
        """Synthesize text as OGG audio and send via Telegram sendVoice.

        Creates a temp directory, synthesizes OGG via the configured TTS engine,
        sends it, and always cleans up the temp dir (even on failure).

        Args:
            text: The text to convert to speech.
            update: The Telegram Update to reply to.
            reply_to_message_id: Optional message ID to reply to.
            voice_override: Override the configured voice name (edge-tts only).

        Returns:
            True on success, False if any step failed.
        """
        tmp_dir: Optional[Path] = None
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="tts_"))

            ogg_path = await self._synthesize_ogg(text, tmp_dir, voice_override=voice_override)

            with open(ogg_path, "rb") as audio_file:
                await update.message.reply_voice(
                    voice=audio_file,
                    reply_to_message_id=reply_to_message_id,
                )

            logger.info(
                "Voice reply sent",
                engine=self.config.tts_engine,
                word_count=len(text.split()),
            )
            return True

        except Exception as exc:
            logger.warning(
                "Voice reply failed, falling back to text",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)
