"""H-147 (CI-1): a run's or a publish's id is one the log's scrubber leaves whole.

The run record sends its reader to the log by the run's id. The adapter drew it as ``os.urandom(8).hex()``, and about
1 draw in 130 holds a digit run the scrubber reads as a phone number: the log line then shows ``d6d8b[PHONE]a`` and
no line holds the id (the 1-in-140 flake of ``test_adapter_failure_words.py``). ``tb_common.ids.log_safe_id`` draws
lower-case letters only, and every id the adapter hands out is drawn by it."""

from __future__ import annotations

import ast
import os
import random
import threading
from pathlib import Path
from typing import Any

import pytest
from tb_common import ids
from tb_common.logging import redact

from tests.unit import test_site_inputs

site = test_site_inputs.site  # the fixture: a site as the box holds it

ROOT = Path(__file__).resolve().parents[2]
CI_DRAW = "d6d8b0974142441a"  # the id CI drew in job 139204992870: "0974142441" reads as a phone number
DRAWS = 100_000
TEMPLATES = ("ingest run {} failed: ValueError", "publish {} failed: ValueError", '{{"run": "{}"}}')


def _changed(drawn: list[str]) -> list[str]:
    """The ids of ``drawn`` the scrubber changes in any line the adapter writes them in (a block of lines at a
    time: the scrubber reads a line's characters, and a letter id has no digit for a neighbour to join)."""
    out = []
    for i in range(0, len(drawn), 500):
        part = drawn[i : i + 500]
        for t in TEMPLATES:
            block = "\n".join(t.format(r) for r in part)
            if redact(block) != block:
                out += [r for r in part if redact(t.format(r)) != t.format(r)]
    return out


def test_a_planted_digit_run_id_is_masked_today() -> None:
    """The mechanism: the hex id CI drew is cut by the scrubber, so the line no longer holds it."""
    line = f"ingest run {CI_DRAW} failed: ValueError"
    assert redact(line) == "ingest run d6d8b[PHONE]a failed: ValueError"
    assert CI_DRAW not in redact(line)
    rng = random.Random(147)  # the old draw, seeded
    hex_draws = [rng.randbytes(8).hex() for _ in range(5_000)]
    assert len(_changed(hex_draws)) > 10  # about 1 in 130 (38 expected): the old draw is cut often


@pytest.mark.parametrize("seeded", [True, False], ids=["seeded", "system"])
def test_no_drawn_id_is_changed_by_the_scrubber(seeded: bool) -> None:
    rng = random.Random(147) if seeded else None
    drawn = [ids.log_safe_id(rng) for _ in range(DRAWS)]
    assert _changed(drawn) == []
    assert all(len(r) == ids.LENGTH == 16 and set(r) <= set(ids.ALPHABET) for r in drawn)
    assert len(set(drawn)) == DRAWS  # 75 bits: a repeat in 100,000 draws has odds of about 1 in 10^13


def test_the_id_is_at_least_as_strong_as_the_hex_id_it_replaces() -> None:
    import math

    assert ids.ALPHABET == "abcdefghijklmnopqrstuvwxyz" and ids.LENGTH == 16
    assert math.floor(ids.LENGTH * math.log2(len(ids.ALPHABET))) == ids.BITS == 75 > 64
    assert ids.log_safe_id().isalnum() and CI_DRAW.isalnum()  # an older hex id is still read back (runs.read)


def test_a_draw_the_scrubber_would_change_is_drawn_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule a site adds (its chart-number pattern) could read letters: such a draw is never handed out."""
    from tb_common import logging as tb_logging

    first = ids.log_safe_id(random.Random(147))
    monkeypatch.setattr(tb_logging, "_EXTRA_MRN", [])  # put back after the test
    tb_logging.set_mrn_regex(first)  # a site rule that happens to match the first draw exactly
    assert "[MRN]" in redact(f"run {first} failed")
    second = ids.log_safe_id(random.Random(147))  # the same generator: its first draw is refused
    assert second != first and redact(f"run {second} failed") == f"run {second} failed"


def test_every_id_the_adapter_hands_out_is_drawn_by_the_helper() -> None:
    """``services/adapter/app.py`` draws no id of its own: every ``rid`` it makes is ``ids.log_safe_id()``."""
    tree = ast.parse((ROOT / "services/adapter/app.py").read_text(encoding="utf-8"))
    drawn = [
        ast.unparse(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "rid" for t in n.targets)
    ]
    assert drawn.count("ids.log_safe_id()") == 3, drawn  # the run, the publish, the publish done already
    assert set(drawn) == {"ids.log_safe_id()", "str(state['run'])"}, drawn  # else the id read from the run's state
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not {c for c in calls if c.endswith(("urandom", "token_hex", "token_urlsafe", "uuid4", "randbytes"))}


def _boom(*_a: Any, **_k: Any) -> Any:
    raise ValueError("could not convert string to float: 'WANG XIAOMING'")


def test_the_log_line_of_a_failed_run_holds_the_whole_id_with_cis_draw_planted(
    site: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """CI's draw made the 8-byte draw of the process: the service's line must still hold the run's id whole."""
    from adapter import app as adapter_app
    from adapter import cli
    from fastapi.testclient import TestClient

    assert cli.main(["keys-init"]) == 0
    real = os.urandom
    monkeypatch.setattr(os, "urandom", lambda n: bytes.fromhex(CI_DRAW) if n == 8 else real(n))
    monkeypatch.setenv("TB_ADAPTER_RUN", "thread")
    monkeypatch.setattr(adapter_app, "_runs", {})
    monkeypatch.setattr(adapter_app, "_running", threading.Lock())
    monkeypatch.setattr(adapter_app, "run_ingest", _boom)
    client = TestClient(adapter_app.app)
    started = client.post("/run", json={"source": "csv", "snapshot": "2026-10-04", "load_fhir": False})
    assert started.status_code == 202, started.text
    rid = started.json()["run"]
    for _ in range(2400):
        st = client.get(f"/run/{rid}").json()
        if st["state"] != "running":
            break
        threading.Event().wait(0.05)
    assert st["state"] == "failed" and rid in st["detail"]
    logged = "".join(capfd.readouterr())
    assert f"ingest run {rid} failed: ValueError" in logged
