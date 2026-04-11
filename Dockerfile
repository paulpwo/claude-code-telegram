# syntax=docker/dockerfile:1
# Claude Code Telegram Bot — Multi-stage Dockerfile
#
# Stages:
#   builder         — installs Python deps into /install prefix
#   node-builder    — installs Claude Code CLI via npm (isolated)
#   whisper-builder — (opt-in) compiles whisper-cli from source
#   runtime         — lean production image

ARG PYTHON_VERSION=3.11
ARG WITH_LOCAL_WHISPER=false

# =============================================================================
# Stage 1: builder — Python deps via pip
# =============================================================================
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

# Copy project files (src/ and README.md needed by the build backend)
COPY pyproject.toml poetry.lock README.md ./
COPY src/ ./src/

# Install project + all production deps into /install prefix
# Uses poetry-core as build backend (no Poetry CLI needed)
RUN pip install --no-cache-dir --prefix=/install .

# =============================================================================
# Stage 2: node-builder — Claude Code CLI (isolated, no npm in runtime)
# Note: @anthropic-ai/claude-code requires Node.js (postinstall scripts incompatible with Bun)
# =============================================================================
FROM node:lts-slim AS node-builder

RUN npm install -g @anthropic-ai/claude-code --no-update-notifier \
    && npm cache clean --force

# =============================================================================
# Stage 3: whisper-builder — compile whisper-cli from source (opt-in)
# =============================================================================
FROM python:${PYTHON_VERSION}-slim AS whisper-builder

ARG WITH_LOCAL_WHISPER=false

RUN if [ "$WITH_LOCAL_WHISPER" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
      && rm -rf /var/lib/apt/lists/* \
      && git clone --depth 1 https://github.com/ggerganov/whisper.cpp /whisper.cpp \
      && cmake -B /whisper.cpp/build -S /whisper.cpp \
           -DCMAKE_BUILD_TYPE=Release \
           -DBUILD_SHARED_LIBS=OFF \
           -DWHISPER_BUILD_TESTS=OFF \
           -DWHISPER_BUILD_EXAMPLES=ON \
      && cmake --build /whisper.cpp/build --target whisper-cli -j$(nproc) \
      && cp /whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper-cli; \
    else \
      mkdir -p /usr/local/bin \
      && printf '#!/bin/sh\necho "whisper-cli not available (built without WITH_LOCAL_WHISPER=true)"\nexit 1\n' \
         > /usr/local/bin/whisper-cli \
      && chmod +x /usr/local/bin/whisper-cli; \
    fi

# =============================================================================
# Stage 4: runtime — lean production image
# =============================================================================
FROM python:${PYTHON_VERSION}-slim AS runtime

# System dependencies — no gnupg/NodeSource needed (Node comes from node-builder)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        jq \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install edge-tts (TTS for voice replies)
RUN pip install --no-cache-dir edge-tts

# Copy pre-installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy Node.js runtime + Claude Code CLI (no npm/npx — not needed at runtime)
COPY --from=node-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=node-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node-builder /usr/local/bin/claude /usr/local/bin/claude

# Copy whisper-cli stub or real binary
COPY --from=whisper-builder /usr/local/bin/whisper-cli /usr/local/bin/whisper-cli

WORKDIR /app

# Copy application source
COPY src/ ./src/
COPY pyproject.toml ./

# Copy voice scripts into image (must live inside container — ~/.claude/ is host-only)
COPY scripts/voice/ ./scripts/voice/
RUN chmod +x ./scripts/voice/*.sh

# Volume mount points:
#   /data       — SQLite database persistence (DATABASE_URL=sqlite:////data/bot.db)
#   /workspace  — approved working directory (APPROVED_DIRECTORY=/workspace)
#   /models     — whisper model files (WHISPER_CPP_MODEL_PATH=/models/ggml-medium.bin)
VOLUME ["/data", "/workspace", "/models"]

ENTRYPOINT ["python", "-m", "src.main"]
