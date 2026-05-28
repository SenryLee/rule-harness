# syntax=docker/dockerfile:1.6
# ─────────────────────────────────────────────────────────────
# Rule Harness · Multi-stage Dockerfile (Railway / Fly / local)
# ─────────────────────────────────────────────────────────────

# ---- Stage 1: build the frontend bundle (React + Vite + Tailwind) ----
FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend

# Copy lockfile first to leverage layer cache
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Now copy the rest of the frontend and build
COPY frontend/ ./
RUN npm run build && \
    test -f dist/index.html || (echo "✗ frontend build produced no dist/index.html" && exit 1)

# ---- Stage 2: runtime image ----
FROM python:3.11-slim

# Python runtime knobs:
#  - PYTHONDONTWRITEBYTECODE: don't litter the image with .pyc
#  - PYTHONUNBUFFERED: flush stdout/stderr immediately so Railway logs are live
#  - PIP_*: speed up pip + avoid network detours
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# System libs required by pdfplumber / PyMuPDF / lxml
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (so source changes don't bust dep layer)
COPY pyproject.toml ./
COPY backend/ ./backend/
RUN pip install -e .

# Frontend bundle from Stage 1
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Runtime assets (profiles, default config, theme keys, red-line dictionary)
COPY profiles/ ./profiles/
COPY config.default.yaml redline_keywords.yaml theme_keys.yaml ./

# Pre-create writable runtime dirs. Without this, the FastAPI startup hook
# fails at storage.init_db() with "unable to open database file" because
# /app/data does not exist yet, and the first /api/* call also tries to
# mkdir + write into /app/data.
RUN mkdir -p /app/data/uploads /app/data/exports

# Document the listening port (Railway injects $PORT at runtime; do NOT bake
# a shell expression into EXPOSE — Docker does not evaluate it).
EXPOSE 8000

# Shell form so $PORT gets expanded by the shell at container start.
CMD python3 -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}
