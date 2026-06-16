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

# Install Python deps first (separate layer — only rebuilds on pyproject.toml changes)
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.2.0" \
    "Pillow>=10.3.0" \
    "chromadb>=0.5.0" \
    "python-multipart>=0.0.9" \
    "aiofiles>=23.2.1" \
    "python-dotenv>=1.0.1" \
    "httpx>=0.27.0"

# Copy source code
COPY backend/ .
COPY scripts/ ./scripts

# Runtime dirs + symlink so seed_templates.py resolves /backend → /app
RUN mkdir -p static/generated fonts templates && ln -sf /app /backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8000}/health || exit 1

# PORT is injected by Render at runtime; fallback to 8000 for local Docker
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
