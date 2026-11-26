"""crossvet: one chat, any model. You pick the model; Crossvet never picks it for you.

    crossvet start              check your keys, print the settings for Hermes, Cursor, Claude Code and Codex, serve
    crossvet chat [--model M]   chat in this terminal (/model NAME switches; /models, /cost, /help)
    crossvet ask -m M "..."     one question to one model
    crossvet models             the models you can name, with short names and prices
    crossvet cost [--days N]    spend per model
    crossvet log [-n N]         the latest turns from every app
    crossvet serve              the OpenAI-compatible server only (http://127.0.0.1:8787/v1)
    crossvet mcp [--http]       the MCP server (list_models, ask_model, recent_turns)
    crossvet init               write a settings file from the keys you have
    crossvet doctor             check keys, settings and the local log

`crossvet chat start`, `crossvet chat mcp` and the other 1.x spellings still work.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from crossvet import __version__, providers
from crossvet.config import (
    HOME,
    Config,
    builtin,
    callable_now,
    load,
    load_env,
    old_config,
    render,
)

KEPT = ("start", "serve", "mcp", "chat", "ask", "models", "cost", "log", "init", "doctor")
REMOVED = ("route", "routes", "compare", "challenge", "feedback", "note", "bench", "tune", "sync", "report", "dashboard",
           "learn", "replay", "export", "handoff", "backup", "restore", "prune")
HISTORY_MESSAGES = 40  # the terminal chat sends at most this many earlier messages


# --- what to paste into each app ---

def app_settings(host: str, port: int, token: str) -> str:
    """Return the settings for Hermes, Cursor, Claude Code and Codex."""
    base = f"http://{host}:{port}/v1"
    command = shutil.which("crossvet") or "crossvet"
    key = "the value of CROSSVET_TOKEN" if token else "any text (not checked on this computer)"
    cursor = json.dumps({"mcpServers": {"crossvet": {"command": command, "args": ["mcp"]}}}, indent=2)
    return f"""Hermes, or any app with an OpenAI-compatible provider (keep `crossvet start` running):
  base URL   {base}
  API key    {key}
  model      default, or any name from `crossvet models`
  Hermes: in ~/.hermes/config.yaml set  model: {{provider: custom, base_url: {base}, default: default}}
  then pick a model from Hermes's model menu, or type /model NAME in the chat.

