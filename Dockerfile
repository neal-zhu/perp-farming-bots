FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 bot
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY third_party ./third_party
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev \
    && mkdir /app/data && chown -R bot:bot /app
USER bot
ENV PFB_HOST=0.0.0.0 PFB_DATA_DIR=/app/data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3)"]
CMD ["/app/.venv/bin/perp-farming-bots"]
