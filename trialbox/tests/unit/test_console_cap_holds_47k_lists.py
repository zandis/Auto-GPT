"""E2E P-06: the console was OOM-killed under the 47,177-candidate study (anon RSS 1.19 GB against the 1,173 MiB cap the
box plan gave it on a 96 GB box); every user got 502 until it restarted. Measured with the console's own pages on a
synthetic 47,177-row candidate list (six criteria a row, as GOUT-301), people opening the job, week, candidates and
week pages at the same moment: the peaks are in the measured-peak table (``site_peaks.json`` ``console_users``). The
console's cap now holds 1.5 times the peak for the number of people the site uses it at once (``TB_SITE_USERS``)."""

from __future__ import annotations

import dataclasses
import math
import re
import shutil
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


# ------------------------------------------------------------------------------------------------ round 2 (review)
def test_the_table_holds_the_measured_console_mapping_whole() -> None:
    """P06-3: a transcription error in any of the three measurements fails here, not only the first."""
    assert {u: row["TB_MEM_CONSOLE"] for u, row in PEOPLE.items()} == {1: 1296, 2: 1719, 4: 3131}


def _env(tmp: Path, text: str) -> Path:
    env = tmp / ".env"
    env.write_text(text, encoding="utf-8")
    return env


def _written(env: Path) -> dict[str, str]:
    return memcaps._parse_env(env.read_text(encoding="utf-8"))


@pytest.mark.parametrize("patients", ["", "TB_SITE_PATIENTS=50000\n"], ids=["no-patient-count", "50k"])
def test_a_memcaps_rerun_sizes_the_console_for_the_sites_users(tmp_path: Path, patients: str) -> None:
    """P06-1: one person to four, then ``memcaps --write``: the console must not stay at what holds one person."""
    four = f"{math.ceil(memcaps.HEADROOM * PEOPLE[4]['TB_MEM_CONSOLE'])}m"
    env = _env(tmp_path, f"TB_ENV=PRODUCTION\n{patients}TB_SITE_USERS=4\n")
    assert memcaps.main(["--env-file", str(env), "--write"]) == 0
    assert _written(env)["TB_MEM_CONSOLE"] == four
    env.write_text(env.read_text(encoding="utf-8").replace("TB_SITE_USERS=4", "TB_SITE_USERS=1"), encoding="utf-8")
    assert memcaps.main(["--env-file", str(env), "--write"]) == 0  # its own value, no longer needed: removed
    assert "TB_MEM_CONSOLE" not in _written(env)


def test_a_console_cap_set_by_hand_is_kept_and_doctor_flags_it_under_the_floor(tmp_path: Path) -> None:
    from tools.trialbox import doctor

    floor = math.ceil(memcaps.HEADROOM * PEOPLE[4]["TB_MEM_CONSOLE"])
    env = _env(tmp_path, "TB_ENV=PRODUCTION\nTB_SITE_USERS=4\nTB_MEM_CONSOLE=1944m\n")
    assert memcaps.main(["--env-file", str(env), "--write"]) == 0
    assert _written(env)["TB_MEM_CONSOLE"] == "1944m"  # by hand: kept
    for extra in ({}, {"TB_SITE_PATIENTS": "50000", "TB_MEM_ADAPTER": "7g", "TB_MEM_LAKE": "6g"}):
        e = {"TB_ENV": "PRODUCTION", "TB_SITE_USERS": "4", **extra}
        c = doctor.check_memory_caps(doctor.DoctorInputs(env={**e, "TB_MEM_CONSOLE": "1944m"}, deploy=ROOT / "deploy"))
        assert c.status == "FAIL" and f"TB_MEM_CONSOLE 1944 MB < {floor} MB" in c.detail, c.detail
        ok = doctor.check_memory_caps(
            doctor.DoctorInputs(env={**e, "TB_MEM_CONSOLE": f"{floor}m"}, deploy=ROOT / "deploy")
        )
        assert "TB_MEM_CONSOLE" not in ok.detail.split(" for ")[0] or ok.status == "PASS", ok.detail  # not flagged


def test_the_console_fits_by_reclaiming_another_measured_services_surplus() -> None:
    """P06-2: the console is short; the lake holds a surplus; the third service has none to give."""
    caps = {"TB_MEM_CONSOLE": 2.0, "TB_MEM_LAKE": 8.0, "TB_MEM_X": 5.0}
    defaults = {"TB_MEM_CONSOLE": 2.0, "TB_MEM_LAKE": 6.0, "TB_MEM_X": 20.0}
    got, said = bp.measured_floors(caps, defaults, {"TB_MEM_CONSOLE": 4.5, "TB_MEM_LAKE": 2.0}, 50_000, [])
    assert got == {"TB_MEM_CONSOLE": 4.5, "TB_MEM_LAKE": 5.5, "TB_MEM_X": 5.0} and said == [], (got, said)


def test_the_plan_hands_the_sites_size_and_people_to_the_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P06-4: ``bp.plan`` over a ``.env`` with both: the adapter's and console's caps and the two emitted settings."""
    from tb_common.box_answers import parse

    from tests.unit.test_site_country import HW, OWNER

    a, problems = parse(OWNER)
    assert a is not None, problems
    for var in ("TB_SITE_PATIENTS", "TB_SITE_USERS"):
        monkeypatch.delenv(var, raising=False)
    deploy = tmp_path / "deploy"
    shutil.copytree(ROOT / "deploy", deploy, ignore=shutil.ignore_patterns(".env"))
    hw = dataclasses.replace(HW, ram_gib=96.0)
    base = bp.plan(a, hw, deploy).env_extra
    assert "TB_SITE_PATIENTS" not in base and "TB_SITE_USERS" not in base
    assert _mib(base["TB_MEM_ORCH"]) < 1.5 * 12053 and _mib(base["TB_MEM_CONSOLE"]) < 1.5 * PEOPLE[4]["TB_MEM_CONSOLE"]
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=100000\nTB_SITE_USERS=4\n", encoding="utf-8")
    env = bp.plan(a, hw, deploy).env_extra
    assert env["TB_SITE_PATIENTS"] == "100000" and env["TB_SITE_USERS"] == "4"
    assert _mib(env["TB_MEM_ADAPTER"]) >= 1.5 * 6769 and _mib(env["TB_MEM_ORCH"]) >= 1.5 * 12053, env
    assert _mib(env["TB_MEM_CONSOLE"]) >= 1.5 * PEOPLE[4]["TB_MEM_CONSOLE"], env["TB_MEM_CONSOLE"]
