"""Card H-51 (finding H51-01): the tier record reader never raises; the checker fails loudly, without a traceback.

Each hostile file class that could replace ``models/tiers/<profile>.json``: the reader answers ``malformed`` (or
``no_record``) with fixed words and the file name, never the file's content; ``tools.tier_record check`` refuses the
same file with a clear message and exit 3.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tb_common import tier_value

from tools import tier_record

ROOT = Path(__file__).resolve().parents[2]
ENV = {"TB_PROFILE": "P-PRO6000"}
DEEP = b"[" * 200_000 + b"]" * 200_000
SECRET_WORD = b"plantedcontent"


def _write(d: Path, data: bytes) -> Path:
    p = d / "rtxpro6000.json"
    p.write_bytes(data)
    return p


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (DEEP, "nested too deep to read"),
        (b'{"fields":' * 100_000 + b"1" + b"}" * 100_000, "over 1000000 bytes"),
        (b" " * (tier_value.TIER_RECORD_MAX_BYTES + 1), "over 1000000 bytes"),
        (b"\xff\xfe" + SECRET_WORD, "not UTF-8"),
        (b"{" + SECRET_WORD, "not JSON (JSONDecodeError)"),
        (b'{"fields":{"judge_sequences":{"basis":"measured","value":' + b"9" * 5000 + b"}}}", "not JSON (ValueError)"),
        (b"[1]", "no readable field judge_sequences"),
        (b'{"fields":[1]}', "no readable field judge_sequences"),
        (b'{"fields":{"judge_sequences":{"basis":["measured"]}}}', "no readable field judge_sequences"),
    ],
)
def test_a_hostile_record_is_malformed_with_a_fixed_reason(tmp_path: Path, data: bytes, why: str) -> None:
    _write(tmp_path, data)
    tv = tier_value.measured("judge_sequences", ENV, tmp_path)
    assert (tv.case, tv.why, tv.value) == ("malformed", f"rtxpro6000.json: {why}", None)
    assert SECRET_WORD.decode() not in tv.line(16)


def test_nan_and_bool_are_measured_but_never_a_count(tmp_path: Path) -> None:
    for v in (b"NaN", b"Infinity", b"true", b"-3", b"2.5"):
        _write(tmp_path, b'{"fields":{"judge_sequences":{"basis":"measured","value":%s}}}' % v)
        tv = tier_value.measured("judge_sequences", ENV, tmp_path)
        assert tv.case == "measured" and tier_value.positive_int(tv) is None
        tv.line(16)


def _within_a_second(call: Callable[[], Any]) -> Any:
    """``call()`` in a thread; a call that blocks (a regression to a blocking open) fails here, not the suite."""
    out: list[Any] = []
    t = threading.Thread(target=lambda: out.append(call()), daemon=True)
    t.start()
    t.join(1.0)
    assert not t.is_alive(), "the reader blocked for over a second"
    return out[0]


def _socket_at(at: Path, request: pytest.FixtureRequest) -> None:
    """A UNIX socket reached through ``at``: bound in a short directory, ``at`` a symbolic link to it.

    ``AF_UNIX`` paths are limited to about 104-108 bytes and a CI runner's temporary path can be longer, so the
    socket is bound under a short ``/tmp`` directory (removed by a finalizer); the reader follows the link and meets
    the socket exactly as if it sat at ``at``. Only if even that bind fails for the operating system's path limit is
    the case skipped, with that reason.
    """
    short = Path(tempfile.mkdtemp(prefix="tb", dir="/tmp"))
    request.addfinalizer(lambda: shutil.rmtree(short, ignore_errors=True))
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(str(short / "s"))
    except OSError as e:
        if "too long" in str(e):
            pytest.skip(f"the operating system's AF_UNIX path limit: {e}")
        raise
    finally:
        s.close()
    os.symlink(short / "s", at)


def _special(kind: str, at: Path, request: pytest.FixtureRequest) -> None:
    if kind == "fifo":
        os.mkfifo(at)
    elif kind == "dev_zero_link":
        os.symlink("/dev/zero", at)
    elif kind == "directory":
        at.mkdir()
    elif kind == "link_loop":
        os.symlink(at, at)
    else:
        _socket_at(at, request)


@pytest.mark.parametrize(
    ("kind", "why"),
    [
        ("fifo", "rtxpro6000.json: not a regular file"),
        ("dev_zero_link", "rtxpro6000.json: not a regular file"),  # refused before a byte is read, not by size
        ("directory", "rtxpro6000.json: not a regular file"),
        ("link_loop", "rtxpro6000.json: not readable (OSError)"),
        ("socket", "rtxpro6000.json: not readable (OSError)"),
    ],
)
def test_a_record_that_is_not_a_regular_file_is_malformed_at_once(
    tmp_path: Path, kind: str, why: str, request: pytest.FixtureRequest
) -> None:
    p = tmp_path / "rtxpro6000.json"
    _special(kind, p, request)
    tv = _within_a_second(lambda: tier_value.measured("x", ENV, tmp_path))
    assert (tv.case, tv.why) == ("malformed", why)
    said = _within_a_second(lambda: tier_record.check([p])[p])
    assert said == [f"not readable JSON ({why})"]


def test_a_symlink_to_a_regular_record_still_reads(tmp_path: Path) -> None:
    (tmp_path / "real.json").write_text('{"fields":{"x":{"basis":"measured","value":8}}}')
    os.symlink(tmp_path / "real.json", tmp_path / "rtxpro6000.json")
    assert tier_value.positive_int(tier_value.measured("x", ENV, tmp_path)) == 8


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_a_file_without_permission_is_malformed(tmp_path: Path) -> None:
    _write(tmp_path, b"{}").chmod(0)
    assert tier_value.measured("x", ENV, tmp_path).why == "rtxpro6000.json: not readable (PermissionError)"


def test_a_missing_file_is_no_record(tmp_path: Path) -> None:
    assert tier_value.measured("x", ENV, tmp_path).case == "no_record"


def test_a_long_or_deep_declared_value_gives_a_bounded_line(tmp_path: Path) -> None:
    _write(tmp_path, b'{"fields":{"x":{"basis":"declared","value":' + b"[" * 990 + b"]" * 990 + b"}}}")
    tv = tier_value.measured("x", ENV, tmp_path)
    assert tv.case == "declared" and len(tv.line(16)) < 300


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (DEEP, "not readable JSON (deep.json: nested too deep to read)"),
        (b" " * (tier_value.TIER_RECORD_MAX_BYTES + 1), "not readable JSON (deep.json: over 1000000 bytes)"),
        # parsed, but near the interpreter's limit: TOO_DEEP or the record's own problems, by the caller's stack depth
        (b'{"fields":' + b"[" * 995 + b"]" * 995 + b"}", None),
    ],
)
@pytest.mark.parametrize("cmd", ["check", "summary"])
def test_the_checker_fails_loudly_on_a_hostile_record(tmp_path: Path, data: bytes, said: str | None, cmd: str) -> None:
    p = tmp_path / "deep.json"
    p.write_bytes(data)
    why = tier_record.check([p])[p]
    assert why and (said is None or why[0] == said)
    r = subprocess.run(
        [sys.executable, "tools/tier_record.py", cmd, str(p)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == tier_record.REFUSED
    assert f"tier record: refused: {p}: {said or ''}" in r.stderr and "Traceback" not in r.stderr


def _shipped(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> Path:
    """A copy of a shipped record (rtx5090, all its sources in the repository) with one change, under its own name."""
    rec = json.loads((ROOT / "models/tiers/rtx5090.json").read_text(encoding="utf-8"))
    change(rec)
    p = tmp_path / "rtx5090.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return p


def _run_check(p: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/tier_record.py", "check", str(p)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("const", [float("nan"), float("inf"), float("-inf")])
def test_the_checker_refuses_nan_and_infinity_the_reader_keeps_its_fallback(tmp_path: Path, const: float) -> None:
    def nan(rec: dict[str, Any]) -> None:
        rec["fields"]["judge_sequences"]["value"] = const

    p = _shipped(tmp_path, nan)
    why = tier_record.check([p])[p]
    assert len(why) == 1 and "is not a number (NaN and Infinity are not JSON numbers)" in why[0]
    r = _run_check(p)
    assert r.returncode == tier_record.REFUSED and "complete" not in r.stdout and "Traceback" not in r.stderr
    tv = tier_value.measured("judge_sequences", {"TB_PROFILE": "P-5090"}, tmp_path)
    assert tv.case == "declared" and tier_value.positive_int(tv) is None


@pytest.mark.parametrize(
    ("source", "said"),
    [
        ("deploy/docker-compose.rtx5090.yml:" + "9" * 5000, "are not n, n-m or a list of them"),
        ("deploy/docker-compose.rtx5090.yml:1-" + "9" * 5000, "are not n, n-m or a list of them"),
        ("deploy/docker-compose.rtx5090.yml:999999999", "has "),
        ("x" * 5000 + ":1", "no file"),
        ("deploy/" + "y/" * 3000 + "z:1", "no file"),
        ("a\x00b:1", "no file"),
    ],
)
def test_the_checker_reports_a_hostile_source_as_a_problem(tmp_path: Path, source: str, said: str) -> None:
    def bad(rec: dict[str, Any]) -> None:
        rec["fields"]["judge_sequences"]["source"] = source

    p = _shipped(tmp_path, bad)
    why = tier_record.check([p])[p]
    assert why and said in why[0] and len(why[0]) < 400
    r = _run_check(p)
    assert r.returncode == tier_record.REFUSED and "Traceback" not in r.stderr


def test_summary_survives_a_record_swapped_after_its_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _shipped(tmp_path, lambda rec: None)
    real = tier_record.load
    calls: list[Path] = []

    def swapped(path: Path) -> Any:
        calls.append(path)
        if len(calls) > 1:
            raise tier_value.TierRecordUnreadable(f"{path.name}: over 1000000 bytes")
        return real(path)

    monkeypatch.setattr(tier_record, "load", swapped)
    assert tier_record.main(["summary", str(p)]) == tier_record.REFUSED and len(calls) == 2


def test_the_shipped_records_still_check_complete() -> None:
    r = subprocess.run(
        [sys.executable, "tools/tier_record.py", "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0 and r.stdout.count(": complete") == 2, r.stderr
