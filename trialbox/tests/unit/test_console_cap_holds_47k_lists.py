"""E2E P-06: the console was OOM-killed under the 47,177-candidate study (anon RSS 1.19 GB against the 1,173 MiB cap the
box plan gave it on a 96 GB box); every user got 502 until it restarted. Measured with the console's own pages on a
synthetic 47,177-row candidate list (six criteria a row, as GOUT-301), people opening the job, week, candidates and
week pages at the same moment: the peaks are in the measured-peak table (``site_peaks.json`` ``console_users``). The
console's cap now holds 1.5 times the peak for the number of people the site uses it at once (``TB_SITE_USERS``)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.box import plan as bp
from tools.trialbox import memcaps

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PEOPLE = dict(memcaps.load_users(ROOT / "deploy" / "measured" / memcaps.PEAKS_NAME))


def _mib(v: str) -> int:
    return int(v[:-1])


def test_the_table_holds_the_measured_console_peaks() -> None:
    assert sorted(PEOPLE) == [1, 2, 4]
    assert PEOPLE[1]["TB_MEM_CONSOLE"] == 1296 and PEOPLE[1]["TB_MEM_CONSOLE"] < PEOPLE[2]["TB_MEM_CONSOLE"]


@pytest.mark.parametrize("ram", [94.0, 96.0])
def test_the_walks_box_gives_the_console_room_for_a_47k_study(ram: float) -> None:
    caps, _ = bp.memory_caps(ram, "rtxpro6000", ROOT / "deploy")  # not given: one person at a time
    assert _mib(caps["TB_MEM_CONSOLE"]) >= 1.5 * 1296, caps["TB_MEM_CONSOLE"]  # was 1,117 to 1,195 MiB


def test_the_console_cap_follows_the_people_who_use_it_at_once() -> None:
    two, _ = bp.memory_caps(96, "rtxpro6000", ROOT / "deploy", users=2)
    assert _mib(two["TB_MEM_CONSOLE"]) >= 1.5 * PEOPLE[2]["TB_MEM_CONSOLE"], two["TB_MEM_CONSOLE"]
    three, _ = bp.memory_caps(128, "rtxpro6000", ROOT / "deploy", users=3)  # the nearest larger measured: 4
    assert _mib(three["TB_MEM_CONSOLE"]) >= 1.5 * PEOPLE[4]["TB_MEM_CONSOLE"], three["TB_MEM_CONSOLE"]
    ten, said = bp.memory_caps(128, "rtxpro6000", ROOT / "deploy", users=10)
    assert _mib(ten["TB_MEM_CONSOLE"]) > _mib(three["TB_MEM_CONSOLE"]), ten
    assert any("10 people at once" in n for n in said), said  # above the most measured: said, never silent


def test_the_spark_says_when_its_fixed_console_cap_is_under_the_peak() -> None:
    """Review P06-1: the Spark's caps are its profile's, never derived; the plan says which fall short."""
    assert bp.memory_caps(128, "gb10") == ({}, [])  # one person, 50,000 patients: its caps hold
    caps, said = bp.memory_caps(128, "gb10", users=2)
    assert caps == {} and any("TB_MEM_CONSOLE 2048m < 2579m" in n for n in said), said
    _, big = bp.memory_caps(128, "gb10", patients=100_000)
    assert any("TB_MEM_ADAPTER 6144m <" in n and "TB_MEM_ORCH" in n for n in big), big


def test_the_plan_reads_the_sites_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SITE_USERS", raising=False)
    (tmp_path / ".env").write_text("TB_SITE_USERS=4\n", encoding="utf-8")
    assert bp.site_patients(tmp_path, "TB_SITE_USERS") == 4


def test_the_shipped_console_caps_hold_one_persons_peak() -> None:
    assert memcaps.size_mb(memcaps.compose_default("TB_MEM_CONSOLE")) >= 1.5 * 1296
    gb10 = (ROOT / "deploy" / "docker-compose.gb10.yml").read_text(encoding="utf-8")
    m = re.search(r"^\s*console: \{[^}]*mem_limit: (\w+)\}", gb10, re.M)
    assert m and memcaps.size_mb(m.group(1)) >= 1.5 * 1296, m
