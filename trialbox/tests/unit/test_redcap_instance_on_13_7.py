"""RC13-C (D-850): the test-instance tool's never-run steps, as REDCap 13.7 needed them.

The owner's REDCap 13.7.23 package, run privately and offline in lane E's container (D-1021; synthetic projects only),
showed where ``tools/redcap_instance`` (written before any REDCap ran) did not fit a real REDCap:

* the package is an upgrade zip (the version folder only, with its own installer): the tool refused it;
* the dictionary import reads columns by position: short rows were refused;
* a new data access group must be sent with an empty unique name: named ones were refused;
* users made through the API have no instrument, export or logging rights: R1 to R9 then could not read;
* the import recalculates only the calculations driven by the first row's fields, and none driven by a checkbox:
  R6's single batch compared stale values.

Nothing of REDCap's is in these tests: the archives are written here."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from tests import edc_kit as k
from tools import redcap_instance as ri

VERSION = "99.9.9"


def _upgrade(path: Path, prefix: str = "redcap/") -> Path:
    base = f"{prefix}redcap_v{VERSION}/"
    with zipfile.ZipFile(path, "w") as z:
        for name in ("install.php", "API/index.php", "Surveys/index.php", "Resources/sql/install.sql",
                     "Resources/sql/install_data.sql"):  # fmt: skip
            z.writestr(base + name, "-- stand-in\n")
        z.writestr("Upgrade Instructions.txt", "read me\n")  # the release's own notes, at the top of the zip
    return path


def test_an_upgrade_zip_with_its_installer_is_taken_and_the_tool_writes_its_own_entry_points(tmp_path: Path) -> None:
    info = ri.inspect_zip(_upgrade(tmp_path / "u.zip"))
    assert info["version"] == VERSION and info["full"] is False
    ri.unpack(tmp_path / "u.zip", tmp_path / "www")
    ri.entry_points(tmp_path / "www", info)
    root = tmp_path / "www" / "redcap"
    assert f"redcap_v{VERSION}/API/index.php" in (root / "api" / "index.php").read_text()
    assert f"redcap_v{VERSION}/Surveys/index.php" in (root / "surveys" / "index.php").read_text()
    assert (root / "temp").is_dir() and (root / "edocs").is_dir()
    assert not (tmp_path / "www" / "Upgrade Instructions.txt").exists()  # a top-level text is never unpacked


def test_an_upgrade_zip_outside_the_redcap_folder_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ri.ZipRefused):
        ri.inspect_zip(_upgrade(tmp_path / "u.zip", prefix=""))


def _built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    admin = ri.RealAdmin(tmp_path)
    admin.cfg = {"port": 8791, "password": "x", "salt": "y"}
    calls: list[dict[str, str]] = []

    def post(data: dict[str, str]) -> tuple[int, str]:
        calls.append(data)
        if data["content"] == "project" and "data" in data:
            return 200, ("1" if "conformance" in data["data"] else "2") * 32
        if data["content"] == "project":
            return 200, json.dumps({"project_id": 14 if data["token"] == "1" * 32 else 15})
        return 200, json.dumps("13.7.23" if data["content"] == "version" else [])

    monkeypatch.setattr(admin, "post", lambda: post)
    monkeypatch.setattr(admin, "sql", lambda statement: "")
    admin.build()
    return calls


def test_every_dictionary_row_is_sent_with_redcaps_18_columns_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for c in (c for c in _built(tmp_path, monkeypatch) if c["content"] == "metadata"):
        assert all(list(r) == list(ri.DICTIONARY_COLUMNS) for r in json.loads(c["data"]))
    assert len(ri.DICTIONARY_COLUMNS) == 18 and ri.DICTIONARY_COLUMNS[-1] == "field_annotation"


def test_new_groups_go_without_a_unique_name_and_users_get_their_instrument_rights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _built(tmp_path, monkeypatch)
    dags = json.loads(next(c["data"] for c in calls if c["content"] == "dag"))
    assert [d["unique_group_name"] for d in dags] == ["", ""]
    assert [d["data_access_group_name"] for d in dags] == [d["data_access_group_name"] for d in k.CONF_DAGS]
    forms = sorted({str(r["form_name"]) for r in k.CONF_CRF})
    for u in json.loads(next(c["data"] for c in calls if c["content"] == "user")):
        assert sorted(u["forms"]) == forms and sorted(u["forms_export"]) == forms and u["logging"] == 1


def test_r6_imports_each_case_alone_and_leaves_a_checkbox_calculation_to_the_evaluator() -> None:
    admin = ri.SimAdmin()
    inst = admin.build()
    sent: list[int] = []
    post = admin.post()

    def counting(data: dict[str, str]) -> tuple[int, str]:
        if data.get("content") == "record" and "data" in data and data["token"] == inst.tokens["logic"]:
            sent.append(len(json.loads(data["data"])))
        return post(data)

    admin.post = lambda: counting  # type: ignore[method-assign]
    from datetime import date

    got = ri.r6_logic(admin, inst, date(2026, 11, 16))
    assert sent and set(sent) == {1}
    assert any("[cb(2)] + [cb(3)]" in n for n in got["not_run"])
    assert "calc_11" not in [c["field"] for c in got["cases"]]
