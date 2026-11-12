"""Our own REDCap test instance, and the conformance tests R1 to R9 on it (NEW-EDC-0, D-584; plan v7.2 section 2.4).

REDCap is not open source. An institution gets it under the REDCap Consortium licence and may not pass the code on.
So **the release zip comes from the owner** (or the institution's REDCap administrator), once, in the version the
sites run. It is placed at the path of the setting ``TB_REDCAP_ZIP``; the default is
``deploy/site/redcap/redcap.zip``, in a folder the repository ignores. The zip is never committed, never in a bundle,
never in CI, and this tool downloads nothing. Without the zip every command stops and says where to put it.

    python -m tools.redcap_instance check      # read the zip (never unpacked): version, the files an install needs
    python -m tools.redcap_instance up         # unpack, start PHP and MariaDB (loopback only), install REDCap
    python -m tools.redcap_instance project    # the test project, its users, four tokens and a locker
    python -m tools.redcap_instance run        # R1 to R9; writes deploy/site/redcap/conformance-<day>.json
    python -m tools.redcap_instance all        # the four, in order
    python -m tools.redcap_instance run --stand-in   # the dry run: project and R1 to R9 against the simulator

The test project is ``tests/edc_kit.py`` (``CONF_*``): the kit's CRF, the longitudinal and repeating set, and one
checkbox, one ``date_dmy`` and one ``number_1dp`` field. Synthetic data only.

**What has run and what has not.** ``check``, the unpacking, ``database.php``, the project builder and R1 to R9 run
in the unit tests against a stand-in archive and the simulator (``rc_sim``). The install itself (``up``: the
containers, REDCap's own SQL, the rows this tool writes into REDCap's tables for the users, the tokens and the lock)
has **never run**: it needs the zip. Every such step is in :class:`RealAdmin` and says so.

The record of a run holds, for each test, the status and body REDCap gave, what was written, and pass or fail
against the "pass" column of the deep review of 2026-11-12 (``10-redcap-edc.md`` section 8). No token is in it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

ZIP_ENV = "TB_REDCAP_ZIP"
PORT_ENV = "TB_REDCAP_TEST_PORT"
DAY_ENV = "TB_REDCAP_TEST_DAY"
TIMEOUT_ENV = "TB_REDCAP_TEST_TIMEOUT_S"
WORK = ROOT / "deploy" / "site" / "redcap"  # ignored by the repository (deploy/site/*)
DEFAULT_ZIP = WORK / "redcap.zip"
COMPOSE = ROOT / "deploy" / "redcap-test" / "compose.yml"
INSTANCE = "instance.json"  # the instance's address, project ids and tokens: mode 0600, never printed
_VERSION_DIR = re.compile(r"^redcap/redcap_v(\d+\.\d+\.\d+)/$")
# what an install reads from the zip, relative to ``redcap/redcap_v<version>/``
INSTALL_SQL = ("Resources/sql/install.sql", "Resources/sql/install_data.sql")
R8_RECORDS = 1000  # R8 of the review: "1,000 synthetic records; one send"

Post = Callable[[dict[str, str]], tuple[int, str]]


class ZipMissing(RuntimeError):
    """The owner has not supplied the zip yet."""


class ZipRefused(RuntimeError):
    """The file at the path is not a REDCap release zip this tool can install."""


# ----------------------------------------------------------------------------------------------------- the zip
def zip_path() -> Path:
    """Where the zip is expected: ``TB_REDCAP_ZIP``, else the default under the ignored folder."""
    given = (os.environ.get(ZIP_ENV) or "").strip()
    return Path(given).expanduser() if given else DEFAULT_ZIP


def missing_message(path: Path) -> str:
    return (
        f"the REDCap release zip is missing: {path}\n"
        "REDCap is licensed to an institution and is not in this repository, in a bundle or in CI, and this tool\n"
        "downloads nothing. The owner, or the institution's REDCap administrator, downloads the release zip in the\n"
        "version the sites run (REDCap Community site, with the institution's own login) and puts it at\n"
        f"  {path}\n"
        f"or names another path in {ZIP_ENV}. Then run: python -m tools.redcap_instance all"
    )


def inspect_zip(path: Path) -> dict[str, Any]:
    """Read the zip without unpacking it: its version and whether it holds what an install needs. Raises
    :class:`ZipMissing` or :class:`ZipRefused` (a path that leaves the folder, two versions, a missing file)."""
    if not path.is_file():
        raise ZipMissing(missing_message(path))
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise ZipRefused(f"{path} is not a zip file") from exc
    bad = [n for n in names if n.startswith(("/", "\\")) or ".." in Path(n).parts or not n.startswith("redcap/")]
    if bad:
        raise ZipRefused(f"{path}: {len(bad)} entries are outside the folder redcap/ (the first: {bad[0][:60]!r})")
    versions = sorted({m.group(1) for n in names if (m := _VERSION_DIR.match(n))})
    if not versions:  # some archives list no folder entries: read the version off a file path
        versions = sorted({m.group(1) for n in names if (m := re.match(r"^redcap/redcap_v(\d+\.\d+\.\d+)/", n))})
    if len(versions) != 1:
        raise ZipRefused(f"{path}: one folder redcap/redcap_v<version>/ is expected, found {len(versions)}")
    base = f"redcap/redcap_v{versions[0]}/"
    need = ["redcap/database.php", "redcap/install.php", *(base + f for f in INSTALL_SQL)]
    lost = [n for n in need if n not in names]
    if lost:
        raise ZipRefused(f"{path}: not a full install zip, missing {', '.join(lost)}")
    return {"path": str(path), "version": versions[0], "entries": len(names), "base": base}


def unpack(path: Path, dest: Path) -> dict[str, Any]:
    """Unpack the checked zip under ``dest`` (``dest/redcap/...``); the zip's own check comes first."""
    info = inspect_zip(path)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        z.extractall(dest)  # every entry was checked to be under redcap/ with no ``..``
    return info


