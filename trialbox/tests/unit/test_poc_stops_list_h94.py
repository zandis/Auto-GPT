"""H-94 (the owner's ruling 7092087958): the Python helper and the one list (``tools/trialbox/stops.py``) and the
doctor's ``poc_stop`` lines. The shell helper, the same rule and the same list, is tested with install.sh
(``test_poc_stops_h94.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from tools.trialbox import doctor, stops

pytestmark = pytest.mark.nodb


def _never(what: str) -> NoReturn:
    raise AssertionError(f"stopped: {what}")


class Stopped(Exception):
    pass


def _stop(what: str) -> NoReturn:
    raise Stopped(what)


def test_on_a_poc_box_the_python_helper_warns_lists_and_returns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / "deploy"
    d.mkdir()
    (d / ".env").write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    stops.stop_or_warn("k", "a guard said no", deploy=d, by="launch.py", stop=_never, skipped="a step")
    assert "launch.py: warning (PoC box, H-94): a guard said no; skipped: a step" in capsys.readouterr().err
    entries, problems = stops.read(d)
    assert not problems and [(e.key, e.what, e.skipped, e.by) for e in entries] == [
        ("k", "a guard said no", "a step", "launch.py")
    ]


@pytest.mark.parametrize("dotenv", [None, "TB_ENV=PRODUCTION\n", "TB_ENV=NONSENSE\n"])
def test_elsewhere_the_python_helper_stops_and_lists_nothing(tmp_path: Path, dotenv: str | None) -> None:
    d = tmp_path / "deploy"
    d.mkdir()
    if dotenv:
        (d / ".env").write_text(dotenv, encoding="utf-8")
    with pytest.raises(Stopped, match="^a guard said no$"):
        stops.stop_or_warn(
            "k", "a guard said no", deploy=d, by="t", stop=_stop, environment="VALIDATION" if dotenv else ""
        )
    assert not (d / stops.LIST).exists()


def test_the_list_holds_no_secret_and_no_upload_path_and_never_follows_a_link(tmp_path: Path) -> None:
    d = tmp_path / "deploy"
    assert stops.append(d, "install.sh/x", "TB_LLM_API_KEY=abc123 POSTGRES_PASSWORD=pw at /srv/uploads/a.csv", by="t")
    text = (d / stops.LIST).read_text(encoding="utf-8")
    assert "abc123" not in text and "pw " not in text and "/uploads/" not in text
    assert "TB_LLM_API_KEY=<hidden>" in text and "<a path under uploads/>" in text
    (d / stops.LIST).unlink()
    (d / stops.LIST).symlink_to(tmp_path / "elsewhere")
    assert not stops.append(d, "install.sh/x", "y", by="t") and not (tmp_path / "elsewhere").exists()


def test_a_hand_made_or_unreadable_list_never_stops_anything(tmp_path: Path) -> None:
    d = tmp_path / "deploy"
    (d / "site").mkdir(parents=True)
    (d / stops.LIST).write_text('not json\n{"key": "install.sh/a", "what": "w", "skipped": "", "at": "t", "by": "b"}\n',
                                encoding="utf-8")  # fmt: skip
    lines = list(stops.doctor_lines(d))
    assert len(lines) == 2 and "install.sh/a" in lines[0][1] and "not entries of the list" in lines[1][1]
    (d / stops.LIST).unlink()
    (d / stops.LIST).mkdir()  # cannot be read as a file
    got = doctor.run(doctor.DoctorInputs(deploy=d), checks=())
    assert [c.status for c in got] == ["WARN"] and "cannot be read" in got[0].detail
    assert doctor.ok(got)


def test_doctor_without_a_box_shows_no_list() -> None:
    assert doctor.poc_stops(doctor.DoctorInputs(), []) == []


# ----------------------------------------------------------------------------------------------- the ratchet


def test_a_byte_that_is_not_utf8_hides_no_other_entry(tmp_path: Path) -> None:
    d = tmp_path / "deploy"
    (d / "site").mkdir(parents=True)
    good = b'{"key": "install.sh/a", "what": "w", "skipped": "", "at": "t", "by": "b"}\n'
    (d / stops.LIST).write_bytes(
        b'{"key": "install.sh/b", "what": "\xff\xfe", "skipped": "", "at": "t", "by": "b"}\n' + good
    )
    entries, problems = stops.read(d)
    assert [e.key for e in entries] == ["install.sh/a", "install.sh/b"] and not problems
