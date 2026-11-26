# Running Crossvet every day

## On your own computer (recommended)

```bash
crossvet service install            # the server starts at login and restarts if it stops
crossvet service install --weekly   # and a Monday job: score run, tune auto, report --week --json
crossvet service status             # are the files there, and does http://127.0.0.1:8787/health answer?
crossvet service uninstall
```

- **macOS:** launchd agents in `~/Library/LaunchAgents` (`com.github.j-zulick.crossvet.plist`, and `.weekly.plist`), logs in `~/Library/Logs/crossvet.log` and `crossvet-weekly.log`.
- **Linux:** systemd user units in `~/.config/systemd/user` (`crossvet.service`, and `crossvet-weekly.service` with a timer).
- The server listens on 127.0.0.1 only. Keys come from `~/.config/crossvet/.env`, settings from `~/.config/crossvet/crossvet.toml`, so the service sees what `crossvet start` sees.
- Weekly reports are kept in `~/.local/share/crossvet/weekly/<date>.json`. `tune auto` changes nothing unless `[router] auto_tune = true`, and `score run` judges nothing unless `[score] enabled = true`.
- `--no-load` writes the files without starting anything, so you can read them first.

Then point Hermes (or any OpenAI-style app) at `http://127.0.0.1:8787/v1` and the MCP apps at `crossvet mcp` as in [CHAT.md](CHAT.md). Leave out `crossvet start` once the service runs.

## On a server (a droplet, a home server, Komodo)

The repository has a `Dockerfile` and a `compose.yaml`:

```bash
cp .env.example .env     # add your keys and CROSSVET_TOKEN (16+ characters: openssl rand -base64 24)
docker compose up -d
curl -s http://127.0.0.1:8787/health
```

- The container runs `crossvet serve --host 0.0.0.0` as a non-root user. Without a `CROSSVET_TOKEN` of at least 16 characters it refuses to start, because it would listen beyond localhost.
- `compose.yaml` publishes the port on the server's 127.0.0.1 only. To reach it from elsewhere, put a TLS reverse proxy (Caddy, nginx, Traefik) in front, and send `Authorization: Bearer <CROSSVET_TOKEN>` from your apps.
- The log and the lab file live in the `crossvet-data` volume (`/data/chat.db`, `/data/lab.db`). `docker compose exec crossvet crossvet backup /data/backup` makes a copy with SHA-256 sums.
- **Komodo:** create a Stack from this repository (or your fork) with `compose.yaml` as the compose file, and put the variables from `.env.example` in the Stack's environment. Komodo builds the image and keeps it running.

The container image is not built in the project's CI or its live runs yet; build it yourself with `docker compose build`.
