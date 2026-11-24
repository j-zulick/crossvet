"""``crossvet chat``: one chat that routes each request to a suitable model.

    crossvet chat                          talk in one thread; /help lists the commands
    crossvet chat init [--openrouter]      write crossvet-chat.toml from the keys you have
    crossvet chat doctor                   check keys, slots and limits without calling a model
    crossvet chat route "request"          which model would answer and why (free)
    crossvet chat ask "request"            answer once with the model the router picks
    crossvet chat compare "request" -m A -m B    several models side by side
    crossvet chat challenge [--thread ID]  a model from another vendor tries to break the last answer
    crossvet chat note add KEY "text"      save a fact every app and model can read
    crossvet chat note list | search WORDS
    crossvet chat log [--thread ID]        what was asked, who answered, why, and what it cost
    crossvet chat feedback good|bad        rate the latest answer (or --turn ID); kept locally and in Langfuse
    crossvet chat bench -m A -m B [--apply]    measure models per kind of task; --apply fills the slots
    crossvet chat routes show | history    the routing table you tune: slot, vendors, models per kind of task
    crossvet chat routes set KIND [--slot S] [--prefer V,V] [--models M,M] [--avoid M] --why TEXT
    crossvet chat routes reset [KIND] | rollback VERSION
    crossvet chat routes import FILE_OR_URL...   claims like "model X is good at task Y" from posts or notes
    crossvet chat routes evidence | accept ID | reject ID
    crossvet chat tune [--days N] [--apply KIND]    how each model did per kind of task, from your ratings
    crossvet chat replay [--router R ...] [--table V ...] [--run]   how other routers or tables would have routed your history
    crossvet chat export --dataset NAME | --jsonl FILE              your answers and ratings as a Langfuse dataset or JSON lines
    crossvet chat handoff pilot DIR | new PACKET | send TASK --worker W | import RESULT | show TASK | list
                                           versioned packets passed between models, apps and agents, checked in code
    crossvet chat serve                    OpenAI-compatible server (any chat app, model "auto")
    crossvet chat mcp                      MCP server for Claude Code, Codex, Cursor or Hermes

Each command takes --help.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from open_deep_research.chat import __version__, providers
from open_deep_research.chat.config import SLOT_HELP, SLOTS, config_path, load
from open_deep_research.chat.router import ROUTERS
from open_deep_research.chat.routing import EFFORTS


def load_env(path: str = ".env") -> list[str]:
    """Read ``KEY=value`` lines from ``.env`` into the environment; return the names set (never the values)."""
    names: list[str] = []
    file = Path(path)
    if not file.is_file():
        return names
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            names.append(key)
    return names


def _hub():
    from open_deep_research.chat.hub import Hub

    return Hub()


def _read_prompt(words: list[str]) -> str:
    text = " ".join(words).strip()
    if text == "-" or (not text and not sys.stdin.isatty()):
        text = sys.stdin.read().strip()
    if not text:
        raise SystemExit("give a request, or pipe one in")
    return text


def cmd_init(args: argparse.Namespace) -> int:
    """Run `crossvet chat init`."""
    from open_deep_research.chat.setup import build

    target = Path(args.out)
    if target.exists() and not args.force:
        print(f"{target} already exists; use --force to replace it", file=sys.stderr)
        return 2
    try:
        text, notes = build(args.openrouter)
    except Exception as exc:  # noqa: BLE001  network or parsing: say what happened
        print(f"could not build the config: {exc}", file=sys.stderr)
        return 1
    target.write_text(text)
    print(f"wrote {target}")
    for note in notes:
        print(f"note: {note}")
    print("next: crossvet chat doctor")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    """Run `crossvet chat doctor`."""
    cfg = load()
    problems = 0
    print(f"config: {cfg.source or 'none found (run `crossvet chat init`)'}")
    print("keys:   " + ", ".join(
        f"{p} {'no key needed' if not providers.key_name(p) else 'yes' if providers.available(p) else 'no'}"
        for p in providers.PROVIDERS))
    missing: dict[str, int] = {}
    for name in SLOTS:
        models = cfg.slots.get(name, [])
        marks = []
        for model in models:
            try:
                provider, _ = providers.split(model)
            except providers.ProviderError as exc:
                marks.append(f"{model} (bad name: {exc})")
                problems += 1
                continue
            if providers.available(provider):
                marks.append(model)
            else:
                marks.append(f"{model} (no key)")
                missing[provider] = missing.get(provider, 0) + 1
        print(f"{name:9} {', '.join(marks) if marks else '(empty)'}")
    for provider, count in missing.items():
        print(f"problem: {providers.key_name(provider)} is not set ({count} model(s) need it): "
              "add it to .env in this folder, or run `crossvet setup`")
    problems += len(missing)
    if not any(cfg.slots.get(s) for s in ("quick", "balanced", "strong")):
        print("problem: no model in quick, balanced or strong")
        problems += 1
    unpriced = [m for m in cfg.all_models() if cfg.info(m).input is None]
    if unpriced and (cfg.max_usd_per_call or cfg.max_usd_per_day):
        print(f"note: no price for {', '.join(unpriced)}; spend caps only count calls whose cost is known")
    vendors = {providers.vendor_of(m) for m in cfg.all_models()}
    if len(vendors) < 2:
        print("note: all models are from one vendor; `crossvet chat challenge` needs a second vendor")
    print(f"limits: ${cfg.max_usd_per_day:g} a day, ${cfg.max_usd_per_call:g} a call (0 = no cap)")
    print("ok" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


def cmd_route(args: argparse.Namespace) -> int:
    """Run `crossvet chat route`."""
    from open_deep_research.chat.hub import Hub
    from open_deep_research.chat.memory import Memory
    from open_deep_research.chat.record import Recorder

    scratch = Hub(config=load(), memory=Memory(":memory:"), recorder=Recorder())  # deciding needs no store
    decision = scratch.decide(_read_prompt(args.prompt), slot=args.slot, effort=args.effort, router=args.router)
    if args.json:
        print(json.dumps({"kind": decision.task.kind, "difficulty": decision.task.difficulty, "slot": decision.slot,
                          "router": decision.router, "candidates": decision.candidates, "reasons": decision.reasons,
                          "cost": decision.overhead_cost}, indent=2))
    else:
        print(decision.explain())
        if len(decision.candidates) > 1:
            print("if that fails a check, next: " + ", ".join(decision.candidates[1:]))
    return 0 if decision.candidates else 1


def cmd_ask(args: argparse.Namespace) -> int:
    """Run `crossvet chat ask`."""
    hub = _hub()
    answer = hub.ask(_read_prompt(args.prompt), thread=args.thread, model=args.model, slot=args.slot, effort=args.effort,
                     use_memory=not args.no_memory, router=args.router)
    print(answer.text)
    print(f"\n{answer.summary()} thread {answer.thread}", file=sys.stderr)
    return 0


CHAT_HELP = """/model NAME     answer with this model from now on (/model auto goes back to the router)
/slot NAME      use this slot from now on (/slot auto goes back to the router)
/router NAME    rules, jev, openrouter-auto, openrouter-auto-code or jev-router from now on
/why            why the last answer went to that model
/retry [stronger]   ask the last question again (one slot up with "stronger")
/good [comment] rate the last answer good (/bad [comment] for bad); kept locally and sent to Langfuse
/challenge      a model from another vendor tries to break the last answer
/note KEY TEXT  save a fact to shared memory
/cost           what this session and today have cost
/new            start a new thread
/quit"""


def cmd_chat(args: argparse.Namespace) -> int:
    """Talk in one thread (`crossvet chat` with no subcommand)."""
    from open_deep_research.chat.council import challenge
    from open_deep_research.chat.memory import new_thread

    hub = _hub()
    thread, model, slot, last, last_prompt = args.thread or new_thread(), None, None, None, ""
    router: str | None = None
    session_cost = 0.0
    print(f"thread {thread}. /help for commands.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return 0
        if line == "/help":
            print(CHAT_HELP)
        elif line.startswith("/model"):
            model = None if line.split()[-1] in ("auto", "/model") else line.split()[-1]
            print(f"model: {model or 'auto'}")
        elif line.startswith("/slot"):
            slot = None if line.split()[-1] in ("auto", "/slot") else line.split()[-1]
            print(f"slot: {slot or 'auto'}")
        elif line.startswith("/router"):
            name = line.split()[-1]
            if name not in ROUTERS:
                print("routers: " + ", ".join(ROUTERS))
                continue
            router = name
            print(f"router: {router}")
        elif line == "/why":
            print(last.decision.explain() if last else "nothing asked yet")
        elif line.startswith("/retry"):
            if not last:
                print("nothing to retry yet")
                continue
            try:
                last = hub.retry(thread, stronger=line.endswith("stronger"))
                session_cost += last.cost or 0
                print(f"{last.text}\n{last.summary()}")
            except (providers.ProviderError, RuntimeError, ValueError) as exc:
                print(f"error: {exc}")
        elif line.split()[0] in ("/good", "/bad"):
            if not last:
                print("nothing to rate yet")
                continue
            hub.feedback(line.startswith("/good"), turn_id=last.turn_id, comment=line.partition(" ")[2], source="cli")
            print("rated")
        elif line == "/cost":
            print(f"this session: ${session_cost:.4f}   today: ${hub.memory.spent_today():.4f}")
        elif line == "/new":
            thread, last = new_thread(), None
            print(f"thread {thread}")
        elif line.startswith("/note "):
            _, key, *rest = line.split(" ", 2)
            hub.memory.add_note(key, rest[0] if rest else "", author="cli")
            print("saved")
        elif line == "/challenge":
            if not last:
                print("nothing to challenge yet")
                continue
            try:
                print(challenge(hub, last_prompt, last.text, author_model=last.model, revise=True, thread=thread).report())
            except (providers.ProviderError, RuntimeError) as exc:
                print(f"challenge failed: {exc}")
        else:
            try:
                last = hub.ask(line, thread=thread, model=model, slot=slot, router=router)
                last_prompt = line
                session_cost += last.cost or 0
                print(f"{last.text}\n{last.summary()}")
            except (providers.ProviderError, RuntimeError, ValueError) as exc:
                print(f"error: {exc}")


def cmd_compare(args: argparse.Namespace) -> int:
    """Run `crossvet chat compare`."""
    from open_deep_research.chat.council import compare

    hub = _hub()
    models = args.model or hub.config.slot("strong")[:1] + hub.config.slot("reviewer")[:1]
    for result in compare(hub, _read_prompt(args.prompt), list(dict.fromkeys(models))):
        cost = "" if result["cost"] is None else f" · ${result['cost']:.4f}"
        print(f"=== {result['model']}{cost} · {result['seconds']}s ===")
        print(result["text"] if result["ok"] else f"failed: {result['error']}")
        print()
    return 0


def cmd_challenge(args: argparse.Namespace) -> int:
    """Run `crossvet chat challenge`."""
    from open_deep_research.chat.council import challenge

    hub = _hub()
    if args.file:
        work, request, author_model, thread = Path(args.file).read_text(), args.request or "", args.author_model or "", args.thread
    else:
        turns = hub.memory.turns(args.thread, 50) if args.thread else []
        if not turns:
            recent = [t for t in hub.memory.recent(50) if t.role == "assistant"]
            turns = hub.memory.turns(recent[0].thread, 50) if recent else []
        answers = [t for t in turns if t.role == "assistant"]
        if not answers:
            print("no saved answer to challenge; pass --file or ask something first", file=sys.stderr)
            return 2
        last = answers[-1]
        questions = [t for t in turns if t.role == "user" and t.id < last.id]
        work, author_model, thread = last.content, last.model, last.thread
        request = questions[-1].content if questions else ""
    result = challenge(hub, request, work, author_model=author_model, reviewer=args.reviewer, revise=args.revise, thread=thread)
    print(result.report())
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """Run `crossvet chat feedback`."""
    hub = _hub()
    hub.feedback(args.rating == "good", thread=args.thread, turn_id=args.turn, comment=args.comment, source="cli")
    print("rated")
    hub.recorder.flush()
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    """Run `crossvet chat note`."""
    hub = _hub()
    if args.action == "add":
        if len(args.words) < 2:
            print('usage: crossvet chat note add KEY "text"', file=sys.stderr)
            return 2
        hub.memory.add_note(args.words[0], " ".join(args.words[1:]), author=args.author, tags=args.tags)
        print("saved")
    elif args.action == "list":
        for note in hub.memory.notes():
            print(f"[{note.key}] {note.content}  ({note.author}, {time.strftime('%Y-%m-%d', time.localtime(note.ts))})")
    else:
        found = hub.memory.search(" ".join(args.words))
        for note in found["notes"]:
            print(f"note [{note.key}] {note.content}")
        for turn in found["turns"]:
            print(f"turn {turn.thread} {turn.role} ({turn.model or turn.author}): {turn.content[:160]}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    """Run `crossvet chat log`."""
    hub = _hub()
    if not args.thread:
        for t in hub.memory.threads(args.limit):
            print(f"{t['thread']}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(t['last']))}  {t['turns']:3} turns  {t['first']}")
        print(f"spent today: ${hub.memory.spent_today():.4f}")
        return 0
    for turn in hub.memory.turns(args.thread, args.limit):
        who = turn.model or turn.author
        cost = "" if turn.cost is None else f" ${turn.cost:.4f}"
        rated = "".join(f" · {r.name}={r.value:g}" for r in hub.memory.ratings(turn.id)) if turn.role == "assistant" else ""
        print(f"--- {turn.role} #{turn.id} · {who}{cost} · {time.strftime('%H:%M', time.localtime(turn.ts))}{rated}")
        print(turn.content)
        if args.why and turn.meta.get("why"):
            print(f"    why: {turn.meta['why']}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Run `crossvet chat bench`."""
    from open_deep_research.chat import bench

    hub = _hub()
    models = args.model or hub.config.all_models()
    if not models:
        print("name models with -m, or fill the slots first", file=sys.stderr)
        return 2
    calls = len(models) * len(bench.CASES)
    if args.dry_run:
        print(f"{calls} calls: {len(models)} model(s) × {len(bench.CASES)} cases. Nothing was sent.")
        return 0
    rows = bench.run(hub, models, run_code=args.run_code,
                     on_result=lambda r: print(f"{r['model']} {r['case']}: {r['score']:.2f} {r['error']}", file=sys.stderr))
    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(bench.table(rows))
    slots = bench.best_value(rows)
    print("\nbest value per slot (cheapest within 10% of the best score):")
    for slot, ranked in slots.items():
        print(f"  {slot}: {', '.join(ranked) or '(none scored)'}")
    if args.apply:
        _apply_slots(slots)
    return 0