def database_php(host: str, name: str, user: str, password: str, salt: str) -> str:
    """REDCap's ``database.php`` (the five settings its installer asks for). The password and the salt are made at
    set-up and live only in the ignored folder."""

    def q(v: str) -> str:
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"

    return (
        "<?php\n"
        f"$hostname = {q(host)};\n$db = {q(name)};\n$username = {q(user)};\n$password = {q(password)};\n"
        f"$salt = {q(salt)};\n"
    )


# ---------------------------------------------------------------------------------------------------- the API
def call(post: Post, token: str, content: str, **extra: str) -> tuple[int, Any]:
    """One API call as REDCap is called by ``rc_bridge.client``; the status and the body (JSON when it is JSON)."""
    status, text = post({"token": token, "content": content, "format": "json", "returnFormat": "json", **extra})
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def _data(rows: Any) -> str:
    return json.dumps(rows, ensure_ascii=False)


def import_rows(post: Post, token: str, rows: list[dict[str, str]], **extra: str) -> tuple[int, Any]:
    return call(post, token, "record", type="flat", overwriteBehavior="normal", data=_data(rows), **extra)


def export_rows(post: Post, token: str, **extra: str) -> list[dict[str, Any]]:
    status, body = call(post, token, "record", type="flat", rawOrLabel="raw", **extra)
    return [dict(r) for r in body] if status == 200 and isinstance(body, list) else []


# -------------------------------------------------------------------------------------------- building a project
@dataclass
class Instance:
    """An instance and its conformance project: what ``project`` makes and ``run`` reads."""

    kind: str  # "redcap" or "stand-in"
    version: str = ""
    url: str = ""
    project_id: int = 0
    logic_project_id: int = 0
    tokens: dict[str, str] = field(default_factory=dict)  # full, export_only, dag, expired, logic
    notes: list[str] = field(default_factory=list)  # what the instance cannot do (the stand-in says so here)


class Admin:
    """What the conformance run needs beyond a project token. :class:`SimAdmin` is the stand-in;
    :class:`RealAdmin` is REDCap itself."""

    kind = ""

    def post(self) -> Post:
        raise NotImplementedError

    def build(self) -> Instance:
        raise NotImplementedError

    def lock(self, inst: Instance, record: str, event: str, form: str) -> str:
        """Lock one form of one record as the locker; "" when done, else why not."""
        raise NotImplementedError

    def unlock(self, inst: Instance, record: str, event: str, form: str) -> None:
        raise NotImplementedError

    def set_autonumber(self, inst: Instance, on: bool) -> str:
        raise NotImplementedError

    def log(self, inst: Instance) -> tuple[int, Any]:
        """REDCap's own log of the project's last writes (R9)."""
        return call(self.post(), inst.tokens["full"], "log", logtype="record")


def logic_dictionary() -> list[dict[str, str]]:
    """The second project (R6): the inputs, then one calculated field per expression."""
    from tests import edc_kit as k

    rows = [{"field_name": "record_id", "form_name": "logic", "field_type": "text", "field_label": "Record ID"}]
    for name, validation in k.CONF_LOGIC_INPUTS.items():
        rows.append({"field_name": name, "form_name": "logic", "field_type": "text", "field_label": name,
                     "text_validation_type_or_show_slider_number": validation})  # fmt: skip
    rows.append({"field_name": "cb", "form_name": "logic", "field_type": "checkbox", "field_label": "cb",
                 "select_choices_or_calculations": "1, one | 2, two | 3, three"})  # fmt: skip
    for i, (text, _row) in enumerate(k.CONF_CALC, 1):
        rows.append({"field_name": f"calc_{i:02d}", "form_name": "logic", "field_type": "calc",
                     "field_label": f"calc {i}", "select_choices_or_calculations": text})  # fmt: skip
    for i, (text, _row) in enumerate(k.CONF_BRANCH, 1):
        rows.append({"field_name": f"show_{i:02d}", "form_name": "logic", "field_type": "calc",
                     "field_label": f"branching {i}",
                     "select_choices_or_calculations": f"if({text}, 1, 0)"})  # fmt: skip
    return rows


