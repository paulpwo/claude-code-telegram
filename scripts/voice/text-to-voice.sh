#!/bin/bash
# Convert text to voice using edge-tts + ffmpeg
# Usage: text-to-voice.sh "text to speak" [output] [voice] [format]
# format: ogg (default, for Telegram voice) or mp3
# Output: prints path to generated file

set -euo pipefail

TEXT="$1"
VOICE="${3:-es-CO-GonzaloNeural}"
FORMAT="${4:-ogg}"

if [ "$FORMAT" = "mp3" ]; then
  OUTPUT="${2:-/tmp/tts-reply-$(date +%s).mp3}"
  edge-tts --voice "$VOICE" --text "$TEXT" --write-media "$OUTPUT" 2>/dev/null
else
  OUTPUT="${2:-/tmp/tts-reply-$(date +%s).ogg}"
  TMPMP3=$(mktemp /tmp/tts-XXXXXX.mp3)
  trap 'rm -f "$TMPMP3"' EXIT
  edge-tts --voice "$VOICE" --text "$TEXT" --write-media "$TMPMP3" 2>/dev/null
  # Convert to OGG opus (required for Telegram voice messages)
  ffmpeg -y -i "$TMPMP3" -c:a libopus -b:a 64k -ac 1 -ar 48000 -application voip "$OUTPUT" 2>/dev/null
fi

echo "$OUTPUT"