def _apply_slots(slots: dict[str, list[str]]) -> None:
    """Rewrite the ``quick``, ``balanced`` and ``strong`` lines of the config in place."""
    import re

    path = config_path()
    if not path:
        print("no crossvet-chat.toml to update; run `crossvet chat init` first", file=sys.stderr)
        return
    text = path.read_text()
    for slot, ranked in slots.items():
        if ranked:
            line = f"{slot} = [" + ", ".join(f'"{m}"' for m in ranked) + "]"
            text, n = re.subn(rf"(?m)^{slot}\s*=\s*\[.*\]\s*$", line, text, count=1)
            if not n:
                text = text.replace("[slots]\n", f"[slots]\n{line}\n", 1)
    path.write_text(text)
    print(f"updated {path} from the benchmark ({time.strftime('%Y-%m-%d')})")


def _print_table(table, config) -> None:
    from open_deep_research.chat.classify import KINDS

    label = "starting table (judgment, not measured)" if table.version == 0 else (
        f"version {table.version}, {time.strftime('%Y-%m-%d %H:%M', time.localtime(table.ts))} by {table.author}: {table.reason}")
    print(f"routing table: {label}")
    for kind in KINDS:
        entry = table.entries.get(kind)
        slot = (entry.slot if entry and entry.slot else config.routes.get(kind, "balanced"))
        parts = [f"slot {slot}"]
        if entry and entry.prefer:
            parts.append("vendors " + ", ".join(entry.prefer))
        if entry and entry.models:
            parts.append("first " + ", ".join(entry.models))
        if entry and entry.avoid:
            parts.append("avoid " + ", ".join(entry.avoid))
        print(f"  {kind:10} {'; '.join(parts)}")
        if entry and entry.why:
            print(f"  {'':10} why: {entry.why} ({entry.since}, {entry.by})")


