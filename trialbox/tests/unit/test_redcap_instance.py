"""NEW-EDC-0 (D-584): our own REDCap test instance, up to "the zip is missing: here is where to put it", and a dry
run against a stand-in archive and the simulator.

The zip is the owner's: no test here holds REDCap's code, downloads anything or starts a container. What these tests
cannot show is REDCap itself (``RealAdmin`` against a real install); the tool's own text says so.
"""

from __future__ import annotations

import json
import subprocess
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests import edc_kit as k
from tools import redcap_instance as ri

ROOT = Path(__file__).resolve().parents[2]
VERSION = "99.9.9"  # no REDCap has this number: the archive below is ours, with nothing of REDCap's in it


def _stand_in(path: Path, version: str = VERSION, extra: dict[str, str] | None = None, drop: str = "") -> Path:
    base = f"redcap/redcap_v{version}/"
    files = {"redcap/database.php": "<?php\n", "redcap/install.php": "<?php\n", "redcap/index.php": "<?php\n",
             base + "Resources/sql/install.sql": "-- stand-in\n", base + "Resources/sql/install_data.sql": "-- x\n",
             **(extra or {})}  # fmt: skip
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            if name != drop:
                z.writestr(name, text)
    return path


# ------------------------------------------------------------------------------------------------------ the zip
def test_without_the_zip_every_command_stops_and_says_where_to_put_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    where = tmp_path / "nowhere" / "redcap.zip"
    monkeypatch.setenv(ri.ZIP_ENV, str(where))
    for command in ("check", "up", "project", "run", "all"):
        assert ri.main([command, "--work", str(tmp_path / "work")]) == 2
        err = capsys.readouterr().err
        assert "the REDCap release zip is missing" in err and str(where) in err and ri.ZIP_ENV in err
        assert "downloads nothing" in err
    assert not (tmp_path / "work").exists()  # nothing was unpacked, started or written


def test_the_default_place_of_the_zip_is_a_folder_the_repository_ignores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ri.ZIP_ENV, raising=False)
    assert ri.zip_path() == ROOT / "deploy/site/redcap/redcap.zip"
    for path in (ri.zip_path(), ri.WORK / ri.INSTANCE, ri.WORK / "www/redcap/index.php", ri.WORK / "db.json",
                 ri.WORK / "conformance-2026-11-12.json"):  # fmt: skip
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path)], check=False)
        assert r.returncode == 0, f"{path} is not ignored"
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "deploy/site"], capture_output=True, text=True,
                             check=True).stdout.split()  # fmt: skip
    assert tracked == ["deploy/site/.gitkeep"]  # no zip, no unpacked file, no token file is ever committed


def test_a_stand_in_archive_is_read_without_unpacking_it(tmp_path: Path) -> None:
    info = ri.inspect_zip(_stand_in(tmp_path / "r.zip"))
    assert info["version"] == VERSION and info["base"] == f"redcap/redcap_v{VERSION}/" and info["entries"] == 5
    assert list(tmp_path.iterdir()) == [tmp_path / "r.zip"]


@pytest.mark.parametrize(
    ("how", "word"),
    [
        ({"extra": {"../evil.php": "x"}}, "outside the folder redcap/"),
        ({"extra": {"redcap/../../evil.php": "x"}}, "outside the folder redcap/"),
        ({"extra": {"/etc/cron.d/x": "x"}}, "outside the folder redcap/"),
        ({"extra": {"other/file.php": "x"}}, "outside the folder redcap/"),
        ({"extra": {"redcap/redcap_v1.2.3/x.php": "x"}}, "found 2"),
        ({"extra": {"redcap/redcap_v1.2.3/": "", "redcap/redcap_v99.9.9.1/x.php": "x"}}, "found 3"),
        ({"version": "99.9.9';--"}, "is expected"),
        ({"drop": f"redcap/redcap_v{VERSION}/Resources/sql/install.sql"}, "missing"),
        ({"drop": "redcap/database.php"}, "missing"),
    ],
)
def test_an_archive_that_is_not_a_full_install_zip_is_refused(tmp_path: Path, how: dict[str, Any], word: str) -> None:
    with pytest.raises(ri.ZipRefused, match=word):
        ri.inspect_zip(_stand_in(tmp_path / "r.zip", **how))
    with pytest.raises(ri.ZipRefused, match=word):
        ri.unpack(tmp_path / "r.zip", tmp_path / "out")
    assert not (tmp_path / "out").exists() and not (tmp_path.parent / "evil.php").exists()


