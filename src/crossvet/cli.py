"""crossvet: one chat, any model. Pick the model yourself, or name `auto` and let Crossvet choose.

    crossvet start              check your keys, print the settings for Hermes, Cursor, Claude Code and Codex, serve
    crossvet chat [--model M]   chat in this terminal (/model NAME switches; /why, /good, /bad, /retry, /cost, /help)
    crossvet ask -m M "..."     one question to one model (-m auto lets Crossvet choose)
    crossvet models             the models you can name, with short names and prices
    crossvet route "..."        which model auto would choose, and why (calls nothing)
    crossvet compare -m A -m B "..."   the same question to several models; challenge: another vendor checks an answer
    crossvet rate good|bad      rate the last answer; tune: proposals from ratings or scores, accept, roll back, auto
    crossvet bench              the Sarasota used-car benchmark, scored in code
    crossvet replay -m M        past questions on another model, judged blind
    crossvet review --staged    another vendor reviews your change; findings checked in code; --fix, --apply
    crossvet score run|shadow|calibrate, leaderboard   judge a sample of answers (opt-in); score per model and kind
    crossvet note / notes       notes every app shares;  handoff: a task to Claude Code or Codex
    crossvet report / dashboard / export / sync    your numbers, as Markdown, HTML, JSON lines or in Langfuse
    crossvet backup / restore / prune             look after the local files
    crossvet cost / log / why   spend, the latest turns, the last auto decision
    crossvet serve / mcp        the OpenAI-compatible server, the MCP server
    crossvet service install    run the server at login (launchd or systemd), and optionally a weekly job
    crossvet init / doctor      write a settings file; check keys, settings and the local files

`crossvet chat start`, `crossvet chat route` and the other 1.x spellings still work.
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

RENAMED = {"routes": "tune", "feedback": "rate", "learn": "tune"}  # 1.x names that moved
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
    model = cv.label(args.model)
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
                    model = cv.label(words[1])
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
            print("/model NAME (auto lets Crossvet choose), /model, /models, /cost, /why, /good, /bad [note], "
                  "/retry [stronger], /new, /quit")
            continue
        if name == "/why":
            decision = cv.lab.decision(thread=thread)
            print("no answer here was chosen by auto" if decision is None else
                  f"{decision['model']} (kind {decision['kind']}, slot {decision['slot']}): {decision['reason']}")
            continue
        if name in ("/good", "/bad"):
            last = next((t for t in reversed(cv.store.turns(thread, 200)) if t.role == "assistant"), None)
            if last is None:
                print("nothing to rate yet")
            else:
                cv.lab.rate(last.id, 1 if name == "/good" else -1, " ".join(words[1:]), source="terminal")
                print(f"rated #{last.id} ({last.model}) {name[1:]}")
            continue
        if name == "/retry":
            if not messages or messages[-1]["role"] != "assistant":
                print("nothing to ask again")
                continue
            messages.pop()
            if len(words) > 1 and words[1].lower() == "stronger":
                from crossvet import routing

                decision = cv.lab.decision(thread=thread)
                retry_model = "crossvet/best" if (decision or {}).get("slot") == "strong" else \
                    f"crossvet/{routing.stronger(cv.config, decision)}"
            else:
                retry_model = model
            print(f"{retry_model}> ", end="", flush=True)
            pieces = []
            for item in cv.ask_stream(retry_model, messages[-HISTORY_MESSAGES:], thread=thread, app="terminal"):
                if isinstance(item, Answer):
                    print(f"\n[{item.footer()}]")
                else:
                    pieces.append(item)
                    print(item, end="", flush=True)
            messages.append({"role": "assistant", "content": "".join(pieces)})
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


def _cv():  # noqa: ANN202 - imported late so --version and doctor stay light
    from crossvet.core import Crossvet

    return Crossvet()


def cmd_route(args: argparse.Namespace) -> int:
    """Show which model auto would choose for a request, and why; nothing is called."""
    from crossvet.config import load as load_config
    from crossvet.routing import decide

    text = " ".join(args.text) if args.text else sys.stdin.read()
    print(decide(load_config(), [{"role": "user", "content": text}], args.model).explain())
    return 0


def cmd_why(_: argparse.Namespace) -> int:
    """Show the latest decision auto made, in any app."""
    decision = _cv().lab.decision()
    if decision is None:
        print("auto has not chosen a model yet")
        return 0
    print(f"turn #{decision['turn_id']}: {decision['model']} (kind {decision['kind']}, slot {decision['slot']}, "
          f"goal {decision['goal']}): {decision['reason']}")
    for step in decision["steps"]:
        print(f"  {step['model']}: {step['outcome']}")
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    """Rate an answer good or bad (the latest one unless --turn is given)."""
    cv = _cv()
    turn = args.turn or next((t.id for t in cv.store.recent(50) if t.role == "assistant"), 0)
    if not turn:
        print("there is no answer to rate yet", file=sys.stderr)
        return 1
    cv.lab.rate(turn, 1 if args.rating == "good" else -1, " ".join(args.note), source="terminal")
    print(f"rated #{turn} {args.rating}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Ask several models the same question."""
    from crossvet import multi

    text = " ".join(args.text) if args.text else sys.stdin.read()
    print(multi.compare_text(multi.compare(_cv(), args.model, text, app="terminal")))
    return 0


