# Crossvet chat for a server: the light install plus Langfuse recording. Built from the repository root:
#   docker compose -f deploy/chat/compose.yaml build
FROM python:3.13-slim

WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICES.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[langfuse]" \
    && useradd --create-home --uid 10001 crossvet \
    && mkdir /data && chown crossvet /data

USER crossvet
WORKDIR /data
ENV CROSSVET_CHAT_DB=/data/chat.db \
    CROSSVET_CHAT_OAUTH_DB=/data/chat-oauth.db \
    CROSSVET_CHAT_CONFIG=/data/crossvet-chat.toml \
    PYTHONUNBUFFERED=1
EXPOSE 8787 8788
CMD ["crossvet", "chat", "serve", "--host", "0.0.0.0", "--port", "8787"]
