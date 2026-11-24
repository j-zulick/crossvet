# Crossvet API: the LangGraph server with both editions (deep_researcher, deep_agent).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project

COPY src ./src
COPY tests ./tests
COPY docker/langgraph.json ./langgraph.json
RUN uv sync --locked \
    && useradd --create-home --uid 10001 crossvet \
    && chown -R crossvet /app

USER crossvet
EXPOSE 2024

# Development server (in-memory state). Keys come from the environment, never the image.
CMD ["/app/.venv/bin/langgraph", "dev", "--config", "langgraph.json", "--host", "0.0.0.0", "--port", "2024", "--no-browser", "--no-reload"]
