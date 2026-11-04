# Build from the repository root. Use the same source release as the hosted API.
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml backend/uv.lock ./
# Exact Python dependencies come from the checked-in uv lock.
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY deploy/storage/check_worker_access.py /deploy/storage/check_worker_access.py
RUN useradd --uid 10001 --create-home worker
USER worker
CMD ["/app/.venv/bin/python", "-m", "app.worker"]