class SimAdmin(Admin):
    """The stand-in: the simulator in this process. It proves this tool, not REDCap (EDC-001)."""

    kind = "stand-in"

    def __init__(self) -> None:
        from fastapi.testclient import TestClient
        from rc_sim.app import create_app

        self.http = TestClient(create_app())

    def post(self) -> Post:
        def post(data: dict[str, str]) -> tuple[int, str]:
            r = self.http.post("/api/", data=data)
            return r.status_code, r.text

        return post

    def build(self) -> Instance:
        from tests import edc_kit as k

        events = [{"unique_event_name": e["unique_event_name"], "arm_num": e["arm_num"]} for e in k.CONF_EVENTS]
        mapping = [{"unique_event_name": d["unique_event_name"], "form": d["form"]} for d in k.CONF_DESIGNATED]
        main = self.http.post("/sim/projects", json={"title": "TrialBox conformance", "metadata": k.CONF_CRF,
                                                     "events": events, "mapping": mapping,
                                                     "repeating": k.CONF_REPEATING}).json()  # fmt: skip
        logic = self.http.post("/sim/projects", json={"title": "TrialBox logic", "metadata": logic_dictionary()}).json()
        seed = [{f: v for f, v in r.items() if f != "redcap_data_access_group"} for r in k.CONF_SEED]
        self.http.post("/sim/records", json={"project_id": main["project_id"], "records": seed})
        version = self.post()({"token": main["token"], "content": "version", "format": "json"})[1].strip()
        token = str(main["token"])
        return Instance(
            "stand-in", version, "inproc://rc-sim", int(main["project_id"]), int(logic["project_id"]),
            {"full": token, "export_only": token, "dag": token, "expired": token, "logic": str(logic["token"])},
            ["the stand-in has one token per project: no rights, no expiry, no data access group (R4 cannot pass)",
             "the stand-in has no locking (R3 cannot pass)", "the stand-in has no log (R9 cannot pass)"],
        )  # fmt: skip

    def lock(self, inst: Instance, record: str, event: str, form: str) -> str:
        return "the stand-in has no locking"

    def unlock(self, inst: Instance, record: str, event: str, form: str) -> None:
        return None

    def set_autonumber(self, inst: Instance, on: bool) -> str:
        return "the stand-in does not switch auto-numbering"


