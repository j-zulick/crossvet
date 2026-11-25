# Crossvet chat on your own server

The chat from anywhere: Cursor can use it as its chat model, the ChatGPT and claude.ai apps can connect after you sign in, and the activity page works from your phone. One small server (1 GB of memory is plenty), a domain name, and Docker.

**Not yet run on a live server.** Each piece runs and is tested on its own (the servers, sign-in, the Compose file's syntax); the Docker image is built in CI. Check each step below on the first run.

## Set up (once)

1. **DNS:** an `A` record for a subdomain (for example `chat.yourdomain.com`) pointing at the server's address. Ports 80 and 443 must be open: Caddy uses them to get the certificate.
2. **Files:** copy the repository to the server (`git clone`), then in `deploy/chat/`:
   ```bash
   cp .env.example .env
   ```
   Fill in `.env`:
   - `CROSSVET_DOMAIN`: the subdomain.
   - `CROSSVET_CHAT_TOKEN`: a long random passphrase, at least 16 characters (`openssl rand -base64 24` makes one). It is the API's bearer token and what you sign in with.
   - `OPENROUTER_API_KEY` (or vendor keys), and the `LANGFUSE_*` keys to record turns.
3. **Build and write the settings:**
   ```bash
   docker compose build
   docker compose run --rm api crossvet chat init --openrouter --out /data/crossvet-chat.toml
   ```
4. **Start:** `docker compose up -d`.

**Done when:**
- `https://YOUR-DOMAIN/health` answers `{"ok": true, ...}`.
- `curl -H "Authorization: Bearer $CROSSVET_CHAT_TOKEN" https://YOUR-DOMAIN/v1/models` lists the models.
- `https://YOUR-DOMAIN/.well-known/oauth-authorization-server` shows the sign-in endpoints.

## Connect the apps

| App | Where | Value |
|---|---|---|
| Cursor | Settings → Models → OpenAI API key and "Override OpenAI Base URL" | base URL `https://YOUR-DOMAIN/v1`, key = `CROSSVET_CHAT_TOKEN`, model `auto` |
| Hermes, Open WebUI, scripts | An OpenAI-compatible provider | the same three values |
| claude.ai | Settings → Connectors → add a custom connector | `https://YOUR-DOMAIN/mcp`; you are sent to the sign-in page |
| ChatGPT | Settings → Connectors (developer mode) → add an MCP server | `https://YOUR-DOMAIN/mcp`; you are sent to the sign-in page |
| Activity page | A browser | `https://YOUR-DOMAIN/?token=YOUR-TOKEN` |

The apps' menus change often, so the paths above are where to look, not a guarantee. Which plans allow custom connectors is up to each vendor. In Cursor, the override sends Cursor's own model requests to Crossvet too.

## Run it

- **Update:** `git pull && docker compose build && docker compose up -d`.
- **Back up the store:** `docker compose exec api crossvet chat backup /data/backup-$(date +%F).db`, then copy the file off the server.
- **Logs:** `docker compose logs -f api mcp`.
- **Sign everyone out:** stop the stack, then delete `chat-oauth.db` from the `data` volume. Apps will ask you to sign in again.
- **Change the passphrase:** edit `CROSSVET_CHAT_TOKEN` in `.env`, then run `docker compose up -d`.

## What protects it

- **The API:** every request needs the bearer token.
- **The MCP server:**
  - Signing in requires the passphrase.
  - PKCE is required.
  - Codes work once.
  - Tokens are stored only as hashes, are accepted only for this server, and expire after 1 hour (refresh tokens after 30 days, replaced on every use).
  - Requests for any other host name are refused.
  - Five wrong passphrases in 15 minutes lock sign-in for the rest of that window.
- **The connection:** Caddy serves HTTPS only (HSTS on).
- **Keys:** they stay in `.env` on the server.