def _csv(value: str | None) -> list[str] | None:
    return None if value is None else [v.strip() for v in value.split(",") if v.strip()]


def _read_manual(path: str) -> list[dict[str, str]]:
    import csv

    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".csv"):
        return [dict(row) for row in csv.DictReader(text.splitlines())]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def cmd_routes(args: argparse.Namespace) -> int:
    """Run `crossvet chat routes`."""
    from open_deep_research.chat import tuning as tune_mod
    from open_deep_research.scan_cli import fetch

    hub = _hub()
    tuning = hub.tuning
    words = args.words
    if args.action == "show":
        table = tuning.current()
        if args.json:
            print(json.dumps({"version": table.version, "entries": table.body()}, indent=2))
        else:
            _print_table(table, hub.config)
    elif args.action == "history":
        print("v0  starting table (judgment, not measured)")
        for table in tuning.history():
            print(f"v{table.version}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(table.ts))}  {table.author}: {table.reason}")
    elif args.action == "set":
        if not words or not args.why:
            print("usage: crossvet chat routes set KIND [--slot S] [--prefer V,V] [--models M,M] [--avoid M,M] --why TEXT",
                  file=sys.stderr)
            return 2
        table = tuning.change(words[0], "you", args.why, slot=args.slot, prefer=_csv(args.prefer), models=_csv(args.models),
                              avoid=_csv(args.avoid))
        print(f"saved version {table.version}")
    elif args.action == "reset":
        print(f"saved version {tuning.reset(words[0] if words else None).version}")
    elif args.action == "rollback":
        if not words:
            print("usage: crossvet chat routes rollback VERSION", file=sys.stderr)
            return 2
        print(f"saved version {tuning.rollback(int(words[0])).version}")
    elif args.action == "import":
        if args.manual:
            result = tune_mod.import_manual(tuning, args.manual, _read_manual(args.manual))
            print(f"{result.source}: {len(result.kept)} kept" + "".join(f"\n  dropped: {d}" for d in result.dropped))
        for source in words:
            try:
                raw = fetch(source, allow_private=False, max_bytes=2_000_000) if re.match(r"https?://", source) \
                    else Path(source).read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001  one bad source should not stop the rest
                print(f"{source}: could not read ({type(exc).__name__}: {exc})")
                continue
            result = tune_mod.import_post(hub, source, raw, again=args.again)
            print(f"{source}: {result.outcome}" + (f", {len(result.kept)} claim(s) kept" if result.outcome == "imported" else "")
                  + (f" ({result.detail})" if result.detail else ""))
            for reason in result.dropped:
                print(f"  dropped: {reason}")
        print("next: crossvet chat routes evidence")
    elif args.action == "evidence":
        items = tuning.evidence(status=None if args.all else "pending", kind=args.kind)
        if not items:
            print("no pending evidence" if not args.all else "no evidence")
        for item in items:
            matches = tune_mod.match_models(item, hub.config.all_models())
            print(f"#{item.id} [{item.status}] {item.kind}: {item.model} is {item.verdict.upper()}"
                  f"{' (vendor ' + item.vendor + ')' if item.vendor else ''}  source: {item.source}")
            print(f'    "{item.quote}"')
            if item.status == "pending":
                if item.verdict == "bad":
                    effect = f"adds {item.model_id or item.model} to the avoid list"
                elif matches:
                    effect = "puts " + ", ".join(matches) + " first"
                else:
                    effect = f"puts vendor {item.vendor} first" if item.vendor else "needs --model provider:model"
                print(f"    accept: {effect}")
    elif args.action in ("accept", "reject"):
        if not words:
            print(f"usage: crossvet chat routes {args.action} ID [ID ...]", file=sys.stderr)
            return 2
        for word in words:
            item_id = int(word.lstrip("#"))
            item = next((e for e in tuning.evidence() if e.id == item_id), None)
            if item is None:
                print(f"#{item_id}: no such evidence")
                continue
            models = _csv(args.model) or tune_mod.match_models(item, hub.config.all_models())
            table = tuning.decide(item_id, args.action == "accept", models=models)
            print(f"#{item_id}: {args.action}ed" + (f", saved version {table.version}" if table else ""))
    return 0