def cmd_challenge(args: argparse.Namespace) -> int:
    """Have another vendor's model try to break an answer (the latest one unless --turn is given)."""
    from crossvet import multi

    cv = _cv()
    rows = cv.store.db.execute("SELECT a.id, a.content, a.model, q.content question FROM turns a JOIN turns q ON "
                               "q.thread = a.thread AND q.id = a.id - 1 WHERE a.role = 'assistant'"
                               + (" AND a.id = ?" if args.turn else "") + " ORDER BY a.id DESC LIMIT 1",
                               (args.turn,) if args.turn else ()).fetchall()
    if not rows:
        print("there is no answer to challenge", file=sys.stderr)
        return 1
    row = rows[0]
    result = multi.challenge(cv, row["question"], row["content"], row["model"], args.model or "")
    print(f"challenging #{row['id']} ({row['model']})\n" + multi.challenge_text(result))
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    """Save a note."""
    print(f"saved note #{_cv().lab.save_note(' '.join(args.text), args.tags)}")
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    """Search the notes (the latest ones without words)."""
    found = _cv().lab.search_notes(" ".join(args.query), limit=args.n)
    print("\n".join(f"#{n['id']} {time.strftime('%Y-%m-%d', time.localtime(n['ts']))} {n['text']}" for n in found) or "no notes")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Run the chat benchmark and write its results page."""
    from crossvet import bench

    cv = _cv()
    if args.review:
        return bench_review(cv, args)
    cases = bench.SUITES[args.suite][: args.limit or None]
    models = [cv.config.resolve(m) for m in (args.model or cv.config.models)]
    if not models:
        print("no models to benchmark: pass -m MODEL (or set models in crossvet.toml)", file=sys.stderr)
        return 2
    rows = bench.run(cv, models, cases, run_code=args.run_code,
                     on_result=lambda r: print(f"{r['model']:<32} {r['case']:<20} {r['score']:.2f} {r['error'][:60]}", flush=True))
    out = Path(args.out or f"docs/benchmarks/{time.strftime('%Y-%m-%d')}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    command = "crossvet bench " + " ".join(f"-m {m}" for m in models) + f" --suite {args.suite}" + (" --run-code" if args.run_code else "")
    (out / "README.md").write_text(bench.results_page(rows, date=time.strftime("%Y-%m-%d"), suite=args.suite, command=command,
                                                      run_code=args.run_code))
    print(f"\n{bench.table(rows)}\n\nwrote {out}/README.md and results.jsonl")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Have a model from another vendor review a change."""
    from crossvet import review

    diff = review.git_diff(staged=args.staged, base=args.base) if (args.staged or args.base) else sys.stdin.read()
    if not diff.strip():
        print("nothing to review: stage a change (--staged), name a base branch (--base main), or pipe a diff in", file=sys.stderr)
        return 2
    result = review.run(_cv(), diff, args.task, author=args.author, reviewer=args.reviewer, fix=args.fix, apply=args.apply,
                        rounds=args.rounds, record_dir=None if args.no_record else Path(".crossvet/reviews"))
    print(review.as_json(result) if args.json else review.text(result))
    return 0


def _bench_cell(row: dict) -> str:
    if row["error"]:
        return "error"
    if row.get("clean"):
        return "FALSE ALARM" if row["false_alarm"] else "quiet"
    return "caught" if row["caught"] else "missed"


