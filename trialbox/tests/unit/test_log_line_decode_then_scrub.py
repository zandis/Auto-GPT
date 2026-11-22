"""H-79 (D-1358): every value that enters a service's log line passes one decode-then-scrub.

The integrator's order of 2026-11-22 10:07 UTC: a secret behind two to four ``%`` layers or written ``password&#61;``,
and an address written ``%40`` or ``&#64;``, stayed in a service's log line; the review's R22-21: values given
through ``extra=`` that are not text (objects, exceptions, bytes, numbers, dataclasses) went out as written, and
R22-22: a formatter error printed the raw arguments. The invariant is
``test_h79_no_planted_value_in_any_encoding_or_place_reaches_the_emitted_bytes``. All values are synthetic and
built at run time.
"""

from __future__ import annotations

import collections
import collections.abc
import dataclasses
import functools
import io
import json
import logging
import random
import string
import sys
import time
from collections.abc import Callable
from typing import Any

import pytest
from tb_common import logging as tblog
from tb_common.decode_scrub import decode

SECRET = "Zq" + "81xRv0K2pL"  # written after a secret's name
HELD = "held-" + "Wv93kLm0Pq7s"  # a value the process holds (registered), written bare
MAIL = "jo.doe" + "@" + "example.org"
TWID = "A1" + "23456789"
CHART = "1234" + "5678"  # the contract's default chart-number pattern (^\d{8}$)
NEEDLES = (SECRET, HELD, MAIL, TWID, CHART)

#: every form the formatter masked written plain, before this card
PLAIN = [
    f"next=/x?password={SECRET}",
    f"token: {SECRET}",
    f"api_key={SECRET}",
    f"Authorization: Bearer {SECRET}",
    f"postgresql://u:{SECRET}@db:5432/x",
    f"seen {HELD} here",
    f"GET /x?to={MAIL}",
    f"id {TWID}",
    f"chart {CHART}",
]

_CRITICAL = "=:@/?"
_NAMED = {"=": "&equals;", ":": "&colon;", "@": "&commat;", "/": "&sol;", "?": "&quest;"}


def _pct(text: str, layers: int, every: bool = False) -> str:
    out = "".join(f"%{b:02X}" if every or chr(b) in _CRITICAL else chr(b) for b in text.encode())
    for _ in range(layers - 1):
        out = out.replace("%", "%25")
    return out


def _each(text: str, fn: Callable[[str], str], every: bool = False) -> str:
    return "".join(fn(c) if every or c in _CRITICAL else c for c in text)


#: the encoding classes, each with the layer counts it is tried at
ENCODINGS: dict[str, Callable[[str], str]] = {
    "raw": lambda t: t,
    **{f"percent-{n}": functools.partial(_pct, layers=n) for n in range(1, 5)},
    **{f"percent-all-{n}": functools.partial(_pct, layers=n, every=True) for n in range(1, 5)},
    "entity-dec": lambda t: _each(t, lambda c: f"&#{ord(c)};"),
    "entity-dec-no-semicolon": lambda t: _each(t, lambda c: f"&#{ord(c)}"),
    "entity-hex": lambda t: _each(t, lambda c: f"&#x{ord(c):x};"),
    "entity-hex-no-semicolon": lambda t: _each(t, lambda c: f"&#x{ord(c):X}"),
    "entity-named": lambda t: _each(t, lambda c: _NAMED[c]),
    "entity-dec-all": lambda t: _each(t, lambda c: f"&#{ord(c)};", every=True),
    "entity-twice": lambda t: _each(t, lambda c: f"&amp;#{ord(c)};"),
    "backslash-x": lambda t: _each(t, lambda c: f"\\x{ord(c):02x}"),
    "backslash-u-all": lambda t: _each(t, lambda c: f"\\u{ord(c):04x}", every=True),
    "backslash-U": lambda t: _each(t, lambda c: f"\\U{ord(c):08x}"),
    "quoted-printable": lambda t: t.replace("=", "=3D").replace("@", "=40"),
    "percent-of-entity": lambda t: _each(t, lambda c: _pct(f"&#{ord(c)};", 1, every=True)),
    "percent-2-of-entity": lambda t: _each(t, lambda c: _pct(f"&#{ord(c)};", 2, every=True)),
}


