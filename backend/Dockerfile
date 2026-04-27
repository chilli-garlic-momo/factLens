# ── Stage 1: builder ──────────────────────────────────────────────────────────
# Use full image to compile C-extensions in dependencies (e.g. pydantic-core)
FROM python:3.11-slim AS builder

WORKDIR /build

# Install deps into an isolated venv so we copy only that into the final image
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
# slim = no build tools, no pip, much smaller image (~200MB vs ~1GB)
FROM python:3.11-slim AS runtime

# Don't write .pyc files, don't buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

# Copy the compiled venv from builder — no pip needed in final image
COPY --from=builder /venv /venv

# Copy only the backend source (not the extension, assets, etc.)
COPY main.py .
COPY kg.json .

# Security: never run as root inside a container
RUN adduser --disabled-password --no-create-home factlens
USER factlens

EXPOSE 8000

# Health check — Docker (and Cloud Run) will hit this to confirm the app is up
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]