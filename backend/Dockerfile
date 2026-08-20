FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# uv binary (https://docs.astral.sh/uv/guides/integration/docker/)
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
# Put the project venv on PATH so alembic/uvicorn resolve in the entrypoint.
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies in a cached layer (no app code yet, runtime deps only).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev

COPY alembic.ini ./
COPY app ./app

ENTRYPOINT ["bash", "/app/app/scripts/entrypoint.sh"]
CMD ["api"]