@dataclasses.dataclass
class Row:
    note: str
    count: int = 1


Pair = collections.namedtuple("Pair", ["a", "b"])


class Shown:
    def __init__(self, text: str) -> None:
        self.text = text

    def __str__(self) -> str:
        return f"Shown({self.text})"


def _raised(text: str) -> Any:
    try:
        raise ValueError(text)
    except ValueError:
        return sys.exc_info()


#: every place a value enters the emitted line: (name, how a record is built from the text)
def _record(
    msg: str = "probe", args: Any = None, name: str = "probe", exc_info: Any = None, **extra: Any
) -> logging.LogRecord:
    rec = logging.LogRecord(name, logging.WARNING, __file__, 1, msg, args, exc_info)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def _keyed(rec: logging.LogRecord, key: str) -> logging.LogRecord:
    setattr(rec, key, 1)
    return rec


PLACES: dict[str, Callable[[str], logging.LogRecord]] = {
    "message": _record,
    "args": lambda t: _record("a %s b", (t,)),
    "args-mapping": lambda t: _record("a %(v)s b", ({"v": t},)),
    "args-repr": lambda t: _record("a %r b", (t,)),
    "logger-name": lambda t: _record(name=t),
    "extra-text": lambda t: _record(field=t),
    "extra-key": lambda t: _keyed(_record(), t),
    "extra-dict-value": lambda t: _record(field={"k": t}),
    "extra-dict-key": lambda t: _record(field={t: 1}),
    "extra-list": lambda t: _record(field=[1, t]),
    "extra-tuple-set": lambda t: _record(field=((t,), frozenset({t}))),
    "extra-nested": lambda t: _record(field={"a": [{"b": [{"c": (t,)}]}]}),
    "extra-bytes": lambda t: _record(field=t.encode()),
    "extra-exception": lambda t: _record(field=ValueError(t)),
    "extra-dataclass": lambda t: _record(field=Row(t)),
    "extra-namedtuple": lambda t: _record(field=Pair(t, 2)),
    "extra-object": lambda t: _record(field=Shown(t)),
    "extra-object-in-list": lambda t: _record(field=[Shown(t)]),
    "extra-tuple-key": lambda t: _record(field={(t, 1): "v"}),
    "exc-info": lambda t: _record(exc_info=_raised(t)),
}


@pytest.fixture
def rules(monkeypatch: pytest.MonkeyPatch) -> tblog.JsonFormatter:
    monkeypatch.setattr(tblog, "_SECRET_VALUES", set())
    monkeypatch.setattr(tblog, "_EXTRA_MRN", [])
    monkeypatch.setattr(tblog, "_NAMES", {})
    tblog.set_mrn_regex(r"^\d{8}$")
    tblog.register_secret(HELD)
    return tblog.JsonFormatter("probe")


def _texts(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in (*_texts(k), *_texts(v))]
    if isinstance(obj, list):
        return [x for v in obj for x in _texts(v)]
    return [str(obj)]


def _leaks(line: str, needles: tuple[str, ...]) -> list[str]:
    """Each needle found in the emitted bytes, raw or after every encoding is undone, in any text of the JSON."""
    texts = [line, *_texts(json.loads(line))]
    seen = [*texts, *(decode(t) for t in texts)]
    return [n for n in needles if any(n in s for s in seen)]