def test_a_file_that_is_not_a_zip_and_an_upgrade_only_zip_are_refused(tmp_path: Path) -> None:
    (tmp_path / "r.zip").write_bytes(b"not a zip")
    with pytest.raises(ri.ZipRefused, match="not a zip file"):
        ri.inspect_zip(tmp_path / "r.zip")
    with zipfile.ZipFile(tmp_path / "u.zip", "w") as z:  # an upgrade zip holds the version folder only
        z.writestr(f"redcap_v{VERSION}/index.php", "<?php\n")
    with pytest.raises(ri.ZipRefused):
        ri.inspect_zip(tmp_path / "u.zip")


def test_unpacking_puts_the_archive_under_the_work_folder_and_database_php_holds_the_five_settings(
    tmp_path: Path,
) -> None:
    info = ri.unpack(_stand_in(tmp_path / "r.zip"), tmp_path / "www")
    assert (tmp_path / "www" / info["base"] / "Resources/sql/install.sql").read_text() == "-- stand-in\n"
    text = ri.database_php("db", "redcap", "redcap", "p'w\\d", "abc")
    assert text.startswith("<?php\n") and "$hostname = 'db';" in text and "$salt = 'abc';" in text
    assert "$password = 'p\\'w\\\\d';" in text  # a quote or a backslash in the password cannot end the string


# ------------------------------------------------------------------------------------------- the test project
def test_the_conformance_project_is_the_kit_plus_the_repeating_set_and_the_three_fields() -> None:
    by_name = {f["field_name"]: f for f in k.CONF_CRF}
    assert {f["field_name"] for f in k.CRF} <= set(by_name)
    assert by_name["joints"]["field_type"] == "checkbox"
    assert by_name["visit_dmy"]["text_validation_type_or_show_slider_number"] == "date_dmy"
    assert by_name["temp"]["text_validation_type_or_show_slider_number"] == "number_1dp"
    assert by_name["bmi"]["field_type"] == "calc" and by_name["ae_sae_reason"]["branching_logic"]
    assert {e["arm_num"] for e in k.CONF_EVENTS} == {1, 2} and len(k.CONF_EVENTS) == 4
    assert {r["form_name"] for r in k.CONF_REPEATING} == {"ae"}
    assert set(k.CONF_USERS) == {"full", "export_only", "dag", "expired", "locker"}
    assert k.CONF_USERS["export_only"]["api_import"] == 0 and k.CONF_USERS["dag"]["data_access_group"] == "site_a"
    assert str(k.CONF_USERS["expired"]["expiration"]) < "2026" and k.CONF_USERS["locker"]["lock_records"] == 1
    assert len(k.CONF_CALC) + len(k.CONF_BRANCH) == 23
    names = [r["field_name"] for r in ri.logic_dictionary()]
    assert len(names) == len(set(names)) and "calc_13" in names and "show_10" in names and "cb" in names


