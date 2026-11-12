"""D-591: under a chart-number rule with a width, a value wider than the width keeps its leading zeros. Two chart
numbers must never become one pseudonym."""

from __future__ import annotations

import itertools
import random
from pathlib import Path

import pytest
from tb_common import chartno
from tb_common.crypto import pid_for_mrn

KEY = b"k" * 32


@pytest.mark.parametrize(("rule", "value", "want"), [
    ("digits:8", "012345678", "012345678"),      # nine digits: not the eight-digit 12345678
    ("digits:8", "0012345678", "0012345678"),
    ("digits:8", "000000000", "000000000"),      # nine zeros: not the number 0 padded to eight
    ("digits:8", "０１２３４５６７８", "012345678"),  # full width folded, the zeros kept
    ("digits:8", " 012345678 ", "012345678"),
    ("digits:4", "01234", "01234"),
    ("hex:4", "0abcd", "0ABCD"),                 # the case is still the rule's
    ("hex:4:lower", "0ABCD", "0abcd"),
    ("hex:4", "00abcd", "00ABCD"),
    # as before: at or under the width, and with no width
    ("digits:8", "12345678", "12345678"), ("digits:8", "00123456", "00123456"), ("digits:8", "123456", "00123456"),
    ("digits:8", "0", "00000000"), ("digits:8", "00000000", "00000000"), ("digits:4", "123456", "123456"),
    ("digits", "012345678", "12345678"), ("hex", "00ab12", "AB12"), ("hex:6", "ab12", "00AB12"),
])  # fmt: skip
def test_a_value_wider_than_the_width_keeps_its_zeros(rule: str, value: str, want: str) -> None:
    assert chartno.normalise(rule, value) == want
    assert chartno.normalise(rule, want) == want  # idempotent


def test_two_patients_never_share_a_pseudonym_under_a_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(chartno.ENV, "digits:8")
    a, b = pid_for_mrn(KEY, "012345678"), pid_for_mrn(KEY, "12345678")
    assert a != b
    assert pid_for_mrn(KEY, "12345678") == pid_for_mrn(KEY, "１２３４５６７８") == b  # one patient, two spellings
    assert pid_for_mrn(KEY, "00123456") == pid_for_mrn(KEY, "123456")  # the lost zeros of a short one still join


@pytest.mark.parametrize("rule", ["digits:1", "digits:3", "digits:8", "hex:3", "hex:8:lower"])
def test_two_values_become_one_only_when_both_fit_the_width_and_are_one_number(rule: str) -> None:
    """Exhaustive over short strings, random over long ones: the only merge is the declared one (zeros put back
    up to the width)."""
    width = chartno.parse_rule(rule).width or 0
    alphabet = "0123456789" if rule.startswith("digits") else "0123456789abAB"
    rnd = random.Random(7)
    values = ["".join(p) for n in range(1, 5) for p in itertools.product("01a" if "hex" in rule else "012", repeat=n)]
    values += ["".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, width + 3))) for _ in range(3000)]
    seen: dict[str, str] = {}
    for v in values:
        norm = chartno.normalise(rule, v)
        assert chartno.normalise(rule, norm) == norm
        other = seen.setdefault(norm, v)
        if other.lower() != v.lower():  # the case of a hexadecimal key never tells two patients apart
            assert len(v) <= width and len(other) <= width, (rule, v, other)
            assert int(v, 16) == int(other, 16), (rule, v, other)


def test_the_pid_map_refuses_one_pseudonym_for_two_chart_numbers(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.pidmap import PidMap

    monkeypatch.setenv(chartno.ENV, "digits:8")
    pm = PidMap(tmp_path / "pid_map.key", db_url)
    try:
        pid = pid_for_mrn(pm.key, "4242")
        assert pm.upsert_many([(pid, "4242"), (pid, "00004242"), (pid, "４２４２")]) == 1  # one number, three spellings
        with pytest.raises(ValueError, match="one pseudonym for two chart numbers") as exc:
            pm.upsert_many([(pid, "4242"), (pid, "012345678")])
        assert "4242" not in str(exc.value) and "012345678" not in str(exc.value)  # no chart number in the message
        with pytest.raises(ValueError, match="one pseudonym for two chart numbers"):
            pm.stage("2026-11-01", [(pid, "4242"), (pid, "012345678")], [])
        nine = pid_for_mrn(pm.key, "012345678")
        assert pm.upsert_many([(nine, "012345678"), (pid_for_mrn(pm.key, "12345678"), "12345678")]) == 2
        assert pm.resolve(nine) == "012345678"
    finally:
        pm.close()


@pytest.mark.parametrize(("rule", "a", "b", "same"), [
    ("digits:8", "4242", "00004242", True), ("digits:8", "4242", "４２４２", True), ("digits:8", " 4242 ", "4242", True),
    ("digits:8", "012345678", "12345678", False), ("digits:8", "012345678", "0012345678", False),
    ("digits:8", "012345678", "012345678", True), ("digits", "012345678", "12345678", True),
    ("digits:8", "A1", "0A1", False), ("hex:4", "0ab", "AB", True), ("hex:4", "0abcd", "ABCD", False),
    ("hex:4", "0abcd", "0ABCD", True), ("asis", "0042", "42", False), ("asis", "42", " ４２ ", True),
    ("digits:8", "", "0", False),
])  # fmt: skip
def test_same_number_is_decided_without_the_normaliser(rule: str, a: str, b: str, same: bool) -> None:
    assert chartno.same_number(rule, a, b) is same and chartno.same_number(rule, b, a) is same


def test_the_pid_map_check_does_not_trust_the_normaliser(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fault of D-591 put back (a normaliser that strips the zeros of a wide value): the pairs the night
    builds then carry one pseudonym for two chart numbers, and the pid map must refuse them."""
    from adapter import pidmap
    from adapter.pidmap import PidCollision, PidMap

    monkeypatch.setenv(chartno.ENV, "digits:8")
    real = chartno.normalise

    def old(rule: object, value: str) -> str:
        text = real("asis", value)
        return (text.lstrip("0") or "0").zfill(8) if text.isdigit() else text

    pm = PidMap(tmp_path / "pid_map.key", db_url)
    try:
        monkeypatch.setattr(chartno, "normalise", old)
        pairs = [(pid_for_mrn(pm.key, raw), raw) for raw in ("012345678", "12345678")]  # as pipeline.py builds them
        assert pairs[0][0] == pairs[1][0]  # the fault is back
        with pytest.raises(PidCollision):
            pm.upsert_many(pairs)
        with pytest.raises(PidCollision):
            pm.stage("2026-11-01", pairs, [])
        assert issubclass(PidCollision, ValueError) and pidmap._one_per_pid(pairs[:1]) == pairs[:1]
    finally:
        pm.close()