def test_h79_no_planted_value_in_any_encoding_or_place_reaches_the_emitted_bytes(rules: tblog.JsonFormatter) -> None:
    """The invariant: every form the formatter masks, in every encoding class and layer count, in every place a
    value enters the line, leaves nothing of the value in the emitted bytes (raw or decoded)."""
    failures: list[str] = []
    count = 0
    for plain in PLAIN:
        for enc_name, enc in ENCODINGS.items():
            text = enc(plain)
            for place, build in PLACES.items():
                line = rules.format(build(text))
                count += 1
                leaked = _leaks(line, NEEDLES)
                if leaked:
                    failures.append(f"{place} / {enc_name} / {plain.split(' ')[0][:12]}")
    assert count == len(PLAIN) * len(ENCODINGS) * len(PLACES)
    assert not failures, f"{len(failures)} of {count} leaked, e.g. {failures[:8]}"


def test_h79_the_benchs_three_lines_are_masked(rules: tblog.JsonFormatter) -> None:
    for line in (
        f"next=%252Fx%253Fpassword%253D{SECRET}",
        f"next=/x?password&#61;{SECRET}",
        "GET /x?to=" + MAIL.replace("@", "%40"),
        "to " + MAIL.replace("@", "&#64;"),
    ):
        out = json.loads(rules.format(_record(line)))["msg"]
        assert SECRET not in out and MAIL not in out
        assert "[SECRET]" in out or "[EMAIL]" in out


def test_h79_a_rule_that_matches_inside_an_encoding_does_not_hide_the_value(rules: tblog.JsonFormatter) -> None:
    """Found by the fuzz: ``%25252536`` holds eight digits, the chart-number rule masked them in the encoded text,
    and the decoded pass then saw no secret. The line is decoded before any rule reads it."""
    for text in (_pct(f"token={SECRET}", 4, every=True), _pct(f"to={MAIL}", 4, every=True)):
        assert not _leaks(rules.format(_record(text)), NEEDLES)
        assert not _leaks(json.dumps(tblog.redact(text)), NEEDLES)


#: the fuzz classes: (name, how one value is hidden, layers drawn from)
FUZZ: dict[str, Callable[[str, int], str]] = {
    "percent": _pct,
    "percent-all": lambda t, n: _pct(t, n, every=True),
    "entity-numeric": lambda t, n: _each(t, lambda c: f"&#{ord(c)}" + ";" * (n % 2)),
    "entity-hex": lambda t, n: _each(t, lambda c: f"&#x{ord(c):x}" + ";" * (n % 2)),
    "entity-named": lambda t, n: _each(t, lambda c: _NAMED[c]),
    "backslash": lambda t, n: _each(t, lambda c: f"\\x{ord(c):02x}" if n % 2 else f"\\u{ord(c):04x}"),
    "quoted-printable": lambda t, n: t.replace("=", "=3D").replace("@", "=40"),
    "percent-of-entity": lambda t, n: _each(t, lambda c: _pct(f"&#{ord(c)};", n, every=True)),
}
_NOISE = ["ok", "GET /api/v1/x?page=2&size=50", "restarts=2", "D-1358", "2026-11-22T10:07:00Z", "100%", "R&D", ""]
_LABELS = ["password", "token", "api_key", "secret", "access_token", "pw", "client_secret"]


@pytest.mark.parametrize("kind", sorted(FUZZ))
def test_h79_fuzz_150_cases_each_encoding_class(rules: tblog.JsonFormatter, kind: str) -> None:
    rng = random.Random(f"h79-{kind}")  # fixed seed: the same 150 cases on every run
    alnum = string.ascii_letters + string.digits
    misses = []
    for case in range(150):
        secret = "".join(rng.choice(alnum) for _ in range(rng.randint(8, 24)))
        local = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(2, 10)))
        mail = f"{local}.{rng.choice(['x', 'yz'])}@" + rng.choice(["example.org", "example.com", "test.example.net"])
        layers = rng.randint(1, 4)
        if case % 2:
            plain, needle = f"{rng.choice(_LABELS)}={secret}", secret
        else:
            plain, needle = f"to={mail}", mail
        text = f"{rng.choice(_NOISE)} {FUZZ[kind](plain, layers)} {rng.choice(_NOISE)}".strip()
        line = rules.format(_record(text) if case % 3 else _record(field={"v": [text]}))
        if _leaks(line, (needle,)):
            misses.append(case)
    assert not misses, f"{kind}: {len(misses)} of 150 kept the value (cases {misses[:10]})"


