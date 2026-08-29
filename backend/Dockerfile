# ---- Builder stage: install dependencies into a venv ----
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

# ---- Runtime stage: slim, no build toolchain ----
FROM python:3.11-slim

WORKDIR /app

# System deps: curl (healthcheck), libfreetype6 + fontconfig (Pillow fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libfreetype6 \
    libfontconfig1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /usr/share/fonts/truetype/Anton-Regular.ttf \
       "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy source code
COPY backend/ .
COPY scripts/ ./scripts

# Runtime dirs + symlink so seed_templates.py resolves /backend → /app
RUN mkdir -p static/generated fonts templates && ln -sf /app /backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8000}/health || exit 1

# PORT is injected by Render and by Cloud Run at runtime; fallback to 8000 for local Docker
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
