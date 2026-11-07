#!/usr/bin/env bash
# Crossvet quickstart: tools check -> install -> keys and models -> setup check -> first run.
# Usage: scripts/quickstart.sh [--skip-run]
# Safe to re-run. Never prints API keys.
set -euo pipefail
cd "$(dirname "$0")/.."

skip_run=false
[[ "${1:-}" == "--skip-run" ]] && skip_run=true

step() { printf '\n== %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

step "1/5 Tools"
missing=()
for tool in git uv; do have "$tool" && echo "ok      $tool" || { echo "MISSING $tool"; missing+=("$tool"); }; done
for tool in gh docker node pnpm ollama; do have "$tool" && echo "ok      $tool (optional)" || echo "-       $tool (optional)"; done
if ((${#missing[@]})); then
  if have brew; then
    read -r -p "Install ${missing[*]} with Homebrew? [y/N] " yn
    [[ "$yn" =~ ^[Yy]$ ]] && brew install "${missing[@]}" || { echo "Install ${missing[*]} and re-run."; exit 1; }
  else
    echo "Install ${missing[*]} (https://docs.astral.sh/uv/ for uv) and re-run."; exit 1
  fi
fi

step "2/5 Python dependencies"
uv sync --locked

step "3/5 Keys and models (hidden input; Enter skips a key)"
uv run crossvet-setup --check

step "4/5 Setup check"
uv run python -m open_deep_research.doctor || { echo "Fix the FAIL lines above (edit .env or re-run this script), then re-run."; exit 1; }

if $skip_run; then echo; echo "Done. Run 'uv run crossvet-try' when ready."; exit 0; fi
step "5/5 First research run (a few minutes; uses your API keys)"
uv run crossvet-try || true
echo
echo "Send the newest first-run/*/share.md (it contains no keys) to review the run."