#: what must stay readable: ordinary ids, timestamps, decision ids, counts, an escape that hides nothing
NEAR_MISSES = [
    "job 01HZX3K9V7Q2M4N6P8R0T2W4Y6 done",
    "trace 3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f",
    "at 2026-11-22T10:07:00.123+00:00 took 12.5 ms",
    "decision D-1358 applied; finding H79-01",
    "restarts=2 retries=3 count=40 items",
    "pid " + "a" * 32,
    "sha256 " + "ab3f9e" * 10 + "ab3f",
    "cpu=85% disk 100% full",
    "GET /api/v1/studies?page=2&size=50&sort=asc",
    "R&D budget; Q&A at 10:00",
    "html &amp; &lt;b&gt; kept as written",
    "path %2Fdata%2Fx kept as written",
    "name \\u5c71 kept as written",
    "token registry loaded; password refused for the user; bypass=on",
    "version 1.2.3 on port 8443",
    "pid=4018f357768088526010207fd39062b9.json read",  # a value after = that starts with 40: not a QP @
    "x==4018f357768088526010207fd39062b9&y=1",
    "pid=40a1b2c3d4e5f60718293a4b5c6d7e8f.json read",
    "GET /x?retry=404.html&page=2",  # =40 before a digit is not an @
]


@pytest.mark.parametrize("line", NEAR_MISSES)
def test_h79_a_near_miss_is_emitted_as_written(rules: tblog.JsonFormatter, line: str) -> None:
    assert json.loads(rules.format(_record(line)))["msg"] == line


def test_h79_a_quoted_printable_at_does_not_cut_a_value(rules: tblog.JsonFormatter) -> None:
    """Found at the merge with H-76a: ``=40`` read anywhere took the first digits of a value after ``=`` and cut a
    pseudonym. It is read as ``@`` only before a letter that does not start 8 hex digits; an address on a line that
    also holds a secret is still found."""
    for text in (
        "to " + MAIL.replace("@", "=40"),
        f"postgresql://u:{SECRET}=40db:5432/x",
        f"password={SECRET} then to " + MAIL.replace("@", "=40"),
    ):
        assert not _leaks(rules.format(_record(text)), NEEDLES), text


def test_h79_what_is_masked_or_changed_though_it_may_hide_nothing(rules: tblog.JsonFormatter) -> None:
    """Owned over-masks: a line decoded because it held a value loses its other escapes too; a quoted-printable
    ``=40`` before a domain is read as ``@``."""
    out = json.loads(rules.format(_record("path=%2Fdata to " + MAIL.replace("@", "%40"))))["msg"]
    assert out == "path=/data to [EMAIL]"
    assert json.loads(rules.format(_record("user=40example.org")))["msg"] == "[EMAIL]"


def test_r22_21_values_that_are_not_text_are_scrubbed(rules: tblog.JsonFormatter) -> None:
    """The review's R22-21, each kind it named: an object, a dataclass, an exception, bytes, a chart number as an
    integer, a file path; and a value under a secret's name in a mapping."""
    from pathlib import PurePosixPath

    phone = "090-" + "1234-5678"
    rec = _record(
        payload=Row(f"call {phone}"),
        obj=Shown(MAIL),
        err=KeyError(TWID),
        raw=f"to {MAIL}".encode(),
        chart=int(CHART),
        path=PurePosixPath(f"/srv/{MAIL}/x.txt"),
        cfg={"password": SECRET, "dbPassword": SECRET, "apiKey": SECRET, "retries": 3, "token": True},
    )
    line = rules.format(rec)
    assert not _leaks(line, (*NEEDLES, phone))
    got = json.loads(line)
    assert got["chart"] == "[MRN]" and got["cfg"]["retries"] == 3 and got["cfg"]["token"] is True
    assert got["cfg"]["password"] == got["cfg"]["dbPassword"] == got["cfg"]["apiKey"] == "[SECRET]"


