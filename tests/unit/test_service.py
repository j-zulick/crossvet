"""crossvet service: launchd agents on macOS, systemd user units on Linux, and a status check."""

from __future__ import annotations

import plistlib

import httpx
import pytest

from crossvet import cli, service


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(service, "system", lambda: "macos")
    monkeypatch.setattr(service, "binary", lambda: "/opt/bin/crossvet")


def test_macos_agents_are_valid_plists(mac, tmp_path):
    files = service.units(8799, weekly=True)
    server, weekly = sorted(files)
    data = plistlib.loads(files[server].encode())
    assert data["ProgramArguments"] == ["/opt/bin/crossvet", "serve", "--host", "127.0.0.1", "--port", "8799"]
    assert data["KeepAlive"] is True and data["RunAtLoad"] is True and server.parent.name == "LaunchAgents"
    job = plistlib.loads(files[weekly].encode())
    assert job["StartCalendarInterval"]["Weekday"] == 1 and "KeepAlive" not in job
    assert "/opt/bin/crossvet tune auto" in job["ProgramArguments"][2] and "report --week --json >" in job["ProgramArguments"][2]


def test_linux_units_keep_the_dollar_sign_for_systemd(monkeypatch):
    monkeypatch.setattr(service, "system", lambda: "linux")
    monkeypatch.setattr(service, "binary", lambda: "/usr/bin/crossvet")
    files = {p.name: text for p, text in service.units(8787, weekly=True).items()}
    assert "ExecStart=/usr/bin/crossvet serve --host 127.0.0.1 --port 8787" in files["crossvet.service"]
    assert "$$(date +%F)" in files["crossvet-weekly.service"] and "OnCalendar=Mon" in files["crossvet-weekly.timer"]


def test_install_without_loading_then_uninstall(mac, capsys):
    assert cli.main(["service", "install", "--weekly", "--no-load"]) == 0
    out = capsys.readouterr().out
    assert out.count("wrote ") == 2 and "not started" in out
    assert all(p.exists() for p in service.units(8787, True))
    assert "removed" in service.uninstall() and not any(p.exists() for p in service.units(8787, True))


def test_install_loads_with_launchctl(mac, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run", lambda args: calls.append(args) or "")
    text = service.install(8787)
    assert ["launchctl", "bootstrap"] == calls[-1][:2] and "loaded com.github.j-zulick.crossvet.plist" in text


def test_status_says_whether_the_server_answers(mac):
    ok = service.status(8787, get=lambda url, timeout: httpx.Response(200, json={"version": "3.4.0"}))
    assert "not installed" in ok and "answering on 127.0.0.1:8787 (Crossvet 3.4.0)" in ok

    def down(url, timeout):
        raise httpx.ConnectError("refused")

    assert "not answering" in service.status(8787, get=down)


def test_other_systems_are_refused(monkeypatch):
    monkeypatch.setattr(service, "system", lambda: "windows")
    with pytest.raises(ValueError, match="macOS"):
        service.install()