class RealAdmin(Admin):
    """REDCap itself, in the containers of ``deploy/redcap-test/compose.yml``. **Never run**: it needs the zip.

    What goes through REDCap's API is REDCap's documented API (project creation with a super API token, the
    imports of the dictionary, the arms, events, mappings, repeating instruments, groups and users). What the API
    cannot do goes through SQL on REDCap's own tables, as an administrator would: the super token, the tokens of
    the other users (the API gives a user only their own), auto-numbering, and the lock of a form (R3: "lock form
    baseline of record 1 by hand"). The table and column names are REDCap's as of version 14; ``up`` stops with the
    statement and MariaDB's answer when one does not fit the supplied version."""

    kind = "redcap"

    def __init__(self, work: Path = WORK) -> None:
        self.work = work
        self.cfg = json.loads((work / "db.json").read_text(encoding="utf-8")) if (work / "db.json").exists() else {}

    # -- the containers
    def compose(self, *args: str, stdin: str | None = None) -> str:
        env = {**os.environ, "RC_TEST_WORK": str(self.work), "RC_TEST_PORT": str(self.cfg.get("port", port())),
               "RC_TEST_DB_PASSWORD": str(self.cfg.get("password", ""))}  # fmt: skip
        r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "-p", "tb-redcap-test", *args], env=env,
                           input=stdin, capture_output=True, text=True, check=False)  # fmt: skip
        if r.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args[:3])} failed: {r.stderr.strip()[-2000:]}")
        return r.stdout

    def sql(self, statement: str) -> str:
        """Run SQL in the database container; the password goes through the container's own environment."""
        return self.compose("exec", "-T", "db", "sh", "-c", 'exec mariadb -N -uredcap -p"$MARIADB_PASSWORD" redcap',
                            stdin=statement)  # fmt: skip

    def up(self, zip_file: Path) -> dict[str, Any]:
        info = inspect_zip(zip_file)
        self.work.mkdir(parents=True, exist_ok=True)
        if not self.cfg:
            self.cfg = {"port": port(), "password": secrets.token_urlsafe(24), "salt": secrets.token_hex(16)}
            _private(self.work / "db.json", json.dumps(self.cfg))
        unpack(zip_file, self.work / "www")
        (self.work / "www" / "redcap" / "database.php").write_text(
            database_php("db", "redcap", "redcap", self.cfg["password"], self.cfg["salt"]), encoding="utf-8"
        )
        self.compose("up", "-d", "--wait")
        base = self.work / "www" / info["base"]
        if not self.sql("SHOW TABLES LIKE 'redcap_config'").strip():  # a fresh database: REDCap's own install SQL
            for name in INSTALL_SQL:
                self.sql((base / name).read_text(encoding="utf-8"))
            url = f"http://127.0.0.1:{self.cfg['port']}/redcap/"
            self.sql(
                f"UPDATE redcap_config SET value = '{info['version']}' WHERE field_name = 'redcap_version';\n"
                f"UPDATE redcap_config SET value = '{url}' WHERE field_name = 'redcap_base_url';\n"
                "UPDATE redcap_config SET value = 'none' WHERE field_name = 'auth_meth_global';\n"
                "UPDATE redcap_config SET value = '1' WHERE field_name = 'api_enabled';\n"
                "REPLACE INTO redcap_history_version (`date`, redcap_version) "
                f"VALUES (CURDATE(), '{info['version']}');\n"
            )
        return info

    def post(self) -> Post:
        import httpx

        url = f"http://127.0.0.1:{self.cfg['port']}/redcap/api/"

        def post(data: dict[str, str]) -> tuple[int, str]:
            r = httpx.post(url, data=data, timeout=httpx.Timeout(float(os.environ.get(TIMEOUT_ENV) or 120)))
            return r.status_code, r.text

        return post

    def _must(self, what: str, got: tuple[int, Any]) -> Any:
        if got[0] != 200:
            raise RuntimeError(f"REDCap refused to {what}: {got[0]} {str(got[1])[:500]}")
        return got[1]

    def _project(self, post: Post, super_token: str, title: str, longitudinal: bool) -> str:
        made = self._must(f"create the project {title!r}", call(post, super_token, "project", data=_data(
            [{"project_title": title, "purpose": 0, "is_longitudinal": int(longitudinal),
              "record_autonumbering_enabled": 0}])))  # fmt: skip
        return str(made).strip().strip('"')

    def build(self) -> Instance:
        from tests import edc_kit as k

        post = self.post()
        super_token = secrets.token_hex(32).upper()
        self.sql(f"UPDATE redcap_user_information SET super_user = 1, api_token = '{super_token}' "
                 "WHERE username = 'site_admin';")  # fmt: skip
        main = self._project(post, super_token, "TrialBox conformance", True)
        logic = self._project(post, super_token, "TrialBox logic", False)
        for token, rows in ((main, k.CONF_CRF), (logic, logic_dictionary())):
            self._must("import the data dictionary", call(post, token, "metadata", data=_data(rows)))
        self._must("import the arms", call(post, main, "arm", action="import", override="1", data=_data(k.CONF_ARMS)))
        self._must("import the events", call(post, main, "event", action="import", override="1",
                                             data=_data(k.CONF_EVENTS)))  # fmt: skip
        self._must("map the instruments to the events", call(post, main, "formEventMapping",
                                                             data=_data(k.CONF_DESIGNATED)))  # fmt: skip
        self._must("set the repeating instrument", call(post, main, "repeatingFormsEvents",
                                                        data=_data(k.CONF_REPEATING)))  # fmt: skip
        self._must("import the data access groups", call(post, main, "dag", action="import",
                                                         data=_data(k.CONF_DAGS)))  # fmt: skip
        pid = int(self._must("read the project", call(post, main, "project"))["project_id"])
        logic_pid = int(self._must("read the logic project", call(post, logic, "project"))["project_id"])
        tokens = {"full": main, "logic": logic}
        users = [{k2: v for k2, v in u.items() if k2 != "data_access_group"} for u in k.CONF_USERS.values()]
        names = ", ".join(f"('{u['username']}', '{u['username']}@example.org', 'TrialBox', 'Test')" for u in users)
        self.sql("INSERT IGNORE INTO redcap_user_information (username, user_email, user_firstname, user_lastname) "
                 f"VALUES {names};")  # fmt: skip
        self._must("import the users", call(post, main, "user", data=_data(users)))
        dag_rows = [{"username": u["username"], "redcap_data_access_group": u["data_access_group"]}
                    for u in k.CONF_USERS.values() if u.get("data_access_group")]  # fmt: skip
        self._must("bind a user to a group", call(post, main, "userDagMapping", action="import", data=_data(dag_rows)))
        for key in ("export_only", "dag", "expired"):  # the API gives a user only their own token: an admin's SQL
            tokens[key] = secrets.token_hex(16).upper()
            self.sql(f"UPDATE redcap_user_rights SET api_token = '{tokens[key]}' WHERE project_id = {pid} AND "
                     f"username = '{k.CONF_USERS[key]['username']}';")  # fmt: skip
        self._must("seed the two records", import_rows(post, main, k.CONF_SEED))
        version = str(self._must("read the version", call(post, main, "version"))).strip()
        return Instance("redcap", version, f"http://127.0.0.1:{self.cfg['port']}/redcap/", pid, logic_pid, tokens)

    def _event_id(self, inst: Instance, event: str) -> str:
        name, _, arm = event.rpartition("_arm_")
        return self.sql(
            "SELECT e.event_id FROM redcap_events_metadata e JOIN redcap_events_arms a ON a.arm_id = e.arm_id "
            f"WHERE a.project_id = {inst.project_id} AND a.arm_num = {int(arm)} AND LOWER(e.descrip) = '{name}';"
        ).strip()

    def lock(self, inst: Instance, record: str, event: str, form: str) -> str:
        from tests import edc_kit as k

        eid = self._event_id(inst, event)
        if not eid:
            return f"no event {event} in REDCap's tables"
        self.sql("INSERT INTO redcap_locking_data (project_id, record, event_id, form_name, username, timestamp) "
                 f"VALUES ({inst.project_id}, '{record}', {eid}, '{form}', '{k.CONF_USERS['locker']['username']}', "
                 "NOW());")  # fmt: skip
        return ""

    def unlock(self, inst: Instance, record: str, event: str, form: str) -> None:
        self.sql(f"DELETE FROM redcap_locking_data WHERE project_id = {inst.project_id} AND record = '{record}' "
                 f"AND form_name = '{form}';")  # fmt: skip

    def set_autonumber(self, inst: Instance, on: bool) -> str:
        self.sql(f"UPDATE redcap_projects SET auto_inc_set = {int(on)} WHERE project_id = {inst.project_id};")
        return ""


