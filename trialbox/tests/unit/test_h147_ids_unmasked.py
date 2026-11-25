"""H-147 (CI-1): a run's or a publish's id is one the log's scrubber leaves whole.

The run record sends its reader to the log by the run's id. The adapter drew it as ``os.urandom(8).hex()``, and about
1 draw in 130 holds a digit run the scrubber reads as a phone number: the log line then shows ``d6d8b[PHONE]a`` and
no line holds the id (the 1-in-140 flake of ``test_adapter_failure_words.py``). ``tb_common.ids.log_safe_id`` draws
lower-case letters only, and every id the adapter hands out is drawn by it."""

from __future__ import annotations

import ast
import logging
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


def _cut_draw() -> str:
    """A draw of the old kind (8 random bytes in hex, seeded) that the scrubber cuts, as CI's did in job
    139204992870 (logged as ``d6d8b[PHONE]a``)."""
    rng = random.Random(147)
    return next(
        h for h in (rng.randbytes(8).hex() for _ in range(5_000)) if redact(f"run {h} failed") != f"run {h} failed"
    )


def test_a_planted_digit_run_id_is_masked_today() -> None:
    """The mechanism: an old-kind id with a digit run is cut by the scrubber, so the line no longer holds it."""
    cut = _cut_draw()
    line = f"ingest run {cut} failed: ValueError"
    assert cut not in redact(line)  # cut: "[PHONE]" or "[ID]" in its place
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
    assert ids.log_safe_id().isalnum() and _cut_draw().isalnum()  # an older hex id is still read back (runs.read)


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


