# syntax=docker/dockerfile:1.7
#
# Meeting Assistant: the web UI and API in one image, GPU-capable.
#
#   Stage "ui"  builds the React frontend (node).
#   Stage "app" is the Python runtime: CUDA-enabled torch, faster-whisper,
#               pyannote, FFmpeg, and the built UI served by FastAPI.
#
# Build and run with compose (see compose.yaml and docker/up.ps1), which also
# records the git commit so every run in the container stays traceable.

# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg: audio decoding for pyannote (torchcodec) and faster-whisper.
# libportaudio2: lets sounddevice import (containers have no microphone, so
#   the Live page reports that; batch processing is unaffected).
# tini: forwards signals so `docker stop` shuts the server down cleanly.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libportaudio2 tini \
 && rm -rf /var/lib/apt/lists/*

# CUDA 12.6 builds of torch, torchaudio and torchcodec. Their CUDA 12 / cuDNN 9
# libraries (pip packages) are also what CTranslate2 (faster-whisper) loads, so
# one set serves both. torchaudio and torchcodec must come from the same index:
# their PyPI wheels are built for CUDA 13 and fail to load next to a CUDA 12
# torch. Same versions as the native environment (backend/constraints.txt).
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu126
ARG TORCH_VERSION=2.14.0
ARG TORCHAUDIO_VERSION=2.11.0
ARG TORCHCODEC_VERSION=0.16.0
RUN pip install "torch==${TORCH_VERSION}" "torchaudio==${TORCHAUDIO_VERSION}" \
      "torchcodec==${TORCHCODEC_VERSION}" --index-url "${TORCH_INDEX}"

WORKDIR /app

# Dependencies first (cached until pyproject.toml changes), then the code.
COPY backend/pyproject.toml backend/constraints.txt backend/
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
project = tomllib.load(open("backend/pyproject.toml", "rb"))["project"]
extras = project["optional-dependencies"]
print("\n".join(project["dependencies"] + extras["api"] + extras["eval"]))
EOF
# Constrained to the exact versions the native environment was tested with.
RUN pip install -r /tmp/requirements.txt -c backend/constraints.txt \
 && python -c "import torchaudio, torchcodec.decoders; assert '+cu126' in torchaudio.__version__"

COPY backend/ backend/
RUN pip install --no-deps ./backend

# Make the CUDA libraries that came with torch visible to CTranslate2.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cuda_runtime/lib

COPY --from=ui /ui/dist frontend/dist

# Provenance: the commit this image was built from (no .git inside).
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown
ARG GIT_BRANCH=
ENV MEETING_ASSISTANT_GIT_COMMIT=${GIT_COMMIT} \
    MEETING_ASSISTANT_GIT_DIRTY=${GIT_DIRTY} \
    MEETING_ASSISTANT_GIT_BRANCH=${GIT_BRANCH}
LABEL org.opencontainers.image.title="Meeting Assistant" \
      org.opencontainers.image.revision="${GIT_COMMIT}"

# Data (recordings, runs, accounts) and model downloads live in volumes.
ENV DATA_DIR=/app/data \
    FRONTEND_DIST=/app/frontend/dist \
    HF_HOME=/cache/huggingface \
    XDG_CACHE_HOME=/cache \
    API_HOST=0.0.0.0 \
    API_PORT=8000

RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data /cache \
 && chown -R app:app /app/data /cache
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["meeting-assistant", "serve", "--host", "0.0.0.0", "--port", "8000"]
