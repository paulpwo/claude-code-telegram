#!/bin/bash
# Send an OGG file as a Telegram voice message (not document)
# Usage: send-voice-telegram.sh <ogg_file> <chat_id> [reply_to_message_id]
# Requires: TELEGRAM_BOT_TOKEN env var

set -euo pipefail

FILE="$1"
CHAT_ID="$2"
REPLY_TO="${3:-}"

ARGS=(-s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendVoice"
  -F "chat_id=${CHAT_ID}"
  -F "voice=@${FILE}")

[ -n "$REPLY_TO" ] && ARGS+=(-F "reply_to_message_id=${REPLY_TO}")

RESULT=$(curl "${ARGS[@]}" 2>/dev/null)
OK=$(echo "$RESULT" | jq -r '.ok')

if [ "$OK" = "true" ]; then
  echo "$RESULT" | jq -r '.result.message_id'
  rm -f "$FILE"
else
  echo "ERROR: $RESULT" >&2
  exit 1
fi