# ------------------------------------------------------------------------------------------------ the dry run
@pytest.fixture(scope="module")
def dry(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("dry") / "record.json"
    assert ri.main(["run", "--stand-in", "--out", str(out)]) == 0
    return {"record": json.loads(out.read_text(encoding="utf-8")), "text": out.read_text(encoding="utf-8")}


def test_one_command_runs_r1_to_r9_against_the_stand_in_and_writes_the_record(dry: dict[str, Any]) -> None:
    rec = dry["record"]
    assert rec["instance"] == "stand-in" and list(rec["results"]) == list(ri.TESTS) and len(ri.TESTS) == 9
    assert [n.split()[0] for n in ri.TESTS] == [f"R{i}" for i in range(1, 10)]
    assert not any("error" in r for r in rec["results"].values()), rec  # no test of the tool broke
    assert sorted(rec["passed"] + rec["failed"]) == sorted(ri.TESTS)


def test_the_stand_in_fails_exactly_where_the_simulator_is_known_to_be_laxer_than_redcap(dry: dict[str, Any]) -> None:
    """EDC-001: the simulator takes values REDCap refuses, takes a bare checkbox column and refuses the ``___``
    columns, has no locking, no rights per token and no log. NEW-EDC-1 makes it as strict; this list then shrinks,
    on purpose."""
    rec = dry["record"]
    assert rec["failed"] == ["R1 validation", "R2 checkbox", "R3 lock", "R4 rights", "R6 logic", "R7 auto-number",
                             "R9 log"]  # fmt: skip
    r1 = {(c["field"], c["value"]): c for c in rec["results"]["R1 validation"]["cases"]}
    lax = [f for (f, _v), c in r1.items() if c["redcap_must_refuse"] and not c["redcap_refused"]]
    assert lax == ["sex", "mh_gout", "weight", "brthdat", "visit_dmy"]  # the simulator took what REDCap refuses
    assert all(r1[k2]["trialbox_refused"] for k2 in r1 if k2[0] in ("sex", "mh_gout", "weight", "brthdat"))
    t37 = r1[("temp", "37")]  # number_1dp: refused as 37, and TrialBox sends 37.0 for it (STD-061)
    assert t37["redcap_refused"] and not t37["trialbox_refused"] and t37["trialbox_sends"] == "37.0"
    assert not r1[("temp", "37.0")]["redcap_refused"] and not r1[("visit_dmy", "2026-11-05")]["redcap_refused"]
    assert rec["results"]["R1 validation"]["batch"]["the_good_row_was_written"] is True  # the lax batch
    assert rec["results"]["R2 checkbox"]["bare_column"]["status"] == 200
    assert rec["results"]["R3 lock"]["not_run"] and rec["notes"]
    assert rec["results"]["R5 repeat and arms"]["rows_not_read_back_equal"] == []
    r6 = rec["results"]["R6 logic"]  # the simulator refuses the ``___`` columns: nothing is compared, no "differ"
    assert r6["not_compared"] and "differ" not in r6 and r6["expressions"] == 23
    r7 = rec["results"]["R7 auto-number"]  # the ids parse, but the stand-in cannot run the two halves
    assert r7["no_group"]["ids_parse"] and len(r7["not_run"]) == 2
    assert len(r7["no_group"]["records_with_that_number_after_a_blind_retry"]) == 2  # why the link looks up first
    r8 = rec["results"]["R8 limits"]
    assert r8["records"] == 1000 and r8["read_back"] == 1000


def test_the_record_holds_no_token(dry: dict[str, Any]) -> None:
    import re

    assert not re.search(r"[0-9A-Fa-f]{32}", dry["text"]) and "<token>" not in dry["text"]
    tokens = {name: "A" * 32 for name in ("full", "export_only", "dag", "expired", "logic")}
    out = ri.run(_Echo(), ri.Instance("stand-in", tokens=tokens), date(2026, 11, 12))
    text = json.dumps(out)  # an instance that echoes the token in every body, in lower case, and a longer one
    assert "<token>" in text and not re.search(r"[0-9A-Fa-f]{32}", text)
    assert ri.scrub(f"x {'ab' * 32} y {'CD' * 16} z") == "x <token> y <token> z"


class _Echo(ri.Admin):
    kind = "echo"

    def post(self) -> ri.Post:
        return lambda data: (400, json.dumps({"error": f"bad token {data['token'].lower()} and {'9f' * 32}"}))

    def lock(self, inst: ri.Instance, record: str, event: str, form: str) -> str:
        return ""

    def unlock(self, inst: ri.Instance, record: str, event: str, form: str) -> None:
        return None

    def set_autonumber(self, inst: ri.Instance, on: bool) -> str:
        return ""


# ------------------------------------------------------------------------- the install path, as far as it can go
def test_the_real_set_up_makes_two_projects_four_tokens_and_a_locker_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``RealAdmin.build`` against an API that answers 200 to everything and a database that records the SQL: the
    order of the calls, who gets a token and that no statement carries a value of ours unquoted. Not REDCap."""
    admin = ri.RealAdmin(tmp_path)
    admin.cfg = {"port": 8791, "password": "x", "salt": "y"}
    sql: list[str] = []
    calls: list[dict[str, str]] = []

    def post(data: dict[str, str]) -> tuple[int, str]:
        calls.append(data)
        if data["content"] == "project" and "data" in data:
            return 200, ("1" if "conformance" in data["data"] else "2") * 32
        if data["content"] == "project":
            return 200, json.dumps({"project_id": 14 if data["token"] == "1" * 32 else 15})
        return 200, json.dumps("16.0.10" if data["content"] == "version" else [])

    monkeypatch.setattr(admin, "post", lambda: post)

    def run_sql(statement: str) -> str:
        sql.append(statement)
        return ""

    monkeypatch.setattr(admin, "sql", run_sql)
    inst = admin.build()
    assert (inst.kind, inst.project_id, inst.logic_project_id) == ("redcap", 14, 15)
    assert set(inst.tokens) == {"full", "export_only", "dag", "expired", "logic"}
    assert len({*inst.tokens.values()}) == 5 and all(len(t) == 32 for t in inst.tokens.values())
    order = [c["content"] for c in calls]
    assert order[:4] == ["project", "project", "metadata", "metadata"]
    assert [c for c in order if c in ("arm", "event", "formEventMapping", "repeatingFormsEvents", "dag", "user",
                                      "userDagMapping")] == ["arm", "event", "formEventMapping",
                                                             "repeatingFormsEvents", "dag", "user", "userDagMapping"]  # fmt: skip
    users = json.loads(next(c["data"] for c in calls if c["content"] == "user"))
    assert {u["username"] for u in users} == {u["username"] for u in k.CONF_USERS.values()}
    assert sum("UPDATE redcap_user_rights SET api_token" in s for s in sql) == 4  # a user's token: an admin's SQL
    assert "tb_full" in "".join(sql) and inst.tokens["full"] != "1" * 32  # not the creator's (a super user's)
    assert "site_admin" in sql[0] and "super_user = 1" in sql[0]
    assert admin.lock(inst, "1", k.CONF_SCREEN1, "baseline") == "no event screening_arm_1 in REDCap's tables"


def test_the_compose_file_is_not_a_box_file_and_listens_on_the_loopback_address_only() -> None:
    assert not list((ROOT / "deploy").glob("docker-compose*redcap*"))  # outside the box's compose set and its sheet
    doc = yaml.safe_load((ROOT / "deploy/redcap-test/compose.yml").read_text(encoding="utf-8"))
    web, db = doc["services"]["web"], doc["services"]["db"]
    assert web["ports"] == ["127.0.0.1:${RC_TEST_PORT:-8791}:80"] and "ports" not in db
    assert any(v.endswith("/www/redcap:/var/www/html/redcap:ro") for v in web["volumes"])  # mounted, never copied
    docker = (ROOT / "deploy/redcap-test/Dockerfile").read_text(encoding="utf-8")
    assert "COPY" not in docker and "ADD" not in docker and "curl" not in docker and "wget" not in docker


def test_the_tool_downloads_nothing() -> None:
    src = (ROOT / "tools/redcap_instance.py").read_text(encoding="utf-8")
    for word in ("urlretrieve", "urlopen", "requests.", "curl", "wget", "projectredcap", "vanderbilt"):
        assert word not in src, word
    assert src.count("httpx.post(") == 1 and "http://127.0.0.1:" in src  # the one address it calls is its own


# ---------------------------------------------------------------- the adversarial review of PR #352 (2026-11-12)
@pytest.mark.parametrize("where", ["deploy/redcap", "tools/redcap-work", "deploy/redcap-test/work"])
def test_a_place_inside_the_repository_that_git_does_not_ignore_is_refused(
    where: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """H1: the host tree packs untracked files of ``deploy/`` and ``tools/``; a zip, an unpacked tree or a token file
    there would travel in a bundle. Only an ignored folder or one outside the repository is taken."""
    inside = ROOT / where
    for argv, env in (
        (["check", "--work", str(inside)], None),
        (["run", "--stand-in", "--out", str(inside / "record.json")], None),
        (["check"], str(inside / "redcap.zip")),
    ):
        if env:
            monkeypatch.setenv(ri.ZIP_ENV, env)
        assert ri.main(argv) == 2
        assert "inside the repository and not ignored" in capsys.readouterr().err
    assert not inside.exists()
    assert ri.not_private(ri.WORK / ri.INSTANCE) == "" and ri.not_private(Path("/tmp/x/redcap.zip")) == ""


class _Strict(ri.Admin):
    """An instance that refuses what REDCap refuses and never answers an export: nothing can be read back."""

    kind = "strict"

    def post(self) -> ri.Post:
        def post(data: dict[str, str]) -> tuple[int, str]:
            if "data" in data:
                return 400, json.dumps({"error": "refused"})
            return 403, json.dumps({"error": "no export right"})

        return post

    def lock(self, inst: ri.Instance, record: str, event: str, form: str) -> str:
        return ""

    def unlock(self, inst: ri.Instance, record: str, event: str, form: str) -> None:
        return None

    def set_autonumber(self, inst: ri.Instance, on: bool) -> str:
        return ""


def test_an_export_that_fails_is_never_read_as_nothing_was_written() -> None:
    """M3: R1, R3 and R4 passed when every import was refused and the export answered 403."""
    tokens = {"full": "1" * 32, "export_only": "2" * 32, "dag": "3" * 32, "expired": "4" * 32, "logic": "5" * 32}
    out = ri.run(_Strict(), ri.Instance("strict", tokens=tokens), date(2026, 11, 12))
    assert out["passed"] == [] and not any("error" in r for r in out["results"].values())
    assert out["results"]["R1 validation"]["batch"]["the_good_row_was_written"] is None
    assert out["results"]["R3 lock"]["export_failed"] and out["results"]["R4 rights"]["records_written"] is None
    assert out["results"]["R6 logic"]["not_compared"]


def test_a_second_run_on_the_same_instance_judges_as_the_first(tmp_path: Path) -> None:
    """M4: R5 wrote the weight R1 looks for, so R1 changed its verdict on a second run."""
    admin = ri.SimAdmin()
    inst = admin.build()
    first = ri.run(admin, inst, date(2026, 11, 12))
    again = ri.run(admin, inst, date(2026, 11, 12))
    assert (first["passed"], first["failed"]) == (again["passed"], again["failed"])
    assert again["results"]["R8 limits"]["read_back"] == 1000
