"""F0, the framework commit of the system modules: the new settings keys, the doctor hook and the declared page files."""

from __future__ import annotations

import importlib
import logging
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from console import app as console_app
from tb_common.config import DECLARED, ConfigError, load_env

from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "deploy" / "settings.example.yaml"
KEYS = {"TB_TERMINOLOGY_UPDATE_DIR", "TB_TERMINOLOGY_STICK", "TB_TERMINOLOGY_NIGHT", "TB_VENDOR_KEYS"}

#: page files their module still owes. A module's pull request takes its own line out (one unchanged line stands
#: between two entries, so two modules' removals do not touch).
PENDING: frozenset[str] = frozenset({"support_page"})  # M1, M3, M8 and the other M5 pages have brought theirs


# ---------------------------------------------------------------------------------------------- settings keys
def test_a_new_key_has_one_default_and_one_meaning_in_both_places() -> None:
    said = dict(re.findall(r"^#   (TB_\w+)=(.*)$", EXAMPLE.read_text(encoding="utf-8"), re.MULTILINE))
    assert set(said) == KEYS
    for key, line in said.items():
        default, meaning = re.split(r"\s{2,}", line, maxsplit=1)
        assert (default, meaning) == (DECLARED[key].default, DECLARED[key].doc)


@pytest.mark.parametrize(("key", "bad"), [
    ("TB_TERMINOLOGY_UPDATE_DIR", "packs"), ("TB_TERMINOLOGY_STICK", "/media/a:b"), ("TB_VENDOR_KEYS", "keys"),
    ("TB_TERMINOLOGY_NIGHT", "before the night"), ("TB_TERMINOLOGY_NIGHT", "25:00-05:00"),
    ("TB_TERMINOLOGY_NIGHT", "22:00"),
])  # fmt: skip
def test_an_unknown_value_stops_the_start(tmp_path: Path, key: str, bad: str) -> None:
    with pytest.raises(ConfigError, match=key):
        load_env(tmp_path / "none", {"TB_TZ": "Asia/Taipei", key: bad})


@pytest.mark.parametrize("env", [
    {}, {k: "" for k in ("TB_TERMINOLOGY_UPDATE_DIR", "TB_TERMINOLOGY_STICK", "TB_TERMINOLOGY_NIGHT", "TB_VENDOR_KEYS")},
    {"TB_TERMINOLOGY_UPDATE_DIR": "/srv/packs", "TB_TERMINOLOGY_STICK": "/media/a:/media/b", "TB_VENDOR_KEYS": "/keys",
     "TB_TERMINOLOGY_NIGHT": "22:00-05:30"},
    {"TB_VENDOR_KEYS": "deploy/keys", "TB_TERMINOLOGY_STICK": "/media/a /media/b"},
])  # fmt: skip
def test_a_known_value_loads(tmp_path: Path, env: dict[str, str]) -> None:
    load_env(tmp_path / "none", {"TB_TZ": "Asia/Taipei", **env})


# ------------------------------------------------------------------------------------------------ doctor hook
TOP = [doctor.Check("topology", "PASS", "A")]


def _brought(monkeypatch: pytest.MonkeyPatch, **files: dict[str, Any]) -> None:
    """The modules' check files as if their module had brought them."""
    found = {}
    for short, members in files.items():
        mod = ModuleType(f"tools.trialbox.{short}")
        mod.__dict__.update(members)
        found[mod.__name__] = mod
    monkeypatch.setattr(doctor, "_module", found.get)


def test_an_empty_list_and_files_not_there_add_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _brought(monkeypatch)
    assert doctor.host_profile(doctor.DoctorInputs(), TOP) == TOP
    monkeypatch.setattr(doctor, "MODULE_CHECKS", ())
    assert doctor.host_profile(doctor.DoctorInputs(), TOP) == TOP


def test_a_file_that_is_not_there_is_not_an_error() -> None:
    assert doctor._module("tools.trialbox.doctor_m10") is None
    assert len(set(doctor.MODULE_CHECKS)) == 9


def test_the_rows_come_in_the_declared_order_after_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    _brought(
        monkeypatch,
        doctor_m9={"doctor_checks": lambda inp: [("profile", "PASS", inp.env["TB_ENV"])]},
        doctor_m3={"doctor_checks": lambda inp: [("egress_mail", "WARN", "cannot look: no relay"),
                                                 ("egress_bundle", "FAIL", "refusing")]},
    )  # fmt: skip
    out = doctor.host_profile(doctor.DoctorInputs(env={"TB_ENV": "DEV"}), TOP)
    assert [(c.name, c.status, c.detail) for c in out[1:]] == [
        ("egress_mail", "WARN", "cannot look: no relay"), ("egress_bundle", "FAIL", "refusing"),
        ("profile", "PASS", "DEV"),
    ]  # fmt: skip
    assert out[0] == TOP[0]