def test_the_log_line_of_a_failed_run_holds_the_whole_id_with_a_cut_draw_planted(
    site: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Every 8-byte draw of the process is one the scrubber cuts: the service's line must still hold the run's id whole."""
    from adapter import app as adapter_app
    from adapter import cli
    from fastapi.testclient import TestClient

    assert cli.main(["keys-init"]) == 0
    real, planted = os.urandom, bytes.fromhex(_cut_draw())
    monkeypatch.setattr(os, "urandom", lambda n: planted if n == 8 else real(n))
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


LETTER_RULE = r"^[A-Za-z0-9]{6,20}$"  # a site's chart numbers with letters in them: it reads every letter draw


def _counted_scrubber(monkeypatch: pytest.MonkeyPatch, limit: int) -> dict[str, int]:
    """The scrubber, counted: past ``limit`` asks it raises, so a loop with no bound fails instead of hanging."""
    from tb_common import logging as tb_logging

    asked = {"n": 0}
    real = tb_logging.redact

    def counted(text: str) -> str:
        asked["n"] += 1
        if asked["n"] > limit:
            raise AssertionError(f"the scrubber was asked more than {limit} times: the draw loop has no bound")
        return real(text)

    monkeypatch.setattr(tb_logging, "redact", counted)
    return asked


def test_a_site_rule_that_reads_letters_does_not_hang_the_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    """1515-1: such a rule changes every draw. The helper stops after ``ATTEMPTS`` draws and hands out the last one
    (a valid id; its log line then shows the rule's kind, as a hex id's did), never a request that spins."""
    from tb_common import logging as tb_logging

    monkeypatch.setattr(tb_logging, "_EXTRA_MRN", [])  # put back after the test
    tb_logging.set_mrn_regex(LETTER_RULE)
    asked = _counted_scrubber(monkeypatch, 1000)
    rid = ids.log_safe_id(random.Random(147))
    assert len(rid) == ids.LENGTH and set(rid) <= set(ids.ALPHABET)
    assert asked["n"] == ids.ATTEMPTS == 32  # every draw refused, then the bound


def test_a_run_is_started_under_a_site_rule_that_reads_letters(
    site: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1515-1: ``POST /run`` holds the run gate while it draws; under such a rule it answers 202, it does not spin."""
    from adapter import app as adapter_app
    from adapter import cli
    from fastapi.testclient import TestClient
    from tb_common import logging as tb_logging

    assert cli.main(["keys-init"]) == 0
    monkeypatch.setenv("TB_ADAPTER_RUN", "thread")
    monkeypatch.setattr(adapter_app, "_runs", {})
    monkeypatch.setattr(adapter_app, "_running", threading.Lock())
    monkeypatch.setattr(adapter_app, "run_ingest", _boom)
    monkeypatch.setattr(tb_logging, "_EXTRA_MRN", [])
    tb_logging.set_mrn_regex(LETTER_RULE)
    _counted_scrubber(monkeypatch, 5000)  # the request's own log lines are a few asks; a spinning draw is endless
    client = TestClient(adapter_app.app, raise_server_exceptions=False)
    started = client.post("/run", json={"source": "csv", "snapshot": "2026-10-04", "load_fhir": False})
    assert started.status_code == 202, started.text
    rid = started.json()["run"]
    assert len(rid) == ids.LENGTH and set(rid) <= set(ids.ALPHABET)


class _Lines(logging.Handler):
    """The lines a service's own formatter writes (the scrubber runs there), whatever handlers the process holds."""

    def __init__(self, service: str) -> None:
        from tb_common.logging import JsonFormatter

        super().__init__(logging.DEBUG)
        self.setFormatter(JsonFormatter(service))
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _lines_of(monkeypatch: pytest.MonkeyPatch, logger: str, service: str) -> _Lines:
    lines = _Lines(service)
    lg = logging.getLogger(logger)
    monkeypatch.setattr(lg, "handlers", [*lg.handlers, lines])  # a new list: the old one is put back after the test
    monkeypatch.setattr(lg, "level", logging.DEBUG)
    monkeypatch.setattr(lg, "disabled", False)
    return lines


def test_the_compilers_error_id_is_logged_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    """H147-02: a 500 gives the caller an ``error_id`` to find the log line by; with a draw the scrubber cuts
    planted where the old id came from (``uuid4().hex[:12]``), the logged line must still hold the id whole."""
    import uuid

    from tests.unit.test_compiler_answers_every_failure import _post

    rng = random.Random(147)
    cut = next(h for h in (rng.randbytes(6).hex() for _ in range(20_000)) if redact(h) != h)
    planted = uuid.UUID(hex=cut + "0" * 20)
    monkeypatch.setattr(uuid, "uuid4", lambda: planted)
    lines = _lines_of(monkeypatch, "criteria-compiler", "criteria-compiler")
    resp, _ = _post(monkeypatch, KeyError("a value that must never be shown"))
    assert resp.status_code == 500
    error_id = resp.json()["detail"]["error_id"]
    [line] = [x for x in lines.lines if '"msg": "unhandled error"' in x]
    assert f'"error_id": "{error_id}"' in line


def test_a_cascade_runs_id_is_logged_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H147-03: a failed cascade run is logged by its id; with a ULID the scrubber cuts planted where the old id came
    from (``new_ulid``), the logged line must still hold the run's id whole."""
    from console import cascade
    from tb_common.ulid import new_ulid

    cut = next(u for u in (new_ulid() for _ in range(2_000_000)) if redact(u) != u)
    monkeypatch.setattr(cascade, "new_ulid", lambda: cut, raising=False)  # where the old code drew it

    def broke(source: Path, trial: str, out: Path) -> dict[str, object]:
        raise RuntimeError("the drop could not be read")

    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "patient.csv").write_text("pid\n", encoding="utf-8")  # a synthetic site drop is "mounted"
    done = threading.Event()
    lines = _lines_of(monkeypatch, "console.cascade", "console")
    run = cascade.CascadeRuns(tmp_path / "runs", drop, runner=broke).start("GZQO", "crc", lambda _r: done.set())
    assert done.wait(30)
    [line] = [x for x in lines.lines if '"msg": "cascade run failed"' in x]
    assert f'"run": "{run.run_id}"' in line
