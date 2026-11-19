"""Card H-51 (finding H51-01): the tier record reader never raises; the checker fails loudly, without a traceback.

Each hostile file class that could replace ``models/tiers/<profile>.json``: the reader answers ``malformed`` (or
``no_record``) with fixed words and the file name, never the file's content; ``tools.tier_record check`` refuses the
same file with a clear message and exit 3.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def test_a_directory_or_a_link_loop_is_malformed(tmp_path: Path) -> None:
    (tmp_path / "rtxpro6000.json").mkdir()
    assert tier_value.measured("x", ENV, tmp_path).why == "rtxpro6000.json: not readable (IsADirectoryError)"
    (tmp_path / "rtxpro6000.json").rmdir()
    os.symlink(tmp_path / "rtxpro6000.json", tmp_path / "rtxpro6000.json")
    tv = tier_value.measured("x", ENV, tmp_path)
    assert tv.case == "malformed" and tv.why.startswith("rtxpro6000.json: not readable (")


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