def port() -> int:
    return int(os.environ.get(PORT_ENV) or 8791)


def _private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(text, encoding="utf-8")


# ----------------------------------------------------------------------------------------------------- R1 to R9
def _said(got: tuple[int, Any]) -> dict[str, Any]:
    return {"status": got[0], "body": got[1]}


def _refused(got: tuple[int, Any]) -> bool:
    return got[0] != 200


def r1_validation(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R1: values REDCap's own validation refuses; whether one bad value refuses the batch whole; and whether
    TrialBox's own check (``forms.problem``) refuses the same five."""
    from datacore import forms

    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["full"]
    fields = {f.name: f for f in forms.read_dictionary(_csv(k.CONF_CRF))}
    cases = [("sex", "9"), ("mh_gout", "maybe"), ("weight", "heavy"), ("brthdat", "115/11/01"), ("temp", "37")]
    out: list[dict[str, Any]] = []
    for name, value in cases:
        got = import_rows(post, tok, [{"record_id": "1", "redcap_event_name": k.CONF_SCREEN1, name: value}])
        ours = forms.problem(fields[name], value)
        out.append({"field": name, "value": value, **_said(got), "redcap_refused": _refused(got),
                    "trialbox_refused": ours is not None, "trialbox_code": (ours or {}).get("code", "")})  # fmt: skip
    batch = import_rows(post, tok, [
        {"record_id": "1", "redcap_event_name": k.CONF_SCREEN1, "weight": "72.5"},
        {"record_id": "2", "redcap_event_name": k.CONF_SCREEN2, "sex": "9"}])  # fmt: skip
    rows = export_rows(post, tok, **{"fields[0]": "record_id", "fields[1]": "weight"})
    wrote_good = any(r.get("record_id") == "1" and r.get("weight") == "72.5" for r in rows)
    # ``temp=37`` on number_1dp: REDCap refuses it, TrialBox accepts it and sends 37.0 (forms.redcap_value)
    agree = all(c["redcap_refused"] and (c["trialbox_refused"] or c["field"] == "temp") for c in out)
    return {"pass": agree and _refused(batch) and not wrote_good, "cases": out,
            "batch": {**_said(batch), "the_good_row_was_written": wrote_good}}  # fmt: skip


def r2_checkbox(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R2: a bare checkbox column is refused; the ``___`` columns go in and come back."""
    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["full"]
    key = {"record_id": "1", "redcap_event_name": k.CONF_SCREEN1}
    bare = import_rows(post, tok, [{**key, "joints": "1,3"}])
    cols = import_rows(post, tok, [{**key, "joints___1": "1", "joints___2": "0", "joints___3": "1"}])
    rows = export_rows(post, tok, **{"records[0]": "1", "fields[0]": "record_id", "fields[1]": "joints"})
    back = {c: v for r in rows for c, v in r.items() if c.startswith("joints")}
    ok = _refused(bare) and not _refused(cols) and back.get("joints___1") == "1" and back.get("joints___3") == "1"
    return {"pass": ok, "bare_column": _said(bare), "three_columns": _said(cols), "exported": back}


def r3_lock(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R3: one locked form of record 1; a send that carries records 1 and 2. What REDCap says and what it wrote.
    (That TrialBox then reports record 1 as refused and writes record 2 is EDC-007's repair, wave 3.)"""
    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["full"]
    why = admin.lock(inst, "1", k.CONF_SCREEN1, "baseline")
    if why:
        return {"pass": False, "not_run": why}
    try:
        both = import_rows(post, tok, [
            {"record_id": "1", "redcap_event_name": k.CONF_SCREEN1, "urate": "8.4"},
            {"record_id": "2", "redcap_event_name": k.CONF_SCREEN2, "urate": "7.1"}])  # fmt: skip
        alone = import_rows(post, tok, [{"record_id": "2", "redcap_event_name": k.CONF_SCREEN2, "urate": "7.1"}])
        rows = export_rows(post, tok, **{"fields[0]": "record_id", "fields[1]": "urate"})
    finally:
        admin.unlock(inst, "1", k.CONF_SCREEN1, "baseline")
    wrote = {str(r.get("record_id")): r.get("urate", "") for r in rows if r.get("urate")}
    return {"pass": _refused(both) and "1" not in wrote and not _refused(alone), "both_records": _said(both),
            "record_2_alone": _said(alone), "urate_written": wrote,
            "one_locked_form_refuses_the_whole_import": (_refused(both) and "2" not in wrote) or None}  # fmt: skip


def r4_rights(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R4: a token without the import right, an expired user, a token bound to another group. Nothing is written."""
    from tests import edc_kit as k

    post = admin.post()
    row1 = {"record_id": "1", "redcap_event_name": k.CONF_SCREEN1, "pt_initials": "AA"}
    row2 = {"record_id": "2", "redcap_event_name": k.CONF_SCREEN2, "pt_initials": "BB"}
    got = {"export_only_imports": import_rows(post, inst.tokens["export_only"], [row1]),
           "expired_user_exports": call(post, inst.tokens["expired"], "record", type="flat"),
           "expired_user_imports": import_rows(post, inst.tokens["expired"], [row1]),
           "dag_user_writes_another_group": import_rows(post, inst.tokens["dag"], [row2])}  # fmt: skip
    rows = export_rows(post, inst.tokens["full"], **{"fields[0]": "record_id", "fields[1]": "pt_initials"})
    wrote = sorted(str(r.get("pt_initials")) for r in rows if r.get("pt_initials"))
    return {"pass": all(_refused(g) for g in got.values()) and not wrote,
            **{name: _said(g) for name, g in got.items()}, "written": wrote}  # fmt: skip


def r5_repeat_and_arms(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R5: rows on two arms and two instances of the repeating instrument go in and come back as they went."""
    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["full"]
    sent = [
        {"record_id": "1", "redcap_event_name": k.CONF_SCREEN1, "redcap_repeat_instrument": "",
         "redcap_repeat_instance": "", "weight": "72.5"},
        {"record_id": "1", "redcap_event_name": k.CONF_WEEK4_1, "redcap_repeat_instrument": "ae",
         "redcap_repeat_instance": "1", "ae_term": "Headache", "ae_serious": "0"},
        {"record_id": "1", "redcap_event_name": k.CONF_WEEK4_1, "redcap_repeat_instrument": "ae",
         "redcap_repeat_instance": "2", "ae_term": "Rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"},
        {"record_id": "2", "redcap_event_name": k.CONF_WEEK4_2, "redcap_repeat_instrument": "ae",
         "redcap_repeat_instance": "1", "ae_term": "Nausea", "ae_serious": "0"},
    ]  # fmt: skip
    got = import_rows(post, tok, sent)
    wrong_arm = import_rows(post, tok, [{"record_id": "1", "redcap_event_name": k.CONF_WEEK4_2,
                                         "redcap_repeat_instrument": "ae", "redcap_repeat_instance": "1",
                                         "ae_term": "wrong arm"}])  # fmt: skip
    rows = export_rows(post, tok)

    def at(r: dict[str, Any]) -> tuple[str, str, str, str]:
        return (str(r.get("record_id")), str(r.get("redcap_event_name")), str(r.get("redcap_repeat_instrument") or ""),
                str(r.get("redcap_repeat_instance") or ""))  # fmt: skip

    back = {at(r): r for r in rows}
    lost = [list(at(s)) for s in sent if any(str(back.get(at(s), {}).get(f, "")) != v
                                             for f, v in s.items() if not f.startswith("redcap_"))]  # fmt: skip
    return {"pass": not _refused(got) and not lost, "import": _said(got), "rows_not_read_back_equal": lost,
            "a_row_on_the_other_arm": _said(wrong_arm), "rows_exported": len(rows)}  # fmt: skip


def r6_logic(admin: Admin, inst: Instance, today: date) -> dict[str, Any]:
    """R6: each expression as REDCap computes it, beside TrialBox's evaluator. Any difference keeps
    ``erase_hidden`` off (plan 2.4)."""
    from edc import logic

    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["logic"]

    def look(row: dict[str, str]) -> logic.Lookup:
        def lookup(event: str | None, name: str, code: str | None, instance: int | None) -> str:
            value = row.get(name, "")
            return ("1" if code in value.split(",") else "0") if code else value

        return lookup

    cases = [(f"calc_{i:02d}", text, row, text) for i, (text, row) in enumerate(k.CONF_CALC, 1)]
    cases += [(f"show_{i:02d}", text, row, f"if({text}, 1, 0)") for i, (text, row) in enumerate(k.CONF_BRANCH, 1)]
    rows: list[dict[str, str]] = []
    for n, (_name, _text, row, _expr) in enumerate(cases, 1):
        flat = {"record_id": str(n)}
        for f, v in row.items():
            if f == "cb":
                flat.update({f"cb___{c}": "1" if c in v.split(",") else "0" for c in ("1", "2", "3")})
            else:
                flat[f] = v
        rows.append(flat)
    got = import_rows(post, tok, rows)
    back = {str(r.get("record_id")): r for r in export_rows(post, tok)}
    out: list[dict[str, Any]] = []
    for n, (name, text, row, expr) in enumerate(cases, 1):
        try:
            ours = logic.calculate(expr, look(row), today)
        except logic.LogicError as exc:
            ours = f"(TrialBox cannot read it: {exc})"
        theirs = str(back.get(str(n), {}).get(name, ""))
        out.append({"field": name, "expression": text, "row": row, "redcap": theirs, "trialbox": ours,
                    "equal": theirs == ours or logic.same_number(theirs, ours)})  # fmt: skip
    differ = [c["field"] for c in out if not c["equal"]]
    return {"pass": not _refused(got) and not differ, "import": _said(got), "differ": differ, "cases": out,
            "not_run": ["[baseline_arm_1][w] - [w] (reads another event: the logic project is classic)"]}  # fmt: skip


def r7_auto_number(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R7: ``forceAutoNumber`` with and without a group, and the same screening number sent twice (a forced retry):
    the ids REDCap gives back and how many records then hold that screening number."""
    from tests import edc_kit as k

    post = admin.post()
    note = admin.set_autonumber(inst, True)
    try:
        out: dict[str, Any] = {"auto_numbering_switched": note or "on"}
        for name, tok in (("no_group", inst.tokens["full"]), ("group_bound_token", inst.tokens["dag"])):
            row = {"record_id": "new", "redcap_event_name": k.CONF_SCREEN1, "tb_screening_no": f"S-9{name[:2]}"}
            first = import_rows(post, tok, [row], forceAutoNumber="true", returnContent="auto_ids")
            again = import_rows(post, tok, [row], forceAutoNumber="true", returnContent="auto_ids")
            rows = export_rows(post, inst.tokens["full"], **{"fields[0]": "record_id", "fields[1]": "tb_screening_no"})
            held = sorted(str(r.get("record_id")) for r in rows if r.get("tb_screening_no") == row["tb_screening_no"])
            out[name] = {"first": _said(first), "the_same_row_again": _said(again), "records_with_that_number": held}
    finally:
        admin.set_autonumber(inst, False)
    parsed = all(isinstance(out[n]["first"]["body"], list) and "," in str(out[n]["first"]["body"][:1])
                 for n in ("no_group", "group_bound_token"))  # fmt: skip
    # a retry of a create gives a second record: the link looks the number up before it creates (writeback.py)
    return {"pass": parsed, **out}


def r8_limits(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R8: one import of ``R8_RECORDS`` synthetic records and one export; the seconds each took, and any 429."""
    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["full"]
    rows = [{"record_id": str(10_000 + i), "redcap_event_name": k.CONF_SCREEN1, "tb_screening_no": f"L-{i:04d}",
             "weight": f"{60 + i % 40}.5"} for i in range(R8_RECORDS)]  # fmt: skip
    t0 = time.monotonic()
    got = import_rows(post, tok, rows)
    t1 = time.monotonic()
    back = export_rows(post, tok, **{"fields[0]": "record_id", "fields[1]": "weight"})
    t2 = time.monotonic()
    n = sum(1 for r in back if str(r.get("record_id", "")).startswith("1") and len(str(r.get("record_id"))) == 5)
    return {"pass": not _refused(got) and n == R8_RECORDS, "records": R8_RECORDS,
            "import": {"status": got[0], "seconds": round(t1 - t0, 2)},
            "export": {"rows": len(back), "seconds": round(t2 - t1, 2)}, "rate_limited": got[0] == 429}  # fmt: skip


def r9_log(admin: Admin, inst: Instance) -> dict[str, Any]:
    """R9: what REDCap's own log says about an API write: the user and the words (for the sponsor letter)."""
    from tests import edc_kit as k

    post, tok = admin.post(), inst.tokens["full"]
    import_rows(post, tok, [{"record_id": "1", "redcap_event_name": k.CONF_SCREEN1, "comments": "conformance R9"}])
    got = admin.log(inst)
    entries = got[1][:5] if got[0] == 200 and isinstance(got[1], list) else []
    return {"pass": bool(entries), "status": got[0], "entries": entries,
            **({} if entries else {"body": got[1]})}  # fmt: skip


def _csv(rows: list[dict[str, str]]) -> str:
    import csv
    import io

    cols = sorted({c for r in rows for c in r})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


TESTS: dict[str, Callable[..., dict[str, Any]]] = {
    "R1 validation": r1_validation, "R2 checkbox": r2_checkbox, "R3 lock": r3_lock, "R4 rights": r4_rights,
    "R5 repeat and arms": r5_repeat_and_arms, "R6 logic": r6_logic, "R7 auto-number": r7_auto_number,
    "R8 limits": r8_limits, "R9 log": r9_log,
}  # fmt: skip


def run(admin: Admin, inst: Instance, today: date) -> dict[str, Any]:
    """R1 to R9 in order; one that raises is recorded as failed with the error's type and words, and the run goes
    on. The record never holds a token."""
    results: dict[str, Any] = {}
    for name, test in TESTS.items():
        try:
            results[name] = test(admin, inst, today) if test is r6_logic else test(admin, inst)
        except Exception as exc:
            results[name] = {"pass": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
    record = {"instance": inst.kind, "version": inst.version, "day": today.isoformat(), "project": inst.project_id,
              "notes": inst.notes, "passed": [n for n, r in results.items() if r.get("pass")],
              "failed": [n for n, r in results.items() if not r.get("pass")], "results": results}  # fmt: skip
    text = json.dumps(record, ensure_ascii=False)
    for token in inst.tokens.values():
        if token and token in text:  # a body that echoes a token is cut out, never written
            text = text.replace(token, "<token>")
    return dict(json.loads(text))


# --------------------------------------------------------------------------------------------------- the command
def _load(work: Path) -> Instance:
    path = work / INSTANCE
    if not path.exists():
        raise SystemExit(f"no instance yet ({path}): run `python -m tools.redcap_instance project` first")
    return Instance(**json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("command", choices=("check", "up", "project", "run", "all"))
    ap.add_argument("--stand-in", action="store_true", help="project and run against the simulator (the dry run)")
    ap.add_argument("--work", type=Path, default=WORK, help="the instance's folder (ignored by the repository)")
    ap.add_argument("--out", type=Path, default=None, help="where the record of a run is written")
    args = ap.parse_args(argv)
    today = date.fromisoformat(os.environ.get(DAY_ENV) or date.today().isoformat())
    if args.stand_in:
        if args.command not in ("run", "all", "project"):
            raise SystemExit("--stand-in goes with project, run or all")
        admin: Admin = SimAdmin()
        inst = admin.build()
        print(f"stand-in project built on the simulator (version shown: {inst.version})")
        if args.command == "project":
            return 0
    else:
        try:
            info = inspect_zip(zip_path())
        except (ZipMissing, ZipRefused) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"zip: REDCap {info['version']}, {info['entries']} entries, holds what an install needs")
        if args.command == "check":
            return 0
        real = RealAdmin(args.work)
        admin = real
        if args.command in ("up", "all"):
            real.up(zip_path())
            print(f"REDCap {info['version']} is up on 127.0.0.1:{real.cfg['port']} (loopback only)")
        if args.command == "up":
            return 0
        if args.command in ("project", "all"):
            inst = real.build()
            _private(args.work / INSTANCE, json.dumps(inst.__dict__))
            print(f"project {inst.project_id} built: four tokens and a locker ({args.work / INSTANCE}, not printed)")
        if args.command == "project":
            return 0
        inst = _load(args.work)
    record = run(admin, inst, today)
    out = args.out or (args.work / f"conformance-{today.isoformat()}{'-stand-in' if args.stand_in else ''}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"R1 to R9 on {record['instance']} {record['version']}: {len(record['passed'])} passed, "
          f"{len(record['failed'])} failed ({', '.join(record['failed']) or 'none'})")  # fmt: skip
    print(f"record: {out}")
    return 0 if not record["failed"] or args.stand_in else 1


if __name__ == "__main__":
    raise SystemExit(main())
