"""Card 10C-1c: the log scrubber runs the privacy guard's rules, for every language the guard knows.

Before the card the scrubber had patterns of its own and left an identifier in 102 of the 120 Japanese probe lines
(``eval/phi_synth/ja_guard_probes.json``). Now a log record goes through the same spans the note masker masks and the
check before a model call refuses (``tb_common.phi_guard.note_spans``): every line of the two committed probe files
that the masker changes comes out of the logger changed, and no span the masker masks is left in it. Ordinary
operational lines (``tests/fixtures/log_scrub/operational_lines.txt``, built from the repository's own log calls) come
out byte-identical. A record the scrubber cannot finish in time, or at all, is written as "scrub failed", never as is.
An exception is written as its type and its frames, never its text (D-557). Every value here is synthetic.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tb_common import logging as tblog
from tb_common import phi_guard as pg
from tb_common.phi_guard import MASK_CHAR, mask_note

pytestmark = [pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
SYNTH = ROOT / "eval" / "phi_synth"
PROBES = json.loads((SYNTH / "ja_guard_probes.json").read_text(encoding="utf-8"))
NOTES = [json.loads(x) for x in (SYNTH / "notes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
OPERATIONAL = (ROOT / "tests" / "fixtures" / "log_scrub" / "operational_lines.txt").read_text(encoding="utf-8")
#: operational lines the guard itself over-masks (a defect of the guard's rules, not of the scrubber): each is a strict
#: expected failure, so a line that starts to pass fails the test and must leave this list
GUARD_OVERMASKS = {
    # ID_LABELLED reads "ID no" inside "did not" (no word boundary before its label) when the line holds a digit;
    # card 10C-1d in the pull request of 10C-1c
    "twin build after the ingest did not run: 2026-11-19T03:00:00Z",
}


def _probe_lines() -> list[str]:
    """Every text of the Japanese probe file (masked, unchanged, over-masked before, known gaps) and every note of
    the synthetic notes (Japanese, Traditional Chinese, English)."""
    gaps = PROBES["known_gaps"]
    lines = [p["text"] for p in PROBES["masked"]] + list(PROBES["unchanged"])
    lines += [x["text"] for x in PROBES["overmasked_before"]["lines"]]
    lines += [x["text"] for x in gaps["missed"]] + list(gaps["overmasked"])
    return lines + [n["text"] for n in NOTES]


class _Keep(logging.Handler):
    def __init__(self, service: str = "probe-svc") -> None:
        super().__init__()
        self.setFormatter(tblog.JsonFormatter(service))
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def keep() -> Iterator[tuple[logging.Logger, _Keep]]:
    lg = logging.getLogger("tb.test.scrub")
    h = _Keep()
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    try:
        yield lg, h
    finally:
        lg.removeHandler(h)


def _logged(text: str) -> str:
    lg = logging.getLogger("tb.test.scrub.one")
    h = _Keep()
    lg.addHandler(h)
    lg.propagate = False
    try:
        lg.warning("%s", text)
    finally:
        lg.removeHandler(h)
    return str(json.loads(h.lines[0])["msg"])


# ------------------------------------------------------------------------------------------------ the probe files
@pytest.mark.req("PRIV-29")
def test_every_probe_line_the_masker_changes_comes_out_of_the_logger_changed() -> None:
    """The model-call check's property, for the log: a line the masker changes is changed in the log, and no span the
    masker masks is left in it."""
    changed = 0
    for text in _probe_lines():
        out = _logged(text)
        spans = pg.note_spans(text)
        if mask_note(text) == text:
            continue
        changed += 1
        assert out != text, text
        left = [text[s:e] for _k, s, e in spans if text[s:e] in out]
        assert left == [], (text, out)
    assert changed >= 100 + 3 * 40  # the 120 masked probe lines (and more) and every synthetic note


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("probe", PROBES["masked"], ids=lambda p: p["text"])
def test_no_japanese_identifier_of_the_probe_set_reaches_the_log(probe: dict[str, Any]) -> None:
    out = _logged(probe["text"])
    assert [v for v in probe["ids"] if v in out] == [], out


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("lang", ["ja", "zh-TW", "en"])
def test_every_identifier_the_masker_masks_in_a_note_is_not_in_the_log(lang: str) -> None:
    """English and Traditional Chinese likewise: each identifier of a synthetic note that the masker masks whole."""
    checked = 0
    for note in (n for n in NOTES if n["lang"] == lang):
        text, out, masked = note["text"], _logged(note["text"]), mask_note(note["text"])
        for phi in note["phi"]:
            value = phi["span"]
            i = text.find(value)
            if text.count(value) != 1 or not all(
                masked[j] == MASK_CHAR or text[j].isspace() for j in range(i, i + len(value))
            ):
                continue  # not masked by the masker (an age, a facility: the guard's gaps), or written more than once
            checked += 1
            assert value not in out, (lang, value, out)
    assert checked >= 40, checked


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("lookup failed for 王小明先生 at 0912-345-678", "0912-345-678"),
        ("lookup failed for 王小明先生 at 0912-345-678", "王小明"),
        ("身分證字號 A123456789 refused", "A123456789"),
        ("Patient: John Smith, phone (415) 555-0134", "John Smith"),
        ("Patient: John Smith, phone (415) 555-0134", "555-0134"),
        ("mail to sample.person@example.org bounced", "sample.person@example.org"),
        ("ヤマダ　タロウ様の保険者番号 06130012", "ヤマダ　タロウ"),
        ("〒100-0001 東京都千代田区見本町1-2", "100-0001"),
    ],
)
def test_english_chinese_and_japanese_identifiers_in_a_log_line(text: str, value: str) -> None:
    assert value not in tblog.redact(text)


# ------------------------------------------------------------------------------------------------ operational lines
OPERATIONAL_LINES = [x for x in OPERATIONAL.splitlines() if x]


def test_the_operational_corpus_is_large_and_real_shaped() -> None:
    assert len(OPERATIONAL_LINES) >= 300
    joined = "\n".join(OPERATIONAL_LINES)
    for shape in ("GET /api", "01JITCOMPILE", "sha256:", "v1.4.2", "2026-11-19T03:00:00Z", "ms", "/data/"):
        assert shape in joined, shape


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(x, marks=pytest.mark.xfail(strict=True, reason="the guard over-masks it (10C-1d)"))
        if x in GUARD_OVERMASKS
        else x
        for x in OPERATIONAL_LINES
    ],
)
def test_an_operational_line_comes_out_byte_identical(line: str) -> None:
    tblog.site_rule_on()  # the contract's chart-number rule on, as at every service's start
    assert _logged(line) == line


# ------------------------------------------------------------------------------------------------ the record
def test_arguments_extra_fields_and_nested_values_are_scrubbed(keep: tuple[logging.Logger, _Keep]) -> None:
    lg, h = keep
    lg.info(
        "row of %s refused",
        "ヤマダ　タロウ様",
        extra={"detail": {"tel": ["090-1234-5678"], "n": 3}, "who": "王小明先生"},
    )
    line = h.lines[-1]
    for value in ("ヤマダ", "090-1234-5678", "王小明"):
        assert value not in line, line
    rec = json.loads(line)
    assert rec["detail"]["n"] == 3 and rec["msg"].startswith("row of ")


def test_an_exception_is_written_as_its_type_and_frames_never_its_text(keep: tuple[logging.Logger, _Keep]) -> None:
    lg, h = keep

    def parse(value: str) -> None:
        raise ValueError(f"cannot read {value!r}")

    row = "".join(["患者：山田 太郎 ", "090-1234-5678", " free text 呼吸苦"])  # a value, not a line of the code
    try:
        parse(row)
    except ValueError:
        lg.exception("row not read")
    rec = json.loads(h.lines[-1])
    assert rec["msg"] == "row not read"
    assert rec["exc"].endswith("ValueError") and "in parse" in rec["exc"]
    for value in ("山田", "090-1234-5678", "呼吸苦", "cannot read '"):  # the code's line is kept, never its value
        assert value not in h.lines[-1], h.lines[-1]


def test_a_third_party_logger_goes_through_the_scrubber(capsys: pytest.CaptureFixture[str]) -> None:
    with _SetUp():
        logging.getLogger("httpx").warning("POST %s failed for 090-1234-5678 (ヤマダ　タロウ様)", "/v1/x")
        logging.getLogger("some.library").error("cannot parse 身分證字號 A123456789")
    out = capsys.readouterr().out
    assert "090-1234-5678" not in out and "ヤマダ" not in out and "A123456789" not in out
    assert '"logger": "httpx"' in out and '"logger": "some.library"' in out


def test_an_uncaught_exception_and_a_warning_go_through_the_logger(capsys: pytest.CaptureFixture[str]) -> None:
    with _SetUp():
        try:
            raise RuntimeError("患者 山田 太郎 090-1234-5678")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        t = threading.Thread(target=lambda: (_ for _ in ()).throw(KeyError("A123456789")))
        t.start()
        t.join()
        warnings.warn("value 'ヤマダ　タロウ' expected str", UserWarning, stacklevel=1)
    cap = capsys.readouterr()
    text = cap.out + cap.err
    for value in ("山田", "090-1234-5678", "A123456789", "ヤマダ"):
        assert value not in text, text
    assert '"logger": "uncaught"' in cap.out and "UserWarning at" in cap.out


class _SetUp:
    """``setup_logging`` for one test, and everything it changes put back after."""

    def __enter__(self) -> None:
        root = logging.getLogger()
        self.saved = (root.handlers[:], root.level, sys.excepthook, threading.excepthook, warnings.showwarning)
        tblog.setup_logging("probe-svc")

    def __exit__(self, *_a: Any) -> None:
        root = logging.getLogger()
        root.handlers[:], level, sys.excepthook, threading.excepthook, warnings.showwarning = self.saved
        root.setLevel(level)


# ------------------------------------------------------------------------------------------------ failure and time
def _fixed(line: str) -> dict[str, Any]:
    rec: dict[str, Any] = json.loads(line)
    assert rec["msg"] == "scrub failed" and set(rec) == {"ts", "level", "service", "logger", "msg"}, rec
    return rec


def test_a_record_over_its_time_is_written_as_scrub_failed(
    keep: tuple[logging.Logger, _Keep], monkeypatch: pytest.MonkeyPatch
) -> None:
    lg, h = keep
    real = pg.note_spans

    def slow(text: str, mrn_regex: str | None = None) -> list[tuple[str, int, int]]:
        time.sleep(tblog.SCRUB_BUDGET_S + 0.05)
        return real(text, mrn_regex)

    monkeypatch.setattr(pg, "note_spans", slow)
    lg.warning("patient ヤマダ　タロウ様 at 090-1234-5678")
    rec = _fixed(h.lines[-1])
    assert rec["logger"] == "tb.test.scrub" and rec["service"] == "probe-svc"
    assert "ヤマダ" not in h.lines[-1]


def test_a_guard_error_and_a_bad_format_are_written_as_scrub_failed(
    keep: tuple[logging.Logger, _Keep], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lg, h = keep
    # the arguments do not fit the message: written as "scrub failed", not left to logging's handleError, which prints
    # the arguments to stderr (pytest's own capture handler would raise on it, so the record goes to ours alone)
    h.handle(lg.makeRecord(lg.name, logging.WARNING, __file__, 1, "value %d of %s", ("090-1234-5678",), None))
    _fixed(h.lines[-1])

    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("guard broke")

    monkeypatch.setattr(pg, "note_spans", broken)
    lg.warning("patient ヤマダ　タロウ様")
    _fixed(h.lines[-1])
    cap = capsys.readouterr()
    assert "090-1234-5678" not in cap.err + cap.out and "ヤマダ" not in cap.err + cap.out


def test_a_long_record_is_cut_and_scrubbed_within_its_time(keep: tuple[logging.Logger, _Keep]) -> None:
    lg, h = keep
    worst = ("No. 1 " * 200_000)[:1_000_000]  # the slowest shape of the guard's own adversarial inputs, 1 MB
    start = time.perf_counter()
    lg.warning("%s 090-1234-5678", worst)
    took = time.perf_counter() - start
    rec = json.loads(h.lines[-1])
    assert rec["msg"] != "scrub failed" and "characters not logged" in rec["msg"]
    assert len(rec["msg"]) <= tblog.MAX_FIELD + 64 and took < tblog.SCRUB_BUDGET_S, took


# ------------------------------------------------------------------------------------------------ loading
def _run(code: str) -> str:
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                         env={"PYTHONPATH": "libs:services:.", "PATH": "/usr/bin:/bin"}, check=False)  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def test_the_guard_is_loaded_on_the_first_record_and_without_cryptography() -> None:
    """No start-up cost for a process that never logs; the host's python3 (the support bundle) has no third-party
    package, and the guard loads without one."""
    out = _run(
        "import sys\n"
        "sys.modules['cryptography'] = None\n"
        "import tb_common.logging as L\n"
        "print('before', 'tb_common.phi_guard' in sys.modules)\n"
        "print(L.redact('ヤマダ　タロウ様 090-1234-5678'))\n"
        "print('after', 'tb_common.phi_guard' in sys.modules)\n"
    )
    assert "before False" in out and "after True" in out and "ヤマダ" not in out and "090-1234-5678" not in out


@pytest.mark.parametrize("first", ["tb_common.phi_guard", "tb_common.logging", "tb_common.http", "tb_common.llm"])
def test_no_import_cycle(first: str) -> None:
    _run(f"import {first}\nimport tb_common.logging, tb_common.phi_guard\nprint('ok')")


def test_the_scrubber_holds_no_identifier_pattern_of_its_own() -> None:
    """One set of rules: what the log scrubs is decided by the guard; logging.py only names it."""
    src = (ROOT / "libs" / "tb_common" / "logging.py").read_text(encoding="utf-8")
    assert "_PHI_PATTERNS" not in src and "０-９" not in src and "〒[" not in src
    assert tblog.scrub_identifiers("ヤマダ　タロウ様", None) == ("[NAME]様", 1)
