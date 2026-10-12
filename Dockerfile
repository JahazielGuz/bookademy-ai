# syntax=docker/dockerfile:1

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Manifests first. This layer is rebuilt only when dependencies change, not on every
# code edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=build /app /app

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8001
# One worker on purpose. Extraction peaks near 400MB on a 750-page book, and two
# workers doing that at once is an out-of-memory kill rather than twice the speed.
# 0.0.0.0, because Fly's proxy and its health checks reach a machine over IPv4 on the
# 172.19.x.x private network — Django's own logs showed `Host: 172.19.31.138:8000`.
# Binding :: instead makes every health check fail with "connection refused", and an
# unhealthy machine is one the proxy will not route to.
#
# Nothing needs to reach this over IPv6: bookademy-core calls it through the Flycast
# proxy, not at its .internal address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
