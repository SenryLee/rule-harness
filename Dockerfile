# ---- Stage 1: Build frontend ----
FROM node:20-slim AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# ---- Stage 2: Final image ----
FROM python:3.11-slim

# System deps for PyMuPDF, lxml, pdfplumber
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY pyproject.toml ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir -e .

# Copy frontend build output
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Copy runtime assets
COPY profiles/ ./profiles/
COPY config.default.yaml ./

EXPOSE ${PORT:-8000}

# Use shell form so $PORT (injected by Railway at runtime) expands correctly
CMD python3 -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}