def cmd_tune(args: argparse.Namespace) -> int:
    """Run `crossvet chat tune`."""
    from open_deep_research.chat.tuning import proposals, stats

    hub = _hub()
    since = time.time() - args.days * 86400 if args.days else 0.0
    table_stats = stats(hub, since)
    found = proposals(hub, table_stats, hub.config.min_ratings)
    if args.json:
        print(json.dumps({"stats": [{**s.__dict__, "good_rate": s.good_rate, "trouble_rate": s.trouble_rate,
                                     "mean_cost": s.mean_cost} for s in table_stats.values()],
                          "proposals": [p.__dict__ for p in found]}, indent=2))
        return 0
    if not table_stats:
        print("no answers recorded yet")
        return 0
    print(f"{'kind':10} {'model':45} {'answers':>7} {'rated':>5} {'good':>6} {'trouble':>7} {'escal.':>6} {'$/answer':>9}")
    for (kind, model), s in sorted(table_stats.items()):
        good = "-" if s.good_rate is None else f"{s.good_rate:.0%}"
        cost = "-" if s.mean_cost is None else f"{s.mean_cost:.4f}"
        print(f"{kind:10} {model[:45]:45} {s.answers:>7} {s.rated:>5} {good:>6} {s.trouble_rate:>7.0%} {s.escalated:>6} {cost:>9}")
    print("\ntrouble = retried, switched away from, or rated bad, as a share of answers")
    if not found:
        print("no proposals: rate answers with /good and /bad to get some")
    for p in found:
        print(f"\nproposal for {p.kind}: put {p.model} first{' (weak: few ratings)' if p.weak else ''}\n  {p.evidence}")
        print(f"  apply: crossvet chat tune --apply {p.kind}")
    if args.apply:
        chosen_one = next((p for p in found if p.kind == args.apply), None)
        if chosen_one is None:
            print(f"no proposal for {args.apply}", file=sys.stderr)
            return 2
        entry = hub.tuning.current().entries.get(chosen_one.kind)
        models = list(dict.fromkeys([chosen_one.model] + (entry.models if entry else [])))
        table = hub.tuning.change(chosen_one.kind, "you (tune)", f"from your ratings: {chosen_one.evidence}", models=models)
        print(f"saved version {table.version}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Run `crossvet chat replay`."""
    from open_deep_research.chat import replay

    hub = _hub()
    since = time.time() - args.days * 86400 if args.days else 0.0
    past = replay.history(hub, since=since, limit=args.limit)
    if not past:
        print("no saved answers to replay yet")
        return 0
    routers = args.router or ["rules"]
    jev_calls = len(past) * routers.count("jev")
    if jev_calls and not args.yes:
        print(f"the jev router makes one small Jev call per question: {jev_calls} calls. Add --yes to go ahead.", file=sys.stderr)
        return 2
    rated = sum(p.good is not None for p in past)
    print(f"{len(past)} answers ({rated} rated, {sum(p.trouble for p in past)} with trouble). No answering model is called.")
    results = replay.compare_routers(hub, past, routers, args.table)
    for result in results:
        print(result.line() + (f"  deciding cost ${result.decide_cost:.4f}" if result.decide_cost else ""))
        for change, count in sorted(result.changes.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    {count:4}  {change}")
    print("hosted routers pick at answer time, so they never match a past model here; use --run to judge their answers")
    if args.run:
        duels = replay.run_duels(hub, past, routers, sample=args.sample, max_usd=args.max_usd)
        if args.out:
            Path(args.out).write_text("".join(json.dumps(d.__dict__) + "\n" for d in duels))
        print(f"\njudged re-answers (sample of {args.sample}, cap ${args.max_usd:g}, spent ${sum(d.cost for d in duels):.4f}):")
        for router, counts in replay.tally(duels).items():
            print(f"  {router:22} new answer better {counts['challenger']}, original better {counts['original']}, "
                  f"tie {counts['tie']}, same model {counts['same']}, errors {counts['error']}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Run `crossvet chat export`."""
    from open_deep_research.chat import replay

    hub = _hub()
    if not (args.dataset or args.jsonl):
        print("give --dataset NAME (Langfuse) or --jsonl FILE", file=sys.stderr)
        return 2
    since = time.time() - args.days * 86400 if args.days else 0.0
    data = replay.rows(hub, only=args.only, since=since, content=hub.config.record_content if not args.full else "full")
    if args.jsonl:
        replay.export_jsonl(data, args.jsonl)
        print(f"wrote {len(data)} rows to {args.jsonl}")
    if args.dataset:
        print(f"sent {replay.export_langfuse(data, args.dataset)} items to the Langfuse dataset {args.dataset}")
    return 0


def _show_job(job) -> None:
    print(f"{job.task_id} revision {job.revision}: {job.state} (attempts {job.attempts}/{job.request['attempt_limit']}, "
          f"digest {job.digest[:12]})")
    for event in job.events:
        detail = event["detail"]
        extra = ""
        if detail.get("result"):
            extra = f" verdict={detail['result'].get('verdict')} quote={detail['result'].get('quote', '')[:60]!r}"
        if detail.get("problems"):
            extra += " problems: " + "; ".join(detail["problems"])
        who = detail.get("model") or detail.get("worker") or ""
        print(f"  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(event['ts']))} {event['state']:11} {event['attempt_id'] or '-':12} "
              f"{who}{extra}")


def cmd_handoff(args: argparse.Namespace) -> int:
    """Run `crossvet chat handoff`."""
    from open_deep_research.chat import handoff as ho

    hub = _hub()
    queue = hub.handoffs
    words = args.words
    if args.action == "pilot":
        folder = words[0] if words else "handoff-pilot"
        raw = (json.dumps(ho.PILOT_PACKET) + "\n").encode()
        job, _ = queue.submit(ho.PILOT_PACKET, raw)
        kit = ho.write_kit(job, folder)
        print(f"queued {job.task_id} r{job.revision}; kit in {kit['folder']} (packet digest {kit['digest'][:12]})")
        print("expected: verdict contradicted, quote \"The fixture lists one indexable page.\"")
        print(f"next: sh {kit['folder']}/run-claude.sh, then crossvet chat handoff import {kit['folder']}/claude-result.json")
        return 0
    if args.action == "new":
        if not words:
            print("usage: crossvet chat handoff new PACKET.json [--kit DIR]", file=sys.stderr)
            return 2
        raw = Path(words[0]).read_bytes()
        job, new = queue.submit(json.loads(raw), raw)
        print(("queued " if new else "already queued (same task, revision and digest): ") + f"{job.task_id} r{job.revision}")
        if args.kit:
            print(f"kit in {ho.write_kit(job, args.kit)['folder']}")
        return 0
    if args.action in ("send", "show", "resolve", "cancel", "kit"):
        if not words:
            print(f"usage: crossvet chat handoff {args.action} TASK_ID [--revision N]", file=sys.stderr)
            return 2
        job = queue.find(words[0], args.revision)
        if args.action == "show":
            _show_job(job)
            return 0
        if args.action == "kit":
            print(f"kit in {ho.write_kit(job, args.kit or f'handoff-{job.task_id}-r{job.revision}')['folder']}")
            return 0
        if args.action == "resolve":
            queue.resolve(job.id, args.note or "checked by hand: the earlier attempt did not finish")
            print("reconciled; a new attempt may start")
            return 0
        if args.action == "cancel":
            queue.cancel(job.id, args.note)
            print("cancelled")
            return 0
        if args.worker == "model":
            outcome = ho.run_model(hub, queue, job, args.model)
        elif args.worker == "file":
            print(f"kit in {ho.write_kit(job, args.kit or f'handoff-{job.task_id}-r{job.revision}')['folder']}: give packet.json to any "
                  "chat or agent, then import its reply")
            return 0
        else:
            outcome = ho.run_cli(queue, job, args.worker, args.kit or f"handoff-{job.task_id}-r{job.revision}")
        print(f"{outcome.state}" + (f": {'; '.join(outcome.problems)}" if outcome.problems else "")
              + (f" · verdict {outcome.result.get('verdict')}" if outcome.result else ""))
        return 0 if outcome.state == "succeeded" else 1
    if args.action == "import":
        if not words:
            print("usage: crossvet chat handoff import RESULT.json [--task ID] [--revision N] [--exit CODE]", file=sys.stderr)
            return 2
        outcome = ho.import_result(queue, words[0], args.task, args.revision, args.worker if args.worker != "model" else "file",
                                   args.exit)
        print(f"{outcome.state}" + (f": {'; '.join(outcome.problems)}" if outcome.problems else "")
              + (f" · verdict {outcome.result.get('verdict')}" if outcome.result else ""))
        return 0 if outcome.state == "succeeded" else 1
    if args.action == "reconcile":
        changed = queue.reconcile(stale_after=args.stale_after)
        print("\n".join(changed) or "nothing to reconcile")
        return 0
    for job in queue.jobs(args.limit):
        print(f"{job.task_id:28} r{job.revision:<3} {job.state:11} attempts {job.attempts}/{job.request['attempt_limit']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run `crossvet chat serve`."""
    from open_deep_research.chat.server import serve

    return serve(args.host, args.port)


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run `crossvet chat mcp`."""
    from open_deep_research.chat.mcp_server import main as mcp_main

    return mcp_main(http=args.http, host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for every `crossvet chat` command."""
    parser = argparse.ArgumentParser(prog="crossvet chat", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="write crossvet-chat.toml from the keys you have")
    p.add_argument("--openrouter", action="store_true", help="fill the slots from OpenRouter's public model list")
    p.add_argument("--out", default="crossvet-chat.toml")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    sub.add_parser("doctor", help="check keys, slots and limits without calling a model").set_defaults(func=cmd_doctor)

    def routing_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("prompt", nargs="*", help='the request; "-" or a pipe reads it from standard input')
        sp.add_argument("--slot", choices=SLOTS, help="skip the classifier and use this slot: " + "; ".join(
            f"{k} = {v}" for k, v in SLOT_HELP.items()))
        sp.add_argument("--effort", choices=EFFORTS, default="auto", help="low moves down one slot, high moves up one")
        sp.add_argument("--router", choices=ROUTERS, help="override [router] use: " + ", ".join(ROUTERS) + " (jev costs a small Jev call)")

    p = sub.add_parser("route", help="show which model would answer and why, without calling it")
    routing_args(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_route)

    p = sub.add_parser("ask", help="answer with the model the router picks")
    routing_args(p)
    p.add_argument("--model", "-m", help="use this model (provider:model) instead of the router")
    p.add_argument("--thread", help="continue this thread")
    p.add_argument("--no-memory", action="store_true", help="do not show the model the shared notes")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("chat", help="keep talking in one thread")
    p.add_argument("--thread")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("compare", help="several models answer the same request, side by side")
    p.add_argument("prompt", nargs="*")
    p.add_argument("--model", "-m", action="append", help="repeat for each model (default: your strong and reviewer models)")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("challenge", help="a model from another vendor tries to break an answer")
    p.add_argument("--thread", help="challenge the last answer in this thread (default: the most recent answer)")
    p.add_argument("--file", help="challenge the text in this file instead")
    p.add_argument("--request", help="with --file: what the text was meant to do")
    p.add_argument("--author-model", help="with --file: the model that wrote it, so the reviewer comes from another vendor")
    p.add_argument("--reviewer", help="use this model as the reviewer")
    p.add_argument("--revise", action="store_true", help="send the kept objections back to the author for a revised answer")
    p.set_defaults(func=cmd_challenge)

    p = sub.add_parser("feedback", help="rate an answer good or bad (default: the latest answer)")
    p.add_argument("rating", choices=("good", "bad"))
    p.add_argument("--turn", type=int, help="the answer's turn id (shown by `log`)")
    p.add_argument("--thread", help="rate the last answer in this thread")
    p.add_argument("--comment", default="")
    p.set_defaults(func=cmd_feedback)

    p = sub.add_parser("note", help="shared memory: facts every app and model can read")
    p.add_argument("action", choices=("add", "list", "search"))
    p.add_argument("words", nargs="*")
    p.add_argument("--author", default="user")
    p.add_argument("--tags", default="")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("log", help="threads, or one thread's turns with who answered and what it cost")
    p.add_argument("--thread")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--why", action="store_true", help="show why each answer went to its model")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("bench", help="measure models per kind of task (this calls the models and costs money)")
    p.add_argument("--model", "-m", action="append")
    p.add_argument("--dry-run", action="store_true", help="say how many calls it would make, and stop")
    p.add_argument("--run-code", action="store_true", help="also run the code answers in a separate process to check them")
    p.add_argument("--apply", action="store_true", help="write the best-value models into the quick, balanced and strong slots")
    p.add_argument("--out", help="save every result as JSON lines")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("routes", help="the routing table you tune, its history, and evidence imported from posts")
    p.add_argument("action", choices=("show", "history", "set", "reset", "rollback", "import", "evidence", "accept", "reject"))
    p.add_argument("words", nargs="*", help="KIND for set and reset; VERSION for rollback; files or URLs for import; IDs for accept and reject")
    p.add_argument("--slot", choices=SLOTS)
    p.add_argument("--prefer", help="vendors, best first, comma-separated (openai, anthropic, google, x-ai, ...)")
    p.add_argument("--models", help="provider:model names to try first, comma-separated")
    p.add_argument("--avoid", help="model names (or parts of names) not to use, comma-separated")
    p.add_argument("--why", help="the reason, saved with the version")
    p.add_argument("--model", help="accept: put these provider:model names first instead of the automatic match")
    p.add_argument("--manual", help="import: a .jsonl or .csv of your own claims (kind, model, verdict, vendor, model_id, quote)")
    p.add_argument("--again", action="store_true", help="import: read a post again even if it was imported before")
    p.add_argument("--kind", help="evidence: only this kind of task")
    p.add_argument("--all", action="store_true", help="evidence: include accepted and rejected claims")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_routes)

    p = sub.add_parser("tune", help="how each model did per kind of task, from your ratings, with proposals")
    p.add_argument("--days", type=int, default=0, help="only the last N days (default: everything)")
    p.add_argument("--apply", metavar="KIND", help="accept the proposal for this kind of task")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tune)

    p = sub.add_parser("replay", help="how other routers or routing-table versions would have routed your history")
    p.add_argument("--router", action="append", choices=ROUTERS, help="repeat to compare several (default: rules)")
    p.add_argument("--table", action="append", type=int, help="also replay with this routing-table version (0 = the starting table)")
    p.add_argument("--days", type=int, default=0)
    p.add_argument("--limit", type=int, default=500, help="at most this many recent answers")
    p.add_argument("--yes", action="store_true", help="allow the Jev calls the jev router makes")
    p.add_argument("--run", action="store_true", help="also re-answer a sample and have a third vendor judge (costs money)")
    p.add_argument("--sample", type=int, default=10)
    p.add_argument("--max-usd", type=float, default=1.0, help="with --run: stop before spending more than this")
    p.add_argument("--out", help="with --run: save every judged pair as JSON lines")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("export", help="your answers and ratings as a Langfuse dataset or JSON lines")
    p.add_argument("--dataset", help="Langfuse dataset name (created if missing; a repeated export updates items)")
    p.add_argument("--jsonl", help="write JSON lines to this file")
    p.add_argument("--only", choices=("all", "rated", "good", "bad"), default="rated")
    p.add_argument("--days", type=int, default=0)
    p.add_argument("--full", action="store_true", help="include text even when [record] content is metadata")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("handoff", help="versioned packets passed between models, apps and agents, checked in code")
    p.add_argument("action", choices=("pilot", "new", "send", "import", "show", "list", "kit", "reconcile", "resolve", "cancel"))
    p.add_argument("words", nargs="*", help="DIR for pilot; PACKET for new; TASK_ID for send, show, kit, resolve, cancel; RESULT for import")
    p.add_argument("--worker", choices=("model", "claude-code", "codex", "file"), default="model")
    p.add_argument("--model", help="send --worker model: this provider:model (default: a reviewer from another vendor)")
    p.add_argument("--kit", help="folder for the packet, schema and worker scripts")
    p.add_argument("--task", help="import: the task id, when the result does not name it")
    p.add_argument("--revision", type=int)
    p.add_argument("--exit", type=int, help="import: the worker's exit status (kept apart from its verdict)")
    p.add_argument("--note", default="")
    p.add_argument("--stale-after", type=float, default=900.0, help="reconcile: seconds before a claimed attempt is uncertain")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("serve", help="OpenAI-compatible HTTP server and a page showing recent activity")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="MCP server for Claude Code, Codex, Cursor or Hermes")
    p.add_argument("--http", action="store_true", help="serve over Streamable HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8788)
    p.set_defaults(func=cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    load_env()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv or ["chat"])
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except (providers.ProviderError, ValueError) as exc:
        print(f"crossvet chat: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:  # BudgetExceeded, NoModel
        print(f"crossvet chat: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