def bench_review(cv, args: argparse.Namespace) -> int:  # noqa: ANN001 - a Crossvet
    """Run the review benchmark and write its results page."""
    from crossvet import review_bench

    reviewers = args.model or [m for m in cv.config.slot_models("reviewer")][:2]
    if not reviewers:
        print("no reviewers to benchmark: pass -m MODEL", file=sys.stderr)
        return 2
    set_name = args.set or "planted"
    rows = review_bench.run(cv, reviewers, review_bench.SETS[set_name][: args.limit or None],
                            on_result=lambda r: print(f"{r['reviewer']:<32} {r['case']:<20} "
                                                      f"{_bench_cell(r)} {r['error'][:60]}", flush=True))
    suffix = "-review" if set_name == "planted" else f"-review-{set_name}"
    out = Path(args.out or f"docs/benchmarks/{time.strftime('%Y-%m-%d')}{suffix}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    command = ("crossvet bench --review " + (f"--set {set_name} " if set_name != "planted" else "")
               + " ".join(f"-m {cv.config.resolve(m)}" for m in reviewers))
    (out / "README.md").write_text(review_bench.results_page(rows, command, set_name))
    for model, stats in review_bench.summary(rows).items():
        alarms = f", {int(stats['false_alarms'])} false alarm(s) on {int(stats['clean'])} clean" if stats["clean"] else ""
        print(f"{model}: caught {int(stats['caught'])} of {int(stats['cases'])}{alarms}, ${stats['cost']:.4f}")
    print(f"wrote {out}/README.md and results.jsonl")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    """Judge a sample of answers, judge shadow answers, or compare the judge with your ratings."""
    from crossvet import score

    cv = _cv()
    if args.action == "run":
        print(score.run(cv, limit=args.limit, force_all=args.all))
    elif args.action == "shadow":
        print(score.shadow(cv, limit=args.limit))
    else:
        print(score.calibration_text(cv))
    return 0


def cmd_leaderboard(args: argparse.Namespace) -> int:
    """Print score and cost per model for each kind of task."""
    from crossvet import score

    print(score.leaderboard_text(_cv(), args.days))
    return 0


def cmd_service(args: argparse.Namespace) -> int:
    """Install, check or remove the background service."""
    from crossvet import service

    if args.action == "install":
        print(service.install(args.port, weekly=args.weekly, load=not args.no_load))
    elif args.action == "uninstall":
        print(service.uninstall())
    else:
        print(service.status(args.port))
    return 0


