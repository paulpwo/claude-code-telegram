#!/bin/bash
# Transcribe a voice note (OGG/OPUS) using whisper-cpp
# Usage: transcribe-voice.sh <input_file> [language]
# Output: prints transcription to stdout

set -euo pipefail

INPUT="$1"
LANG="${2:-es}"
MODEL="${WHISPER_CPP_MODEL_PATH:-$HOME/.local/share/whisper/ggml-medium.bin}"
WHISPER_BIN="${WHISPER_CPP_BINARY_PATH:-whisper-cli}"
TMPWAV=$(mktemp /tmp/whisper-XXXXXX.wav)

trap 'rm -f "$TMPWAV"; rm -f "$INPUT"' EXIT

# Convert to WAV 16kHz mono (required by whisper-cpp)
ffmpeg -y -i "$INPUT" -ar 16000 -ac 1 -c:a pcm_s16le "$TMPWAV" 2>/dev/null

# Transcribe
"$WHISPER_BIN" -m "$MODEL" -l "$LANG" -nt -f "$TMPWAV" 2>/dev/null
