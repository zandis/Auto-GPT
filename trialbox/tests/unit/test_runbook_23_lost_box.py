"""Card 10K-9 (D-1362): the drill of RUNBOOK §23, the lost-box list (``docs/runbook/23-key-inventory-and-the-lost-box-
list.md``), its command part.

``python -m tools.keys inventory --json`` lists every key of the box the lost-box list names, with a compromise
action; each command the list gives for a key on the box is the command the inventory gives for it, and the tool
takes it (``--help`` of each subcommand runs); ``site_hmac.key``, which the page says is not rotated, is the one the
inventory says is never rotated. The tabletop part (the box reported stolen at 10:00, each row given to a person and
timed) is a meeting, not a test; the page says so.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from tools import keys
from tools.trialbox import __main__ as tb_main

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "runbook" / "23-key-inventory-and-the-lost-box-list.md"
# a row of the lost-box list that is a key of the box -> the name the inventory gives it (in its row)
ON_THE_BOX = {
    "OIDC client secret": "OIDC client secret",
    "staff second-factor (TOTP) secrets": "totp.key",
    "the backup key pair": "backup key pair",
    "the KEK": "KEK (key-encryption key)",
    "`pid_map.key`": "pid_map.key",
    "vendor update key": "vendor update key",
    "the alliance signing key": "alliance signing key",
}


def lost_box_rows() -> dict[str, tuple[str, str]]:
    """The lost-box table: its first cell (shortened to the text before a bracket) -> (where changed, who)."""
    text = PAGE.read_text(encoding="utf-8").split("## The lost-box list", 1)[1].split("\n## ", 1)[0]
    rows: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and not set(cells[0]) <= set("- ") and cells[0] != "Secret outside the box":
            rows[cells[0]] = (cells[1], cells[2])
    return rows


def _inventory(capsys: pytest.CaptureFixture[str]) -> dict[str, dict[str, str]]:
    capsys.readouterr()
    assert keys.main(["inventory", "--json"], env={}) == 0
    return {r["key"]: r for r in json.loads(capsys.readouterr().out)}


def _takes(argv: list[str], main: Callable[[list[str]], object]) -> None:
    """The tool knows the subcommand: its ``--help`` exits 0."""
    with pytest.raises(SystemExit) as ex:
        main([*argv, "--help"])
    assert ex.value.code == 0, argv


def test_runbook_23_lost_box(capsys: pytest.CaptureFixture[str]) -> None:
    rows = lost_box_rows()
    inv = _inventory(capsys)
    assert len(rows) >= 14  # the list as written: every secret outside the box and every key of the box
    for row_start, inv_key in ON_THE_BOX.items():
        row = next((r for r in rows if r.startswith(row_start)), None)
        assert row is not None, f"the lost-box list has no row for {row_start}"
        held = next((k for k in inv if inv_key in k), None)  # a row may hold several (the OIDC client secret's)
        assert held is not None, f"the inventory does not list {inv_key} (lost-box row {row})"
        assert inv[held]["compromise"] and inv[held]["holder"], held

    # the commands the list gives for keys on the box are the inventory's own, and the tools take them
    commands = {r: re.findall(r"`([^`]+)`", where) for r, (where, _) in rows.items()}
    kek = next(c for r, c in commands.items() if r.startswith("the KEK"))
    pid = next(c for r, c in commands.items() if r.startswith("`pid_map.key`"))
    backup = next(c for r, c in commands.items() if r.startswith("the backup key pair"))
    totp_row = next(c for r, c in commands.items() if r.startswith("staff second-factor"))
    assert kek == ["python -m tools.keys rotate-kek"] == [inv["KEK (key-encryption key)"]["code"]]
    assert pid == ["python -m tools.keys rotate pid_map"] == [inv["pid_map.key"]["code"]]
    assert backup == ["trialbox backup-keygen"]
    assert inv["backup key pair"]["code"].startswith("python -m tools.trialbox backup-keygen")
    assert totp_row == ["console.cli reset-totp NAME"]
    _takes(["rotate-kek"], lambda a: keys.main(a, env={}))
    _takes(["rotate", "pid_map"], lambda a: keys.main(a, env={}))
    _takes(["backup-keygen"], tb_main.main)
    from console import cli

    _takes(["reset-totp", "NAME"], cli.main)

    # "Not rotated: site_hmac.key": the inventory says never, and the tool refuses to rotate it
    assert "**Not rotated:** `site_hmac.key`" in PAGE.read_text(encoding="utf-8")
    assert inv["site_hmac.key"]["rotation"].startswith("never")
    capsys.readouterr()
    assert keys.main(["rotate", "site_hmac"], env={}) == 2
    assert "is not rotated by this tool. Rule: never" in capsys.readouterr().err
