"""F0, the framework commit of the system modules: the new settings keys, the doctor hook and the declared page files."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from console import app as console_app
from tb_common.config import DECLARED_SETTINGS, ConfigError, load_settings
from tb_contracts import Settings
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "deploy" / "settings.example.yaml"

#: page files their module still owes. A module's pull request takes its own line out (one unchanged line stands
#: between two entries, so two modules' removals do not touch).
PENDING = {
    # M1
    "console.still_needed",
    # M3
    "console.egress_page",
    # M5
    "console.health_page",
    # M5
    "console.data_step",
    # M5
    "console.support_page",
    # M8
    "console.screen_now",
    # end
}


# ---------------------------------------------------------------------------------------------- settings keys
@pytest.mark.parametrize("key", sorted(DECLARED_SETTINGS))
def test_a_new_key_has_one_default_in_every_place(key: str) -> None:
    section, name = key.split(".")
    default = DECLARED_SETTINGS[key].default
    schema = json.loads((ROOT / "schemas" / "settings.schema.json").read_text(encoding="utf-8"))
    sec = schema["properties"][section]
    assert sec["properties"][name]["default"] == default
    doc = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert doc[section][name] == default
    doc[section] = {}  # a section without the key takes the default
    assert getattr(getattr(Settings.model_validate(doc), section), name) == default
    assert DECLARED_SETTINGS[key].doc


def test_every_key_of_a_declared_section_is_declared() -> None:
    doc = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    for section in {k.split(".")[0] for k in DECLARED_SETTINGS}:
        assert {f"{section}.{n}" for n in doc[section]} == {k for k in DECLARED_SETTINGS if k.startswith(section + ".")}


def _with(tmp_path: Path, terminology: Any) -> Path:
    doc = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    if terminology is None:
        doc.pop("terminology")
    else:
        doc["terminology"] = terminology
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("bad", [
    {"update_time": "before the night"}, {"update_time": "25:00"}, {"update_time": ""}, {"update_time": 3},
    {"update_dir": "packs"}, {"update_dir": None}, {"update_folder": "/packs"}, "nightly",
])  # fmt: skip
def test_an_unknown_value_or_name_stops_the_start(tmp_path: Path, bad: Any) -> None:
    with pytest.raises(ConfigError, match="terminology"):
        load_settings(_with(tmp_path, bad))


def test_a_known_value_loads_and_a_settings_file_of_before_f0_still_does(tmp_path: Path) -> None:
    said = load_settings(_with(tmp_path, {"update_dir": "/srv/packs", "update_time": "01:30"})).terminology
    assert said is not None and (said.update_dir, said.update_time) == ("/srv/packs", "01:30")
    load_settings(_with(tmp_path, None))


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
def test_every_declared_page_file_is_there_or_still_owed() -> None:
    there = {n for n in console_app.MODULE_PAGES if console_app._module_page(n) is not None}
    missing = set(console_app.MODULE_PAGES) - there - PENDING
    assert not missing, f"declared in console.app.MODULE_PAGES and not in this tree: {sorted(missing)}"
    done = PENDING - (set(console_app.MODULE_PAGES) - there)
    assert not done, f"brought or no longer declared: take out of PENDING: {sorted(done)}"


def test_a_declared_page_file_that_is_not_there_is_logged_by_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert console_app._module_page("console.f0_not_there") is None
    assert "console.f0_not_there" in caplog.text


def test_a_page_file_that_is_there_and_does_not_import_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "f0_page.py").write_text("import no_such_package_f0\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ModuleNotFoundError, match="no_such_package_f0"):
        console_app._module_page("f0_page")
    assert all(hasattr(m, "register") for n in console_app.MODULE_PAGES if (m := console_app._module_page(n)))
