"""INT-M5 line 1: ``trialbox doctor`` on an installed box's host has no false red.

Run on the host (as the runbook and the install type it), doctor read the secrets folder at the containers' path
(``/run/secrets/trialbox``) and the box's database at the compose network's address (``db``): on every installed box
``site_key`` and ``key_custody`` said the folder "is not here", ``flags`` and ``provenance_index`` that the database
did not answer, and ``key_ceremony`` passed without looking. None of them was a fault of the box. Now the host reads
the secrets volume where the engine keeps it (``TB_DOCKER_VOLUMES``, the project's ``tb-secrets``) and asks the box's
database through the box (``compose exec``), as the hold after a restore is read (H-136).

The installed box here is a stand-in: a deploy folder with its ``.env``, the engine's volumes folder with the box's
secrets volume, and a stand-in engine named in the box file (``TB_DOCKER``) that runs the reader's SQL with the real
``psql`` on the test cluster and answers the orchestrator's ``provenance --check``. Synthetic keys and values only.
No test here lists the doctor's rows: the whole run is read, and every row is held to the same rule."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest

KEY = b"synthetic-site-key-int-m5-0123456789abcdef"
SITE = "SYN"
#: what an installed box's doctor said for a place it looked in the wrong way (no fault of the box)
WRONG_PLACE = ("/run/secrets/trialbox", "OperationalError", "did not answer", "cannot read the feature flags")


def _engine(tmp_path: Path, db_url: str, provenance_rc: int = 0) -> Path:
    """The stand-in engine: ``compose exec -T db psql ... -f -`` runs the SQL on this test's schemas; ``compose exec
    -T orchestrator python -m tools.trialbox provenance --check`` answers as an index equal to the chain."""
    from tb_common.db import split_url

    dsn, prefix = split_url(db_url)
    exe = tmp_path / "engine" / "docker"
    exe.parent.mkdir(mode=0o700, parents=True)
    psql = (f"sed -e 's/app\\.flag/{prefix}app.flag/g' -e 's/pidmap\\.site_key/{prefix}pidmap.site_key/g' | "
            f"psql {shlex.quote(dsn)} \"$@\"; exit $?")  # fmt: skip
    exe.write_text(
        "#!/bin/sh\n# synthetic stand-in for the container engine (INT-M5 tests)\n"
        'while [ "$#" -gt 0 ] && [ "$1" != exec ]; do shift; done\n'
        'shift; [ "$1" = -T ] && shift\n'
        'svc="$1"; shift\n'
        'if [ "$svc" = db ]; then\n'
        "  shift  # psql\n"
        '  set -- $(printf "%s\\n" "$@" | sed -e "/^-U$/,+1d" -e "/^-d$/,+1d")\n'
        f"  {psql}\n"
        "fi\n"
        'if [ "$svc" = orchestrator ]; then\n'
        f'  echo "provenance index: equal to the chain"; exit {provenance_rc}\n'
        "fi\n"
        "exit 3\n"
    )
    exe.chmod(0o700)
    return exe


def _installed_box(tmp_path: Path, db_url: str) -> Path:
    """The deploy folder of an installed box (its ``.env`` as install.sh leaves it, its settings) and the engine's
    folder of its volumes, the secrets volume holding the site key."""
    from tb_common.crypto import SITE_KEY_FILE

    deploy = tmp_path / "opt" / "trialbox" / "deploy"
    deploy.mkdir(parents=True)
    volumes = tmp_path / "var-lib-docker-volumes"
    secrets = volumes / "tbm5_tb-secrets" / "_data"
    secrets.mkdir(parents=True, mode=0o700)
    (secrets / SITE_KEY_FILE).write_bytes(KEY)
    env = deploy / ".env"
    env.write_text(
        "TB_ENV=TEST\nCOMPOSE_PROJECT_NAME=tbm5\nCOMPOSE_FILE=docker-compose.yml\n"
        f"TB_DOCKER={_engine(tmp_path, db_url)}\nTB_DOCKER_VOLUMES={volumes}\n"
        "TB_DB_URL=postgresql://trialbox@db:5432/trialbox_wf\n"  # the compose network's address
    )
    env.chmod(0o600)
    return deploy


def _record_pidmap(db_url: str) -> None:
    from tb_common.crypto import key_fingerprint
    from tb_common.db import Database

    with Database.connect(db_url, "pidmap") as db:
        db.execute("CREATE TABLE IF NOT EXISTS site_key (site_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")
        db.execute("INSERT INTO site_key (site_id, fingerprint) VALUES (?, ?)", (SITE, key_fingerprint(KEY)))


def _doctor_on_host(deploy: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from tools.trialbox import doctor

    monkeypatch.delenv("TB_DB_URL", raising=False)  # the caller's address never decides on a box's host
    monkeypatch.delenv("TB_SECRETS_DIR", raising=False)
    inp = doctor.inputs_from(env_file=deploy / ".env", settings=None, routing=None, lake=None)
    inp.settings = {"site": {"id": SITE}}
    inp.in_image = False  # the box's host
    return {c.name: c for c in doctor.run(inp)}


def test_doctor_on_the_box_host_reads_the_box_and_says_no_wrong_place(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common.crypto import key_fingerprint

    deploy = _installed_box(tmp_path, db_url)
    _record_pidmap(db_url)
    rows = _doctor_on_host(deploy, monkeypatch)
    wrong = {n: c.detail for n, c in rows.items() if any(w in c.detail for w in WRONG_PLACE)}
    assert not wrong, wrong  # every row, whichever it is: none looked in a container's place
    site = rows["site_key"]
    assert site.status == "PASS" and key_fingerprint(KEY) in site.detail and "the pid map" in site.detail, site
    assert KEY.decode() not in site.detail
    assert rows["flags"].status == "PASS", rows["flags"]
    assert rows["provenance_index"].status == "PASS", rows["provenance_index"]
    assert "is not here" not in rows["key_custody"].detail, rows["key_custody"]


def test_a_pid_map_of_another_key_is_still_a_fail_read_through_the_box(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common.crypto import SITE_KEY_FILE

    deploy = _installed_box(tmp_path, db_url)
    _record_pidmap(db_url)
    (tmp_path / "var-lib-docker-volumes" / "tbm5_tb-secrets" / "_data" / SITE_KEY_FILE).write_bytes(KEY[::-1])
    site = _doctor_on_host(deploy, monkeypatch)["site_key"]
    assert site.status == "FAIL" and "is not the pid map's" in site.detail, site


def test_a_box_that_does_not_answer_is_said_with_its_cause_never_a_pass(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = _installed_box(tmp_path, db_url)
    broken = tmp_path / "engine" / "docker"
    broken.write_text("#!/bin/sh\necho 'synthetic: the engine is stopped' >&2\nexit 1\n")
    rows = _doctor_on_host(deploy, monkeypatch)
    for name in ("flags", "provenance_index"):
        assert rows[name].status != "PASS" and "the engine is stopped" in rows[name].detail, rows[name]


def test_a_seed_variable_that_disagrees_with_its_flag_is_read_through_the_box(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common.audit import AuditLog
    from tb_common.flags import DECLARED, Flags

    name, d = next((n, d) for n, d in sorted(DECLARED.items()) if d.seed_env and len(d.values) > 1)
    deploy = _installed_box(tmp_path, db_url)
    other = next(v for v in d.values if v != d.default)
    with (deploy / ".env").open("a", encoding="utf-8") as fh:
        fh.write(f"{d.seed_env}={other}\n")
    Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(name, d.default, actor="test", reason="synthetic")
    flags = _doctor_on_host(deploy, monkeypatch)["flags"]
    assert flags.status == "WARN" and "is ignored" in flags.detail and name in flags.detail, flags


def test_review_1534_a_mismatch_of_many_rows_stays_a_fail_however_long_its_list(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 1534 (M1): ``provenance --check`` prints its header first and then one line per differing row; the
    answer was cut to its tail, so with more than a few rows the header went and a real mismatch read as a WARN."""
    deploy = _installed_box(tmp_path, db_url)
    engine = tmp_path / "engine" / "docker"
    rows = "".join(f"  provenance.model_uses line {i:016x} call synthetic-{i}\\n" for i in range(20))
    said = ("provenance index differs from the chain: 20 row(s) missing, 0 extra; the chain wins: run trialbox "
            "provenance --rebuild")  # fmt: skip
    engine.write_text(
        engine.read_text().replace(
            'echo "provenance index: equal to the chain"; exit 0', f"printf '%s\\n' '{said}'; printf '{rows}'; exit 1"
        )
    )
    row = _doctor_on_host(deploy, monkeypatch)["provenance_index"]
    assert row.status == "FAIL" and "differs from the chain" in row.detail, row


def test_review_1534_a_wrong_secrets_folder_is_never_a_pass_of_the_ceremony_on_a_strict_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 1534 (M3): a secrets folder that is not there (a wrong path) read as "no KEK yet", a PASS."""
    from tools.trialbox import doctor

    monkeypatch.delenv("TB_SECRETS_DIR", raising=False)
    gone = tmp_path / "no-such-secrets-folder"
    for env, want in (("PRODUCTION", "WARN"), ("VALIDATION", "WARN"), ("TEST", "PASS")):
        c = doctor.check_key_custody_record(
            doctor.DoctorInputs(env={"TB_ENV": env, "TB_SECRETS_DIR": str(gone)}, deploy=tmp_path)
        )
        assert c.status == want, (env, c)
        if want == "WARN":
            assert str(gone) in c.detail and "not here" in c.detail, c
