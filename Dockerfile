# Crossvet in a container: the OpenAI-compatible server for use away from your computer (a droplet, Komodo, a home server).
# Listening beyond localhost needs CROSSVET_TOKEN (16+ characters): without it the server refuses to start.
FROM python:3.13-slim

RUN useradd --create-home --uid 10001 crossvet
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && mkdir -p /data && chown crossvet /data

USER crossvet
ENV CROSSVET_DB=/data/chat.db
VOLUME ["/data"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4).status != 200)"
CMD ["crossvet", "serve", "--host", "0.0.0.0", "--port", "8787"]