Claude Code:  claude mcp add --scope user crossvet -- {command} mcp
Codex:        codex mcp add crossvet -- {command} mcp
Cursor:       add to ~/.cursor/mcp.json
{cursor}
The MCP tools: list_models, ask_model(request, model), recent_turns.
"""


# --- commands ---

def cmd_start(args: argparse.Namespace) -> int:
    """Check keys, print the app settings, and serve."""
    cfg = load()
    ready = [m for m in cfg.menu() if callable_now(m)]
    if not ready:
        print("No model can be called yet: set at least one key (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, "
              f"XAI_API_KEY or OPENROUTER_API_KEY) in your environment or in {HOME / '.env'}, then run "
              "`crossvet start` again. `crossvet doctor` shows what is missing.", file=sys.stderr)
        return 1
    print(f"Crossvet {__version__}   settings: {cfg.source or 'built in'}   default model: {cfg.default_model or 'none'}")
    print(f"Models ready: {', '.join(ready)}\n")
    print(app_settings(args.host, args.port, os.environ.get("CROSSVET_TOKEN", "")))
    if args.no_serve:
        return 0
    from crossvet.server import serve

    return serve(args.host, args.port)


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the OpenAI-compatible server."""
    from crossvet.server import serve

    return serve(args.host, args.port)


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run the MCP server."""
    from crossvet.mcp_server import main

    return main(http=args.http, host=args.host, port=args.port)


def cmd_models(_: argparse.Namespace) -> int:
    """Print the model menu."""
    from crossvet.core import Crossvet

    print(Crossvet().models_text())
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    """Print spend per model."""
    from crossvet.core import Crossvet

    since = time.time() - args.days * 86400 if args.days else 0.0
    print(Crossvet().cost_text(since=since, title=f"Spend in the last {args.days:g} days" if args.days else "Spend"))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    """Print the latest turns."""
    from crossvet.core import Crossvet
    from crossvet.mcp_server import tools

    print(tools(Crossvet())["recent_turns"](args.n))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """Ask one model one question and stream the answer."""
    from crossvet.core import Answer, Crossvet

    text = " ".join(args.text) if args.text else sys.stdin.read()
    if not text.strip():
        print("nothing to ask: give the question as words, or on standard input", file=sys.stderr)
        return 2
    messages = ([{"role": "system", "content": args.system}] if args.system else []) + [{"role": "user", "content": text}]
    for item in Crossvet().ask_stream(args.model, messages, app="terminal"):
        if isinstance(item, Answer):
            print(f"\n\n[{item.footer()}]", file=sys.stderr)
        else:
            print(item, end="", flush=True)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """Chat in this terminal."""
    from crossvet.core import Answer, Crossvet
    from crossvet.store import new_thread

    cv = Crossvet()
    model = cv.config.resolve(args.model)
    thread, messages = new_thread(), []
    print(f"Crossvet {__version__}: talking to {model}. /model NAME switches, /models lists, /cost, /new, /quit.")
    while True:
        try:
            line = input("\nyou> ").strip()
        except EOFError:
            print()
            return 0
        if not line:
            continue
        words = line.split()
        name = words[0].lower()
        if name in ("/quit", "/exit"):
            return 0
        if name == "/model":
            if len(words) > 1:
                try:
                    model = cv.config.resolve(words[1])
                except (ValueError, providers.ProviderError) as exc:
                    print(exc)
                    continue
                print(f"now talking to {model}")
            else:
                print(f"talking to {model}")
            continue
        if name == "/models":
            print(cv.models_text())
            continue
        if name == "/cost":
            print(cv.cost_text(thread=thread, title="This conversation"))
            continue
        if name == "/new":
            thread, messages = new_thread(), []
            print("new conversation")
            continue
        if name == "/help":
            print("/model NAME, /model, /models, /cost, /new, /quit")
            continue
        messages.append({"role": "user", "content": line})
        print(f"{model}> ", end="", flush=True)
        try:
            pieces = []
            for item in cv.ask_stream(model, messages[-HISTORY_MESSAGES:], thread=thread, app="terminal"):
                if isinstance(item, Answer):
                    print(f"\n[{item.footer()}]")
                else:
                    pieces.append(item)
                    print(item, end="", flush=True)
            messages.append({"role": "assistant", "content": "".join(pieces)})
        except (providers.ProviderError, RuntimeError) as exc:
            messages.pop()
            print(f"\n{model} did not answer: {exc}\nPick another with /model NAME, or try again.")


def cmd_init(args: argparse.Namespace) -> int:
    """Write a settings file from the keys you have."""
    path = Path(args.path).expanduser() if args.path else HOME / "crossvet.toml"
    if path.exists() and not args.force:
        print(f"{path} exists; add --force to replace it", file=sys.stderr)
        return 1
    cfg = builtin()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(cfg))
    print(f"wrote {path}")
    if not cfg.models:
        print("No OPENAI_API_KEY or ANTHROPIC_API_KEY was found, so the model list is empty. Add keys, or add models "
              "by hand (any provider:model, for example google:..., xai:..., openrouter:vendor/model, ollama:...).")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    """Check keys, settings and the local log; never calls a model."""
    problems = 0
    print(f"Crossvet {__version__}")
    for provider in providers.PROVIDERS:
        name = providers.key_name(provider)
        state = "no key needed" if not name else ("set" if os.environ.get(name) else "not set")
        print(f"  {provider:<11} {name or '-':<20} {state}")
    old = old_config()
    if old:
        print(f"note: {old} is a Crossvet 1.x settings file; 2.x does not read it (`crossvet init` writes a 2.x file)")
    stale = sorted(k for k in os.environ if k.startswith("CROSSVET_CHAT_"))
    if stale:
        print(f"note: {', '.join(stale)} are 1.x names; 2.x reads CROSSVET_CONFIG, CROSSVET_DB and CROSSVET_TOKEN")
    try:
        cfg: Config = load()
    except (ValueError, providers.ProviderError) as exc:
        print(f"settings: {exc}")
        return 1
    print(f"settings: {cfg.source or 'built in (no settings file)'}")
    print(f"default model: {cfg.default_model or 'none'}")
    for model in cfg.menu():
        if not callable_now(model):
            problems += 1
            print(f"  {model}: its key is not set")
        if cfg.price(model) is None and cfg.max_usd_per_call > 0:
            print(f"  {model}: no price, so /cost and the per-call cap cannot count it")
    if not any(callable_now(m) for m in cfg.menu()):
        problems += 1
        print("no listed model can be called: add a key")
    try:
        from crossvet.store import Store

        store = Store(cfg.store_path())
        print(f"log: {cfg.store_path()} ({store.db.execute('SELECT COUNT(*) FROM turns').fetchone()[0]} turns, "
              f"${store.spent_today():.4f} today)")
    except Exception as exc:  # noqa: BLE001 - report any problem opening the log
        problems += 1
        print(f"log: {exc}")
    print("ok" if not problems else f"{problems} problem(s)")
    return 0 if not problems else 1


# --- parsing ---

def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(prog="crossvet", description="One chat, any model. You pick the model.",
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-V", "--version", action="version", version=f"crossvet {__version__}")
    sub = parser.add_subparsers(dest="command")

    def server_args(p: argparse.ArgumentParser, port: int) -> None:
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=port)

    p = sub.add_parser("start", help="check keys, print the settings for each app, and serve")
    server_args(p, 8787)
    p.add_argument("--no-serve", action="store_true", help="print the settings and stop")
    p.set_defaults(func=cmd_start)
    p = sub.add_parser("serve", help="the OpenAI-compatible server")
    server_args(p, 8787)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("mcp", help="the MCP server for Cursor, Claude Code, Codex")
    server_args(p, 8788)
    p.add_argument("--http", action="store_true", help="Streamable HTTP on this computer instead of stdio")
    p.set_defaults(func=cmd_mcp)
    p = sub.add_parser("chat", help="chat in this terminal")
    p.add_argument("-m", "--model", default=None, help="provider:model or a short name (default: default_model)")
    p.set_defaults(func=cmd_chat)
    p = sub.add_parser("ask", help="one question to one model")
    p.add_argument("-m", "--model", default=None, help="provider:model or a short name (default: default_model)")
    p.add_argument("-s", "--system", default="", help="instructions for the model")
    p.add_argument("text", nargs="*", help="the question (default: standard input)")
    p.set_defaults(func=cmd_ask)
    sub.add_parser("models", help="the models you can name").set_defaults(func=cmd_models)
    p = sub.add_parser("cost", help="spend per model")
    p.add_argument("--days", type=float, default=0, help="only the last N days")
    p.set_defaults(func=cmd_cost)
    p = sub.add_parser("log", help="the latest turns from every app")
    p.add_argument("-n", type=int, default=10)
    p.set_defaults(func=cmd_log)
    p = sub.add_parser("init", help="write a settings file from the keys you have")
    p.add_argument("--path", default="", help=f"default {HOME / 'crossvet.toml'}")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="check keys, settings and the local log").set_defaults(func=cmd_doctor)
    return parser


def normalize(argv: list[str]) -> list[str] | str:
    """Map 1.x spellings (``crossvet chat start``) to 2.x; return a message for a removed command."""
    if argv[:1] != ["chat"] or len(argv) < 2:
        return argv
    second = argv[1]
    if second in ("--version", "-V"):
        return ["--version"]
    if second in REMOVED:
        return (f"`crossvet chat {second}` was removed in Crossvet 2.0: Crossvet no longer chooses, rates or compares "
                "models. Name the model yourself (`crossvet models` lists them). See docs/MIGRATING.md.")
    if second in KEPT and second != "chat":
        return argv[1:]
    return argv


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    load_env()
    argv = list(sys.argv[1:] if argv is None else argv)
    normal = normalize(argv)
    if isinstance(normal, str):
        print(normal, file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(normal)
    if not getattr(args, "func", None):
        print(__doc__.strip())
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except (providers.ProviderError, ValueError) as exc:
        print(f"crossvet: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:  # a spend cap, or a log written by a newer Crossvet
        print(f"crossvet: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
