"""Run Crossvet as a service on this computer: the server your apps use every day, and an optional weekly job.

    crossvet service install [--port 8787] [--weekly] [--no-load]
    crossvet service status
    crossvet service uninstall

On macOS this writes launchd agents to ``~/Library/LaunchAgents`` (the server starts at login and is
restarted if it stops; logs go to ``~/Library/Logs/crossvet*.log``). On Linux it writes systemd user
units to ``~/.config/systemd/user``. ``--weekly`` adds a Monday job that runs ``crossvet score run``,
``crossvet tune auto`` and ``crossvet report --week --json`` (each changes nothing that its own
settings don't allow) and keeps the report in ``~/.local/share/crossvet/weekly/``. ``--no-load``
writes the files without starting anything. The service listens on 127.0.0.1 only; keys come from
``~/.config/crossvet/.env`` as usual. Commands run without a shell.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess  # noqa: S404 - launchctl and systemctl with fixed arguments, without a shell
import sys
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "com.github.j-zulick.crossvet"
WEEKLY = "crossvet score run --limit 50; crossvet tune auto; crossvet report --week --json"


def binary() -> str:
    """Return the full path of the ``crossvet`` command (services don't search your shell's PATH)."""
    found = shutil.which("crossvet")
    return found or str(Path(sys.executable).with_name("crossvet"))


def system() -> str:
    """Return "macos", "linux" or the platform's own name."""
    name = platform.system()
    return {"Darwin": "macos", "Linux": "linux"}.get(name, name.lower())


def plist(label: str, args: list[str], *, keep_alive: bool, weekly: bool = False, log: str = "crossvet") -> str:
    """Return a launchd agent definition."""
    home = Path.home()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
             '<plist version="1.0"><dict>', f"  <key>Label</key><string>{escape(label)}</string>",
             "  <key>ProgramArguments</key><array>", *(f"    <string>{escape(a)}</string>" for a in args), "  </array>",
             f"  <key>WorkingDirectory</key><string>{escape(str(home))}</string>",
             f"  <key>StandardOutPath</key><string>{escape(str(home / 'Library' / 'Logs' / (log + '.log')))}</string>",
             f"  <key>StandardErrorPath</key><string>{escape(str(home / 'Library' / 'Logs' / (log + '.log')))}</string>"]
    if keep_alive:
        lines += ["  <key>RunAtLoad</key><true/>", "  <key>KeepAlive</key><true/>"]
    if weekly:
        lines += ["  <key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer>"
                  "<key>Hour</key><integer>8</integer><key>Minute</key><integer>17</integer></dict>"]
    return "\n".join(lines + ["</dict></plist>", ""])


def units(port: int, weekly: bool) -> dict[Path, str]:
    """Return the service files for this computer: path -> content."""
    exe, home = binary(), Path.home()
    serve = [exe, "serve", "--host", "127.0.0.1", "--port", str(port)]
    report_dir = home / ".local" / "share" / "crossvet" / "weekly"
    job = f"mkdir -p '{report_dir}' && {WEEKLY.replace('crossvet ', exe + ' ')} > '{report_dir}/'$(date +%F).json"
    if system() == "macos":
        agents = home / "Library" / "LaunchAgents"
        files = {agents / f"{LABEL}.plist": plist(LABEL, serve, keep_alive=True)}
        if weekly:
            files[agents / f"{LABEL}.weekly.plist"] = plist(f"{LABEL}.weekly", ["/bin/sh", "-c", job], keep_alive=False,
                                                            weekly=True, log="crossvet-weekly")
        return files
    folder = home / ".config" / "systemd" / "user"
    files = {folder / "crossvet.service": (
        "[Unit]\nDescription=Crossvet: one chat, any model (OpenAI-compatible server on 127.0.0.1)\n\n"
        f"[Service]\nExecStart={' '.join(serve)}\nWorkingDirectory={home}\nRestart=on-failure\n\n"
        "[Install]\nWantedBy=default.target\n")}
    if weekly:
        quoted = job.replace("$", "$$")  # systemd expands $; $$ is a literal dollar sign
        files[folder / "crossvet-weekly.service"] = ("[Unit]\nDescription=Crossvet weekly: score, tune, report\n\n[Service]\nType=oneshot\n"
                                                     f"ExecStart=/bin/sh -c \"{quoted}\"\n")
        files[folder / "crossvet-weekly.timer"] = ("[Unit]\nDescription=Crossvet weekly, Mondays\n\n[Timer]\nOnCalendar=Mon *-*-* 08:17\n"
                                                   "Persistent=true\n\n[Install]\nWantedBy=timers.target\n")
    return files


def _run(args: list[str]) -> str:
    """Run a command; return "" when it worked, else what went wrong."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    except OSError as exc:
        return f"{args[0]} could not be run: {exc}"
    return "" if done.returncode == 0 else (done.stderr or done.stdout).strip()[:300]


def install(port: int = 8787, weekly: bool = False, load: bool = True) -> str:
    """Write the service files, and start them unless ``load`` is false; return what was done."""
    if system() not in ("macos", "linux"):
        raise ValueError(f"crossvet service supports macOS (launchd) and Linux (systemd); this is {platform.system()}")
    files = units(port, weekly)
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    lines = [f"wrote {path}" for path in files]
    if not load:
        return "\n".join(lines + ["not started (--no-load)"])
    if system() == "macos":
        domain = f"gui/{os.getuid()}"
        for path in files:
            _run(["launchctl", "bootout", domain, str(path)])  # replace an older copy; an error here means none was loaded
            problem = _run(["launchctl", "bootstrap", domain, str(path)])
            lines.append(f"loaded {path.name}" if not problem else f"launchctl could not load {path.name}: {problem}")
    else:
        names = [p.name for p in files if p.suffix in (".service", ".timer") and p.name != "crossvet-weekly.service"]
        for args in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", *names]):
            problem = _run(args)
            lines.append(" ".join(args[1:]) + (": ok" if not problem else f": {problem}"))
    lines.append(f"Point your apps at http://127.0.0.1:{port}/v1 (`crossvet service status` checks it).")
    return "\n".join(lines)


def uninstall() -> str:
    """Stop the services and remove their files."""
    files = [p for p in units(8787, True) if p.exists()]
    if not files:
        return "no Crossvet service files found"
    lines = []
    for path in files:
        if system() == "macos":
            _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)])
        else:
            _run(["systemctl", "--user", "disable", "--now", path.name])
        path.unlink()
        lines.append(f"removed {path}")
    return "\n".join(lines)


def status(port: int = 8787, get=None) -> str:  # noqa: ANN001 - an httpx-like get, for tests
    """Say which service files exist and whether the server answers on this computer."""
    import httpx

    files = [p for p in units(port, True) if p.exists()]
    lines = [f"installed: {p}" for p in files] or ["not installed (crossvet service install)"]
    try:
        response = (get or httpx.get)(f"http://127.0.0.1:{port}/health", timeout=3)
        version = response.json().get("version", "?") if response.status_code == 200 else None
        lines.append(f"server: answering on 127.0.0.1:{port} (Crossvet {version})" if version else
                     f"server: HTTP {response.status_code} on 127.0.0.1:{port}")
    except (httpx.HTTPError, ValueError, OSError):
        lines.append(f"server: not answering on 127.0.0.1:{port}")
    return "\n".join(lines)