def test_a_broken_check_is_a_fail_in_its_own_words_and_hides_no_other(monkeypatch: pytest.MonkeyPatch) -> None:
    def half(inp: doctor.DoctorInputs) -> Any:
        yield ("egress_mail", "PASS", "ruled")
        raise RuntimeError("the rule file is gone")

    _brought(
        monkeypatch,
        doctor_m1={"doctor_checks": lambda inp: [("seed", "SKIP", "not looked")]},
        doctor_m3={"doctor_checks": half},
        doctor_m4={"doctor_checks": lambda inp: [("topology", "PASS", "mine")]},
        doctor_m6={"doctor_checks": lambda inp: None},
        doctor_m9={"doctor_checks": lambda inp: [("profile", "PASS", "96")]},
    )
    out = {c.name: c for c in doctor.host_profile(doctor.DoctorInputs(), TOP)}
    assert out["topology"] == TOP[0]  # a row never replaces another check's
    assert out["egress_mail"].status == "PASS" and out["profile"].status == "PASS"
    assert "the rule file is gone" in out["doctor_m3"].detail
    assert "SKIP" in out["doctor_m1"].detail and "topology" in out["doctor_m4"].detail
    assert [out[f"doctor_m{n}"].status for n in (1, 3, 4, 6)] == ["FAIL"] * 4


def test_a_file_that_does_not_import_is_a_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "f0_broken.py").write_text("import no_such_package_f0\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(doctor, "MODULE_CHECKS", ("f0_broken", "f0_not_there"))
    (c,) = doctor.module_rows(doctor.DoctorInputs(), [])
    assert (c.name, c.status) == ("f0_broken", "FAIL") and "no_such_package_f0" in c.detail
    sys.modules.pop("f0_broken", None)


def test_a_third_party_package_missing_on_a_host_is_a_warn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "f0_host.py").write_text("import pydantic_not_here_f0\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(doctor, "MODULE_CHECKS", ("f0_host",))
    monkeypatch.setattr(doctor, "_THIRD_PARTY", frozenset({"pydantic_not_here_f0"}))
    monkeypatch.setattr("tools.trialbox.launch.in_box_image", lambda: False)
    (c,) = doctor.module_rows(doctor.DoctorInputs(), [])
    assert (c.name, c.status, c.detail) == ("f0_host", "WARN", "cannot look here: pydantic_not_here_f0")
    monkeypatch.setattr("tools.trialbox.launch.in_box_image", lambda: True)
    (c,) = doctor.module_rows(doctor.DoctorInputs(), [])
    assert (c.name, c.status) == ("f0_host", "FAIL")  # in the box image the same failure is a FAIL
    sys.modules.pop("f0_host", None)


def test_the_rows_are_of_a_whole_run_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _brought(monkeypatch, doctor_m9={"doctor_checks": lambda inp: [("profile", "PASS", "96")]})

    def check_one(inp: doctor.DoctorInputs) -> doctor.Check:
        return doctor.Check("one", "PASS", "")

    assert [c.name for c in doctor.run(doctor.DoctorInputs(), (check_one,))] == ["one"]
    whole = doctor.run(doctor.DoctorInputs(env={"TB_ENV": "DEV"}), (doctor.check_topology, check_one))
    assert [c.name for c in whole] == ["topology", "one", "profile"]


@pytest.mark.parametrize(("module", "name"), [("doctor_m2", "terminology"), ("doctor_m4", "audit_heads")])
def test_a_module_supplies_an_existing_checks_body(monkeypatch: pytest.MonkeyPatch, module: str, name: str) -> None:
    fn = getattr(doctor, f"check_{name}")
    assert fn in doctor.CHECKS and fn.__name__ == f"check_{name}"
    inp = doctor.DoctorInputs(env={"TB_ENV": "DEV"})
    _brought(monkeypatch)
    own = fn.__wrapped__(inp)
    assert fn(inp) == own  # today's body while the module has not brought one
    _brought(monkeypatch, **{module: {f"check_{name}": lambda inp: (name, "WARN", "theirs")}})
    assert fn(inp) == doctor.Check(name, "WARN", "theirs")
    _brought(monkeypatch, **{module: {f"check_{name}": lambda inp: ("backup", "PASS", "theirs")}})
    (c,) = doctor.run(inp, (fn,))
    assert (c.name, c.status) == (name, "FAIL")


# ------------------------------------------------------------------------------------------------ page files
CONSOLE = ROOT / "services" / "console"


def test_every_declared_page_file_is_there_or_still_owed() -> None:
    there = {n for n in console_app.MODULE_PAGES if (CONSOLE / f"{n}.py").is_file()}
    missing = set(console_app.MODULE_PAGES) - there - PENDING
    assert not missing, f"declared in console.app.MODULE_PAGES and not in this tree: {sorted(missing)}"
    done = PENDING - (set(console_app.MODULE_PAGES) - there)
    assert not done, f"brought or no longer declared: take out of PENDING: {sorted(done)}"
    for name in sorted(there):
        assert hasattr(importlib.import_module(f"console.{name}"), "register"), f"{name} has no register()"


def test_every_declared_page_file_is_registered_once_before_the_outermost_middleware() -> None:
    text = (CONSOLE / "app.py").read_text(encoding="utf-8")
    for n in console_app.MODULE_PAGES:
        assert text.count(f'if _module_page("{n}"):') == 1
        assert f"from console.{n} import register as {n}\n\n        {n}(app, helpers, raw_env)" in text
    assert text.count("if _module_page(") == len(console_app.MODULE_PAGES)
    assert text.index('_module_page("screen_now")') < text.index("rc1_guard.register(")


def test_a_declared_page_file_that_is_not_there_is_logged_by_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert console_app._module_page("f0_not_there") is False
    assert "f0_not_there" in caplog.text
    assert console_app._module_page("rc1_guard") is True