def test_r22_21_numbers_and_flags_that_hide_nothing_stay_numbers(rules: tblog.JsonFormatter) -> None:
    got = json.loads(rules.format(_record(n=42, f=1.5, b=False, z=None, secrets_hidden=3, pass_count=2)))
    assert (got["n"], got["f"], got["b"], got["z"], got["secrets_hidden"], got["pass_count"]) == (
        42,
        1.5,
        False,
        None,
        3,
        2,
    )


def test_r22_22_a_record_the_formatter_cannot_render_gives_a_withheld_line(rules: tblog.JsonFormatter) -> None:
    """A broken format string, a broken record: one line that says the message was withheld, with the logger and
    the level, never the raw arguments; nothing raised."""
    for rec in (_record("%d and %s", ("x", SECRET)), _record("x", created="not a time")):
        got = json.loads(rules.format(rec))
        assert got["msg"].startswith("[message withheld: the PHI scrubber failed (")
        assert got["logger"] == "probe" and got["level"] == "WARNING"
        assert SECRET not in json.dumps(got)


def test_r22_22_through_a_handler_nothing_reaches_the_error_stream(
    rules: tblog.JsonFormatter, capsys: pytest.CaptureFixture[str]
) -> None:
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(rules)
    log = logging.getLogger("h79.probe")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.error("%d and %s", "x", SECRET)
        log.error("probe", extra={"field": {(1, 2): HELD, "k": object()}})
    finally:
        log.removeHandler(handler)
    lines = out.getvalue().splitlines()
    assert len(lines) == 2 and SECRET not in out.getvalue() and HELD not in out.getvalue()
    assert "withheld" in json.loads(lines[0])["msg"]
    assert capsys.readouterr().err == ""


def test_h79_a_value_that_cannot_be_read_is_withheld_alone(rules: tblog.JsonFormatter) -> None:
    class Broken:
        def __str__(self) -> str:
            raise RuntimeError(SECRET)

    class BadMap(collections.abc.Mapping[str, int]):
        def __getitem__(self, key: str) -> int:
            raise KeyError(key)

        def __len__(self) -> int:
            return 1

        def __iter__(self) -> Any:
            raise RuntimeError(SECRET)

    got = json.loads(rules.format(_record("kept", a=Broken(), b=BadMap(), c="also kept")))
    assert got["msg"] == "kept" and got["c"] == "also kept"
    assert got["a"] == "<Broken: its text could not be read>"
    assert got["b"].startswith("[message withheld")
    assert SECRET not in json.dumps(got)


def test_h79_a_lone_surrogate_does_not_stop_the_line(rules: tblog.JsonFormatter) -> None:
    line = rules.format(_record("bad \udc80 char", field="\\ud83d" + MAIL.replace("@", "%40")))
    line.encode("utf-8")
    assert not _leaks(line, (MAIL,))


def test_h79_cycles_depth_and_count_are_bounded(rules: tblog.JsonFormatter) -> None:
    loop: list[Any] = [MAIL]
    loop.append(loop)
    deep: Any = MAIL
    for _ in range(10_000):
        deep = [deep]
    got = json.loads(
        rules.format(_record(loop=loop, deep=deep, many=list(range(10**6)), wide=dict.fromkeys(range(10**5), MAIL)))
    )
    assert got["loop"] == ["[EMAIL]", tblog.CYCLE]
    assert tblog.WITHHELD in json.dumps(got["deep"])
    assert len(got["many"]) <= tblog.MAX_VALUES + 1 and tblog.TOO_MANY in got["many"]
    assert not _leaks(json.dumps(got), (MAIL,))


