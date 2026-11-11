FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# The Debian security fixes published since the base image was built: the
# image is scanned (Trivy, HIGH and CRITICAL with a fix) and a base image a
# few weeks old is enough to fail it — zlib1g in November 2026. Nothing else
# is installed: curl served no healthcheck nor script (audit S32).
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
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
