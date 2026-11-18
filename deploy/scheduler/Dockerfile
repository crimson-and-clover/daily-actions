FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group scheduler
COPY src/ci_scheduler ./src/ci_scheduler
CMD ["/app/.venv/bin/python", "-m", "ci_scheduler", "--config", "/app/schedules.toml", "--state", "/data/dispatches.sqlite3"]
