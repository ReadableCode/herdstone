FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Dependencies first (cached layer), then the package itself. The second sync
# installs the project so the `herdstone` console script exists.
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

COPY engine/ ./engine/

RUN uv sync --frozen --no-dev

EXPOSE 8787

# Inventory path comes from HERDSTONE_HOSTS (compose mounts hosts.json at
# /config/hosts.json); API keys/tokens come from the container environment.
CMD ["uv", "run", "herdstone", "web", "--host", "0.0.0.0", "--port", "8787"]
