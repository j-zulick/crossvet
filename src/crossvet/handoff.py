"""Hand a task to a coding agent on this computer (Claude Code or Codex) and collect its result.

    crossvet handoff claude-code "Add a test for the per-call cap" --cwd ~/code/app
    crossvet handoff status 3        crossvet handoff result 3

The agent runs headless with its own defaults, which never approve edits on their own: Claude Code
in print mode (``claude -p``) and Codex with ``codex exec --sandbox read-only``. So a handoff reads,
reviews and proposes; it only changes files if you set the agent up to allow that. Each handoff
runs in the background with a time limit, and its status and output are kept in the lab file.
No shell is used: the task is passed as one argument.
"""

from __future__ import annotations

import shutil
import subprocess  # noqa: S404 - runs the agent CLIs you installed, without a shell
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crossvet.lab import Lab

AGENTS = {
    "claude-code": ("claude", lambda task: ["-p", task, "--output-format", "text"]),
    "codex": ("codex", lambda task: ["exec", "--sandbox", "read-only", task]),
}
TIMEOUT_SECONDS = 900
MAX_TASK = 20_000


def installed() -> dict[str, str]:
    """Return the agents whose CLI is on this computer, with its path."""
    found = {}
    for agent, (binary, _) in AGENTS.items():
        path = shutil.which(binary)
        if path:
            found[agent] = path
    return found


def submit(lab: Lab, agent: str, task: str, cwd: str = ".", timeout: float = TIMEOUT_SECONDS, wait: bool = False) -> int:
    """Start a handoff; return its id. With ``wait``, return once it has finished."""
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r}: use {', '.join(AGENTS)}")
    if not task.strip() or len(task) > MAX_TASK:
        raise ValueError(f"a handoff task needs 1 to {MAX_TASK:,} characters")
    folder = Path(cwd).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a folder")
    binary = installed().get(agent)
    if not binary:
        raise ValueError(f"{AGENTS[agent][0]} is not installed on this computer, so {agent} can't take the task")
    handoff_id = lab.add_handoff(agent, task, str(folder))
    command = [binary, *AGENTS[agent][1](task)]

    def work() -> None:
        start = time.monotonic()
        try:
            done = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
            status = "done" if done.returncode == 0 else f"failed (exit {done.returncode})"
            output = done.stdout + (f"\n[stderr]\n{done.stderr}" if done.returncode and done.stderr else "")
        except subprocess.TimeoutExpired:
            status, output = "timed out", f"stopped after {timeout:g} s"
        except OSError as exc:
            status, output = "failed", str(exc)
        lab.finish_handoff(handoff_id, status, output, time.monotonic() - start)

    thread = threading.Thread(target=work, daemon=not wait)
    thread.start()
    if wait:
        thread.join()
    return handoff_id


def describe(lab: Lab, handoff_id: int, with_result: bool = False) -> str:
    """Return a handoff's status (and output) as plain text."""
    row = lab.handoff(handoff_id)
    if row is None:
        return f"no handoff #{handoff_id}"
    took = f", {row['seconds']:.0f} s" if row["seconds"] else ""
    head = f"handoff #{row['id']} to {row['agent']} in {row['cwd']}: {row['status']}{took}"
    if not with_result:
        return head
    return head + ("\n\n" + row["result"] if row["result"] else "\n\n(no output yet)")