def cmd_tune(args: argparse.Namespace) -> int:
    """Show ratings and proposals; accept, reject or roll back a route."""
    from crossvet import tuning

    cv = _cv()
    if args.action == "show":
        print(tuning.text(cv))
        return 0
    if args.action == "scores":
        found = tuning.propose_from_scores(cv)
        print("\n".join(f"#{r['id']} {r['kind']}: put {r['model']} first instead of {r['previous'] or 'the slot order'}. "
                        f"{r['evidence']}" for r in found) or "No proposal from scores (too few judged answers, or the models in use are already the best value).")
        return 0
    if args.action == "auto":
        print(tuning.auto(cv))
        return 0
    if not args.id:
        print(f"`crossvet tune {args.action}` needs a route number (`crossvet tune` lists them)", file=sys.stderr)
        return 2
    status = {"accept": "accepted", "reject": "rejected", "rollback": "rolled_back"}[args.action]
    row = cv.lab.set_route_status(args.id, status)
    print(f"route #{row['id']} ({row['kind']} -> {row['model']}) is now {status.replace('_', ' ')}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-ask past questions on another model; a blind judge compares."""
    from crossvet import multi

    result = multi.replay(_cv(), args.model, args.judge or "", limit=args.n)
    print(f"{result['candidate']}: {result['candidate_wins']} wins, {result['ties']} ties, {result['logged_wins']} losses "
          f"on {result['judged']} judged of {result['questions']} past questions (${result['cost']:.4f})")
    for row in result["rows"]:
        print(f"  #{row['turn']}: {row.get('verdict', 'error')} {row.get('why') or row.get('error', '')}")
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    """Hand a task to Claude Code or Codex, or show a handoff."""
    from crossvet import handoff

    cv = _cv()
    if args.agent in ("status", "result"):
        print(handoff.describe(cv.lab, int(args.task[0]) if args.task else 0, with_result=args.agent == "result"))
        return 0
    handoff_id = handoff.submit(cv.lab, args.agent, " ".join(args.task), args.cwd, wait=True)
    print(handoff.describe(cv.lab, handoff_id, with_result=True))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Print the report in Markdown (or the weekly numbers, as Markdown or JSON)."""
    from crossvet import care

    if args.week:
        print(json.dumps(care.weekly(_cv()), indent=2) if args.json else care.weekly_text(_cv()), end="" if not args.json else "\n")
        return 0
    print(care.report(_cv(), args.days), end="")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Write the dashboard page."""
    from crossvet import care

    out = Path(args.out)
    out.write_text(care.dashboard(_cv(), args.days))
    print(f"wrote {out}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export every answer as JSON lines."""
    from crossvet import care

    text = care.export(_cv(), Path(args.out) if args.out else None)
    print(text, end="" if text.endswith("\n") or not text else "\n")
    return 0


def cmd_sync(_: argparse.Namespace) -> int:
    """Copy new turns and ratings to Langfuse."""
    from crossvet import langfuse

    print(langfuse.sync(_cv()))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """Back up the log and the lab file."""
    from crossvet import care

    print(care.backup(_cv(), Path(args.folder).expanduser()))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore the log and the lab file from a backup."""
    from crossvet import care

    print(care.restore(_cv(), Path(args.folder).expanduser(), force=args.force))
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """Drop old side data; turns are never removed."""
    from crossvet import care

    print(care.prune(_cv(), args.days))
    return 0


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

    p = sub.add_parser("route", help="which model auto would choose, and why (calls nothing)")
    p.add_argument("-m", "--model", default="auto", help="auto, crossvet/<slot> or crossvet/<goal>")
    p.add_argument("text", nargs="*")
    p.set_defaults(func=cmd_route)
    sub.add_parser("why", help="the latest decision auto made").set_defaults(func=cmd_why)
    p = sub.add_parser("rate", help="rate an answer good or bad")
    p.add_argument("rating", choices=("good", "bad"))
    p.add_argument("note", nargs="*")
    p.add_argument("--turn", type=int, default=0, help="the turn number (default: the latest answer)")
    p.set_defaults(func=cmd_rate)
    p = sub.add_parser("compare", help="the same question to several models")
    p.add_argument("-m", "--model", action="append", required=True, help="repeat for each model (2 to 6)")
    p.add_argument("text", nargs="*")
    p.set_defaults(func=cmd_compare)
    p = sub.add_parser("challenge", help="another vendor's model tries to break an answer")
    p.add_argument("--turn", type=int, default=0, help="the answer's turn number (default: the latest)")
    p.add_argument("-m", "--model", default="", help="the challenger (default: the strongest model from another vendor)")
    p.set_defaults(func=cmd_challenge)
    p = sub.add_parser("note", help="save a note every app can find")
    p.add_argument("text", nargs="+")
    p.add_argument("--tags", default="")
    p.set_defaults(func=cmd_note)
    p = sub.add_parser("notes", help="search the notes")
    p.add_argument("query", nargs="*")
    p.add_argument("-n", type=int, default=10)
    p.set_defaults(func=cmd_notes)
    p = sub.add_parser("bench", help="the Sarasota used-car benchmark, scored in code")
    p.add_argument("-m", "--model", action="append", help="repeat for each model (default: the model list)")
    p.add_argument("--suite", choices=("standard", "hard", "all"), default="standard")
    p.add_argument("--limit", type=int, default=0, help="only the first N cases")
    p.add_argument("--run-code", action="store_true", help="run code answers in a separate process to check them")
    p.add_argument("--out", default="", help="results folder (default docs/benchmarks/<date>)")
    p.add_argument("--review", action="store_true", help="the review benchmark instead: planted bugs, -m picks the reviewers")
    p.add_argument("--set", choices=("planted", "hard", "all"), default="",
                   help="with --review: planted (12 easy bugs), hard (subtler bugs plus clean changes), or all")
    p.set_defaults(func=cmd_bench)
    p = sub.add_parser("service", help="run the server at login (launchd on macOS, systemd on Linux)")
    p.add_argument("action", nargs="?", default="status", choices=("install", "status", "uninstall"))
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--weekly", action="store_true", help="also a Monday job: score run, tune auto, report --week --json")
    p.add_argument("--no-load", action="store_true", help="write the files without starting anything")
    p.set_defaults(func=cmd_service)
    p = sub.add_parser("score", help="judge a sample of answers (opt-in: [score] enabled), shadow answers, calibration")
    p.add_argument("action", nargs="?", default="run", choices=("run", "shadow", "calibrate"))
    p.add_argument("--limit", type=int, default=20, help="judge at most this many answers")
    p.add_argument("--all", action="store_true", help="judge every candidate, not a sample")
    p.set_defaults(func=cmd_score)
    p = sub.add_parser("leaderboard", help="score and cost per model for each kind of task, from judged answers")
    p.add_argument("--days", type=float, default=30, help="0 = all time")
    p.set_defaults(func=cmd_leaderboard)
    p = sub.add_parser("review", help="another vendor reviews a change; findings checked in code")
    p.add_argument("--task", required=True, help="what the change is meant to do")
    p.add_argument("--staged", action="store_true", help="review the staged change")
    p.add_argument("--base", default="", help="review this branch against BASE (default: a diff on standard input)")
    p.add_argument("--author", default="", help="the model that wrote the change (default: default_model)")
    p.add_argument("--reviewer", default="", help="default: the reviewer slot, from another vendor than the author")
    p.add_argument("--fix", action="store_true", help="the author model writes a patch for the kept findings")
    p.add_argument("--apply", action="store_true", help="with --fix: apply the patch and review again")
    p.add_argument("--rounds", type=int, default=1, help="with --fix --apply: at most this many rounds (max 3)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-record", action="store_true", help="don't write .crossvet/reviews/")
    p.set_defaults(func=cmd_review)
    p = sub.add_parser("tune", help="routes from your ratings: show, accept, reject, rollback")
    p.add_argument("action", nargs="?", default="show", choices=("show", "accept", "reject", "rollback", "scores", "auto"))
    p.add_argument("id", nargs="?", type=int, default=0)
    p.set_defaults(func=cmd_tune)
    p = sub.add_parser("replay", help="past questions on another model, judged blind")
    p.add_argument("-m", "--model", required=True)
    p.add_argument("--judge", default="", help="default: the strongest model from another vendor")
    p.add_argument("-n", type=int, default=10)
    p.set_defaults(func=cmd_replay)
    p = sub.add_parser("handoff", help="a task to Claude Code or Codex (or: handoff status ID, handoff result ID)")
    p.add_argument("agent", choices=("claude-code", "codex", "status", "result"))
    p.add_argument("task", nargs="*")
    p.add_argument("--cwd", default=".")
    p.set_defaults(func=cmd_handoff)
    for name, func, text in (("report", cmd_report, "your numbers in Markdown"), ("dashboard", cmd_dashboard, "your numbers as an HTML page")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--days", type=float, default=7, help="0 = all time")
        if name == "dashboard":
            p.add_argument("--out", default="crossvet-dashboard.html")
        else:
            p.add_argument("--week", action="store_true", help="the last 7 days: spend, saving against the strongest model, scores, route changes")
            p.add_argument("--json", action="store_true", help="with --week: as JSON (for n8n, Windmill or cron)")
        p.set_defaults(func=func)
    p = sub.add_parser("export", help="every answer as JSON lines")
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_export)
    sub.add_parser("sync", help="copy new turns and ratings to Langfuse").set_defaults(func=cmd_sync)
    p = sub.add_parser("backup", help="copies of the log and the lab file, with SHA-256 sums")
    p.add_argument("folder")
    p.set_defaults(func=cmd_backup)
    p = sub.add_parser("restore", help="put a backup back (checks the sums first)")
    p.add_argument("folder")
    p.add_argument("--force", action="store_true", help="replace a log that has turns")
    p.set_defaults(func=cmd_restore)
    p = sub.add_parser("prune", help="drop old kept reasoning and finished handoffs (never turns)")
    p.add_argument("--days", type=float, default=30)
    p.set_defaults(func=cmd_prune)
    return parser


def normalize(argv: list[str]) -> list[str] | str:
    """Map 1.x spellings (``crossvet chat route``) to today's commands."""
    if argv[:1] != ["chat"] or len(argv) < 2:
        return argv
    second = argv[1]
    if second in ("--version", "-V"):
        return ["--version"]
    if second in RENAMED:
        return f"`crossvet chat {second}` is now `crossvet {RENAMED[second]}` (see docs/MIGRATING.md)."
    sub = next(a for a in build_parser()._actions if a.dest == "command")
    if second in sub.choices and second != "chat":
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