#: worst cases for time: each a 1 MB line (the formatter cuts it to TB_LOG_SCRUB_MAX_CHARS before it scrubs)
WORST = {
    "percent-run": "%25" * 350_000,
    "percent-layers": "%" + "25" * 500_000 + "40",
    "entity-run": "&#" * 500_000,
    "entity-numbers": "&#61" * 250_000,
    "named-entity-run": "&amp" * 250_000,
    "backslash-run": "\\u0040" * 170_000,
    "quoted-printable-run": "=3D=40" * 170_000,
    "long-hex": "0123456789abcdef" * 65_536,
    "at-run": "@" * 1_000_000,
    "encoded-addresses": "a.b%40example.org " * 55_000,
    "encoded-secrets": "password%3Dabcdefgh&" * 50_000,
}


@pytest.mark.parametrize("kind", sorted(WORST))
def test_h79_a_worst_case_line_is_scrubbed_in_bounded_time(rules: tblog.JsonFormatter, kind: str) -> None:
    rules.format(_record("warm"))
    start = time.perf_counter()
    rules.format(_record(WORST[kind]))
    assert time.perf_counter() - start < 5.0


@pytest.mark.parametrize("kind", sorted(WORST))
def test_h79_a_worst_case_is_linear_without_the_cut(
    rules: tblog.JsonFormatter, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rule of the decoding is quadratic: the line's first 256 KB, with the cut raised past it, in bounded time
    (a quadratic rule takes minutes here)."""
    monkeypatch.setenv(tblog.SCRUB_MAX_ENV, str(300_000))
    line = WORST[kind][:262_144]
    start = time.perf_counter()
    rules.format(_record(line))
    assert time.perf_counter() - start < 10.0


def test_h79_worst_case_structures_are_rendered_in_bounded_time(rules: tblog.JsonFormatter) -> None:
    deep: Any = "x"
    for _ in range(100_000):
        deep = {"k": deep}
    start = time.perf_counter()
    alike = {f"u{i}.x@example.org": i for i in range(10**5)}  # every key scrubs to [EMAIL]
    rules.format(_record(deep=deep, many=[MAIL] * 10**6, big=b"%40" * 10**6, alike=alike))
    assert time.perf_counter() - start < 5.0


def test_h79_the_bundle_and_the_log_line_decode_with_one_function() -> None:
    """One source of truth: the support bundle's decoded pass calls the same function the log line does."""
    import inspect

    from tools import bundle_scrub

    src = inspect.getsource(bundle_scrub.Scrubber.decoded)
    assert "decode_then_scrub" in src
    assert not hasattr(bundle_scrub, "_decode") and not hasattr(bundle_scrub, "ENCODED")
    assert "decode_then_scrub" in inspect.getsource(tblog.redact)


def test_h79_an_escaped_surrogate_decodes_to_a_writable_character() -> None:
    """Mutation survivor 7: ``\\ud83d`` alone, or past Unicode, decodes to U+FFFD, so a decoded line (the log's or
    the bundle's) can always be written as UTF-8."""
    for text in ("\\ud83d", "\\udc80x", "\\U00110000", "\\\\ud800"):
        out = decode(text)
        out.encode("utf-8")
        assert "�" in out


@dataclasses.dataclass
class Cfg:
    dbPassword: str  # a camelCase field, as a client library names it
    retries: int = 3


def test_h79_a_dataclass_or_named_tuple_is_walked_by_its_fields(rules: tblog.JsonFormatter) -> None:
    """Mutation survivors 28 and 30: a secret's name as a camelCase field (``dbPassword``) is not found in the
    object's text form; walked by its fields, its value is ``[SECRET]``."""
    Creds = collections.namedtuple("Creds", ["userName", "dbPassword"])
    got = json.loads(rules.format(_record(cfg=Cfg(SECRET), creds=Creds("amy", SECRET), row=Row("x"))))
    assert got["cfg"] == {"dbPassword": "[SECRET]", "retries": 3}
    assert got["creds"] == {"userName": "amy", "dbPassword": "[SECRET]"}
    assert got["row"] == {"note": "x", "count": 1}
