"""M1 (D-1280): install with four questions. The question table (4 asked, at most 11 offered, each old question one rule
and one place), the four questions on a terminal and nothing after them, detection from a recorded machine, replay on a
second machine, the stand-ins, the page's answer applied on the host, the site seed, and the passphrase never in a file
or a container's environment. Synthetic values only."""

from __future__ import annotations

import json
import os
import pty
import re
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import box_answers as ba
from tb_common import install_questions as iq
from tb_common import site_needs

from tools import settings_wizard, sign_bundle, site_seed
from tools.box import __main__ as box
from tools.box import ask, detect, needs_apply
from tools.box import plan as bp
from tools.trialbox import finish_check as fc
from tools.trialbox import ops as tb_ops

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
HW: dict[str, Any] = {
    "arch": "x86_64", "cpu_count": 32, "ram_gib": 128, "disk_free_gib": 1800, "tpm": True, "lan": "192.0.2.0/24",
    "hostname": "box1", "host_tz": "Asia/Taipei", "gpu_name": PRO6000, "gpu_mem_gib": 96.0,
    "disks": [{"path": "/dev/sdb", "size_gib": 3726.0, "transport": "sata", "mounted": ""}],
}  # fmt: skip
TYPED = ["zh-TW", "", "it.desk@hospa.test", "王 小明"]


def _hw(**over: Any) -> bp.Hardware:
    return bp.Hardware.from_json({**HW, **over})


def _prompt(replies: list[str]) -> Any:
    left = list(replies)

    def reply(_text: str) -> str:
        if not left:
            raise EOFError
        return left.pop(0)

    reply.left = left  # type: ignore[attr-defined]
    return reply


def _build(p: bp.BoxPlan, deploy: Path, environment: str = "") -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """The plan's files under ``deploy`` and the settings built from its answers, as the installer does both."""
    bp.write(p, deploy, deploy / "site" / "box" / "answers.json")
    return settings_wizard.build(p.wizard_answers, [deploy / "site" / "mapping"], environment=environment)


# ------------------------------------------------------------------------------------------------ the table
def test_four_are_asked_and_at_most_eleven_offered() -> None:
    assert [q.key for q in iq.ASKED] == ["A1", "A2", "A3", "A4"] and len(iq.ASKED) == iq.MAX_ASKED == 4
    assert 0 < len(iq.OFFERED) <= iq.MAX_OFFERED == 11
    assert all(q.default[lg] and q.title[lg] for q in (*iq.ASKED, *iq.OFFERED) for lg in site_needs.LANGS)


def test_each_old_question_has_one_rule_and_one_place() -> None:
    wizard = [key for key, *_ in settings_wizard.QUESTIONS]
    prompts = ["prompt:ctgov", "prompt:tls_hostname", "prompt:sae_office_mailbox", "prompt:start"]
    assert [o.key for o in iq.OLD] == [*wizard, *prompts] and len(iq.OLD) == 57
    places = {"-", "page", *(q.key for q in (*iq.ASKED, *iq.OFFERED))}
    for o in iq.OLD:
        assert o.rule in iq.RULES and o.to in places and o.how, o.key


def test_the_table_lists_default_rule_and_gate_and_every_page_item_once() -> None:
    rows = {r["key"]: r for r in iq.table("en", open_keys={"mail_relay"})}
    assert all(r["default"] and r["rule"] in iq.RULES for r in rows.values())
    assert rows["B6"]["open"] and not rows["B1"]["open"]
    assert site_needs.STEPS["mail_out"]["en"] in rows["B6"]["gate"] and rows["B2"]["gate"] == []
    needs = [k for q in iq.OFFERED for k in q.needs]
    assert len(needs) == len(set(needs)) and set(needs) <= set(site_needs.BY_KEY)
    # what no question offers is asked by its own step or made on the host
    assert set(site_needs.BY_KEY) - set(needs) == {"backup_key", "request_mailbox"}
    assert set(needs_apply.FIELDS) == set(site_needs.BY_KEY) - {"backup_key"}


def test_the_installers_hold_no_prompt_of_their_own() -> None:
    """The only reads from a terminal left in the two scripts are the passphrase's (KEK-INPUT, the same in both)."""
    for name in ("install.sh", "box-install.sh"):
        text = (ROOT / "deploy" / name).read_text(encoding="utf-8")
        kek = text[text.index("# ---- KEK-INPUT functions") : text.index("# ---- end of KEK-INPUT functions")]
        rest = text.replace(kek, "")
        asks = [ln for ln in rest.splitlines() if re.search(r"printf .*; *read -r|read -r ans|read -p", ln)]
        assert not asks, (name, asks)


# ------------------------------------------------------------------------------------------------ the four
def test_four_answers_make_a_complete_install_on_a_box_in_use(tmp_path: Path) -> None:
    prompt = _prompt(TYPED)
    raw = ask.four(_hw(), prompt, env={"LANG": "zh_TW.UTF-8"})
    assert prompt.left == [] and "password" not in json.dumps(raw)
    a, notes = box.owner_answers(raw, ("/dev/sdb",))
    assert (a.language, a.tz, a.country, a.owner.username, a.environment) == (
        "zh-TW", "Asia/Taipei", "tw", "it.desk", "PRODUCTION")  # fmt: skip
    p = bp.plan(a, _hw())
    settings, env, _ = _build(p, tmp_path, "PRODUCTION")  # nothing refused
    assert env["TB_CHARTNO_RULE"] == "asis" and "TB_CHARTNO_RULE_ANSWERED" not in env
    assert env["TB_BACKUP_ALERT_WATCHER"] == "王 小明" and env["TB_SAE_OFFICE_MAILBOX"] == "it.desk@hospa.test"
    assert settings["departments"]["RHEU"] == "風濕免疫科" and not notes
    marked = {"site_name", "chart_number", "data_source", "backup_target", "backup_alarm", "audit_share",
              "office_mailbox"}  # fmt: skip
    assert p.stand_ins == marked
    assert site_needs.read_stand_ins(tmp_path) == (frozenset(marked), [])
    g = site_needs.gate("first_real_run", production=True, env=env, settings=settings, stand_ins=marked)
    assert g.refused  # a box in use: the first real run is refused by name, not the install


@pytest.mark.parametrize("zone", ["Asia/Seoul", "Europe/Paris"])
def test_a_zone_outside_japan_and_taiwan_names_no_country_and_builds(zone: str, tmp_path: Path) -> None:
    raw = ask.four(_hw(host_tz=zone, hostname="BOX-Upper"), _prompt(["en", "", "a@b.test", "A B"]), env={})
    assert "country" not in raw and raw["box_name"] == "box-upper"
    a, _ = box.owner_answers(raw, ())
    _, env, _ = _build(bp.plan(a, _hw()), tmp_path)
    assert env["TB_TZ"] == zone


def test_an_input_that_ends_before_the_administrator_stops_with_nothing_made() -> None:
    with pytest.raises(bp.PlanError, match="nothing was changed"):
        ask.four(_hw(), _prompt(["en", ""]), env={})
    raw = ask.four(
        _hw(), _prompt(["xx", "ja", "Mars/Base", "Asia/Tokyo", "no-mail", "a@b.test", "\tA B", "A B"]), env={}
    )
    assert raw["tz"] == "Asia/Tokyo" and raw["owner_full_name"] == "A B"


def _tree(tmp_path: Path) -> dict[str, Any]:
    from tests.console.test_box_install_rehearsal import _tree

    return _tree(tmp_path)


def _on_a_terminal(
    tmp_path: Path, typed: str, *args: str, tpm: bool = True, tree: dict[str, Any] | None = None
) -> tuple[int, str, str]:
    """``box-install.sh`` with a terminal for its input, which is closed after ``typed``."""
    t = tree or _tree(tmp_path)
    hw = {**HW, "tpm": tpm}
    Path(t["env"]["TB_BOX_HARDWARE"]).write_text(json.dumps(hw), encoding="utf-8")
    main, sub = pty.openpty()
    proc = subprocess.Popen(
        ["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), *args],
        cwd=tmp_path, env={**t["env"], "LANG": "C.UTF-8", "TB_BOX_WSL2": "0"}, stdin=sub, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )  # fmt: skip
    os.close(sub)
    for line in typed.splitlines(keepends=True):
        os.write(main, line.encode("utf-8"))
        time.sleep(0.3)
    os.write(main, b"\x04")  # end of input: whatever asks after the fourth answer gets nothing
    out, end = "", time.monotonic() + 90
    assert proc.stdout is not None
    while time.monotonic() < end and proc.poll() is None:
        if select.select([proc.stdout], [], [], 0.2)[0]:
            out += proc.stdout.readline()
    if proc.poll() is None:
        proc.kill()
    out += proc.stdout.read()
    os.close(main)
    calls = t["calls"].read_text(encoding="utf-8") if t["calls"].exists() else ""
    return proc.wait(), out, calls


def test_no_prompt_after_the_fourth_answer_and_exit_0(tmp_path: Path) -> None:
    rc, out, calls = _on_a_terminal(tmp_path, "en\n\nit@hospa.test\nIT Desk\n", "--environment", "VALIDATION")
    assert rc == 0, out[-3000:]
    assert "install TB_BOX=0" in calls and "--yes" in calls and "--environment VALIDATION" in calls
    assert "Is this the machine" not in out and "One-time code" not in out
    assert "Nothing more is asked" in out and "The certificate: the box's own" in out
    deploy = tmp_path / "box" / "deploy"
    planned = json.loads((deploy / "site" / "box" / "answers.json").read_text(encoding="utf-8"))
    assert planned["env_extra"]["TB_ENV"] == "VALIDATION" and planned["data_source_host_dir"] == bp.SAMPLE_FEED
    kept = deploy / "site" / "box" / "owner.json"
    assert kept.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("how", ["exit 1", "kill -9 0"], ids=["stopped", "killed"])
def test_an_install_cut_off_goes_on_with_the_same_answers_and_asks_nothing(how: str, tmp_path: Path) -> None:
    """Interrupted in the install phase and run again: the answers are kept, nothing is asked, the same settings."""
    t = _tree(tmp_path)
    stub = Path(t["env"]["TB_BOX_INSTALL"])
    good = stub.read_text(encoding="utf-8")
    stub.write_text(f"#!/bin/sh\n{how}\n", encoding="utf-8")
    rc, _, _ = _on_a_terminal(tmp_path, "en\n\nit@hospa.test\nIT Desk\n", "--environment", "VALIDATION", tree=t)
    planned = t["deploy"] / "site" / "box" / "answers.json"
    first = planned.read_bytes()
    assert rc != 0 and not (t["deploy"] / "site" / "box" / "applied").exists()
    stub.write_text(good, encoding="utf-8")
    rc, out, _ = _on_a_terminal(tmp_path, "", "--environment", "VALIDATION", tree=t)
    assert rc == 0, out[-2000:]
    assert "the answers of the earlier run are kept" in out and "1 of 4" not in out
    assert planned.read_bytes() == first


def test_without_a_tpm_the_fourth_is_the_passphrase_and_no_file_holds_it(tmp_path: Path) -> None:
    phrase = "a synthetic long phrase"
    rc, out, calls = _on_a_terminal(
        tmp_path, f"en\n\nit@hospa.test\nIT Desk\n{phrase}\n{phrase}\n", "--environment", "VALIDATION", tpm=False
    )
    assert rc == 0, out[-3000:]
    assert "--kek-passphrase-fd 8" in calls and phrase not in out + calls
    for f in (tmp_path / "box" / "deploy").rglob("*"):
        if f.is_file() and not f.is_symlink():
            assert phrase.encode() not in f.read_bytes(), f


# ------------------------------------------------------------------------------------------------ the passphrase
def test_the_seal_step_gives_a_container_no_passphrase_in_its_environment() -> None:
    text = (ROOT / "deploy" / "hardening" / "seal_keys.sh").read_text(encoding="utf-8")
    given = set(re.findall(r"(?:^|\s)(?:-e|--env)[= ]([A-Za-z_]+)", text))
    assert given and not {v for v in given if "PASSPHRASE" in v}, given
    assert "--env-file" not in text


@pytest.mark.parametrize("name", ["TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE"])
def test_the_wizard_never_writes_a_passphrase_to_env(name: str, tmp_path: Path) -> None:
    a, _ = box.owner_answers(ask.four(_hw(), _prompt(TYPED), env={}), ())
    p = bp.plan(a, _hw())
    _build(p, tmp_path)
    answers, maps = p.wizard_answers, [tmp_path / "site" / "mapping"]
    for extra in ({name: "a synthetic long phrase"}, {name: ""}):
        with pytest.raises(settings_wizard.WizardError, match="never goes in a file"):
            settings_wizard.build({**answers, "env_extra": {**answers["env_extra"], **extra}}, maps)
    _, env, _ = settings_wizard.build({**answers, "kek_passphrase": "a synthetic long phrase"}, maps)
    assert "a synthetic long phrase" not in json.dumps(env) and name not in env


# ------------------------------------------------------------------------------------------------ detection
def test_a_recorded_network_and_disks_give_relay_mailbox_and_storage() -> None:
    mx = detect.mx_hosts("hospa.test IN MX 10 mail.hospa.test.\nhospa.test IN MX 20 mail2.hospa.test\n")
    assert mx == ["mail.hospa.test", "mail2.hospa.test"]
    mounts = detect.shares(
        "/dev/sda1 / ext4 rw 0 0\n//nas1/tb /mnt/tb cifs rw 0 0\nnas2:/audit /mnt/hosp-audit nfs4 rw 0 0\n"
    )
    up = {("mail.hospa.test", 25), ("mail.hospa.test", 993)}
    got = detect.propose(mx=mx, is_open=lambda h, p: (h, p) in up, mounted=mounts)
    assert got == {"smtp_host": "mail.hospa.test", "smtp_port": "25", "imap_host": "mail.hospa.test",
                   "backup_dir": "/mnt/tb", "anchor_dir": "/mnt/hosp-audit"}  # fmt: skip
    disk = [bp.Disk("/dev/sdb", 3726.0, "sata", "/srv/disk2")]
    assert detect.propose(disks=disk) == {"backup_dir": "/srv/disk2"}
    assert detect.propose() == {}  # no relay, no second disk: not found, the default applies


@pytest.mark.parametrize(
    ("values", "rule"),
    [([f"{n:08d}" for n in range(30)], "digits:8"), ([f"{n:06X}" for n in range(0xA0, 0xC0)], "hex:6"),
     ([f"{n:08d}" for n in range(30)] + ["123"], ""), ([f"{n:08d}" for n in range(5)], ""),
     ([f"K-{n:05d}" for n in range(30)], "")],
)  # fmt: skip
def test_the_chart_number_form_is_read_from_the_first_records(values: list[str], rule: str, tmp_path: Path) -> None:
    (tmp_path / "patients.csv").write_text("id_no,MRN\n" + "".join(f"x,{v}\n" for v in values), encoding="utf-8")
    assert detect.propose(charts=detect.chart_numbers(tmp_path)).get("chartno_rule", "") == rule


# ------------------------------------------------------------------------------------------------ replay
def test_the_answers_of_one_install_give_the_same_settings_on_another_machine(tmp_path: Path) -> None:
    raw = {**ask.four(_hw(), _prompt(TYPED), env={}), "site_name": "示範醫院A (synthetic)", "chartno_rule": "digits:8",
           "backup_kind": "second_disk", "backup_disk": "/dev/sdb", "sae_office_mailbox": "office@hospa.test",
           "smtp_host": "mail.hospa.test", "smtp_port": "25", "source": "spreadsheet", "source_dir": "/srv/his"}  # fmt: skip
    out = []
    for name in ("one", "two"):
        d = tmp_path / name
        (d / "site" / "box").mkdir(parents=True)
        (d / "owner-in.json").write_text(json.dumps(raw), encoding="utf-8")
        a, _ = box.owner_answers(json.loads((d / "owner-in.json").read_text()), ("/dev/sdb",))
        box.keep_answers(d, a)
        settings, env, _ = _build(bp.plan(a, _hw()), d)
        out.append((settings, {k: v for k, v in env.items() if k not in box.KEEP}))
        raw = json.loads((d / "site" / "box" / "owner.json").read_text(encoding="utf-8"))  # the replay file
    assert out[0] == out[1]
    assert not {"password", "kek_passphrase", "totp"} & set(raw)


def test_a_replay_on_a_machine_without_the_disk_goes_on_and_says_so() -> None:
    raw = {**ask.four(_hw(), _prompt(TYPED), env={}), "backup_kind": "second_disk", "backup_disk": "/dev/sdb"}
    a, notes = box.owner_answers(raw, ("/dev/nvme9n1",))
    assert a.backup.kind is ba.BackupKind.LATER and "not on this machine" in notes[0]
    assert "backup_target" in ba.stand_ins(a)
    with pytest.raises(bp.PlanError, match="chartno_rule"):  # a malformed answer is still refused
        box.owner_answers({**raw, "chartno_rule": "fax"}, ("/dev/nvme9n1",))


# ------------------------------------------------------------------------------------------------ the gates stay
def test_a_marked_item_leaves_the_install_and_an_unmarked_one_still_stops_it(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    host = fc.Host.from_environ()
    env = {"TB_ENV": "PRODUCTION", "TB_BACKUP_TARGETS": f"{tmp_path}/deploy/backups"}
    before = fc.problems(deploy, env, host)
    assert any("no audit anchor folder" in p for p in before) and any("backup target" in p for p in before)
    site_needs.write_stand_ins(deploy, ["audit_share", "backup_target"])
    assert fc.problems(deploy, env, host) == []
    # a folder that is named and wrong is not a missing one: it still stops
    assert fc.problems(deploy, {**env, "TB_BACKUP_TARGETS": "/not/there"}, host)
    assert fc.problems(deploy, {**env, "TB_AUDIT_ANCHOR_TARGETS": "/not/there"}, host)


def test_the_wizard_still_refuses_a_silent_rule_nobody_marked(tmp_path: Path) -> None:
    a, _ = box.owner_answers(ask.four(_hw(), _prompt(TYPED), env={}), ())
    p = bp.plan(a, _hw())
    _build(p, tmp_path, "PRODUCTION")
    answers, maps = p.wizard_answers, [tmp_path / "site" / "mapping"]
    with pytest.raises(settings_wizard.WizardError, match="chartno_rule is required"):
        settings_wizard.build({**answers, "stand_ins": []}, maps, environment="PRODUCTION")


# ------------------------------------------------------------------------------------------------ the host apply
@pytest.fixture
def installed(tmp_path: Path) -> Path:
    deploy = tmp_path / "deploy"
    a, _ = box.owner_answers({**ask.four(_hw(), _prompt(TYPED), env={}), "environment": "VALIDATION"}, ())
    settings, env, _ = _build(bp.plan(a, _hw()), deploy)
    box.keep_answers(deploy, a)
    settings_wizard.write(settings, env, deploy / "settings.yaml", deploy / ".env")
    (deploy / ".env").write_text((deploy / ".env").read_text() + "TB_NOTE_BY_HAND=kept\n", encoding="utf-8")
    return deploy


GIVEN: dict[str, dict[str, str]] = {
    "site_name": {"site_name": "示範醫院A (synthetic)"},
    "office_mailbox": {"sae_office_mailbox": "office@hospa.test"},
    "mail_relay": {"smtp_host": "mail.hospa.test", "smtp_port": "25"},
    "request_mailbox": {"imap_host": "imap.hospa.test", "mta_authserv_id": "mx.hospa.test"},
    "backup_alarm": {"health_page_person": "山田 花子"},
    "certificate": {"tls_root_confirmed_by": "Lin, IT desk"},
    "chart_number": {"chartno_example": "00123456"},
}


def _open(deploy: Path) -> set[str]:
    env = fc.read_env(deploy / ".env")
    settings = yaml.safe_load((deploy / "settings.yaml").read_text(encoding="utf-8"))
    got = site_needs.still_needed(env=env, settings=settings, stand_ins=site_needs.read_stand_ins(deploy)[0])
    return {n.key for n, _ in got}


@pytest.mark.parametrize("item", sorted(GIVEN))
def test_a_filled_item_reaches_the_settings_leaves_the_list_and_changes_nothing_else(
    item: str, installed: Path
) -> None:
    assert item in _open(installed)
    before_env = fc.read_env(installed / ".env")
    summary, keys = needs_apply.run(installed, {"item": item, **GIVEN[item]}, restart=False, rows=lambda: 0)
    assert item not in _open(installed) and summary == f"filled in: {item}" and keys
    after = fc.read_env(installed / ".env")
    named = set(needs_apply.clean(item, GIVEN[item]).env)
    assert {k: v for k, v in after.items() if k not in named} == {k: v for k, v in before_env.items() if k not in named}
    assert after["TB_NOTE_BY_HAND"] == "kept" and (installed / ".env").stat().st_mode & 0o777 == 0o600
    assert not any(v in summary + " ".join(keys) for v in GIVEN[item].values())  # keys only, never a value
    again = (installed / ".env").read_bytes()
    needs_apply.run(installed, {"item": item, **GIVEN[item]}, restart=False, rows=lambda: 0)
    assert (installed / ".env").read_bytes() == again  # the same answer again: the same state


def test_a_filled_site_name_is_in_the_replay_file_and_the_next_plan_marks_it_no_more(installed: Path) -> None:
    needs_apply.run(installed, {"item": "site_name", **GIVEN["site_name"]}, restart=False)
    a, _ = box.owner_answers(json.loads((installed / "site/box/owner.json").read_text(encoding="utf-8")), ())
    assert a.site_name == "示範醫院A (synthetic)" and "site_name" not in ba.stand_ins(a)


@pytest.mark.parametrize(
    ("item", "given", "code"),
    [("site_name", {"site_name": ba.PLACEHOLDER_NAME}, "required"), ("office_mailbox", {"sae_office_mailbox": "a b"}, "mail"),
     ("mail_relay", {"smtp_host": "mail"}, "host"), ("mail_relay", {"smtp_host": "a.b.test", "smtp_port": "0"}, "port"),
     ("backup_target", {"backup_dir": "/etc"}, "folder"), ("audit_share", {"anchor_dir": "relative"}, "folder"),
     ("chart_number", {"chartno_example": "K-12"}, "chartno"), ("certificate", {"tls_root_confirmed_by": "$(id)"}, "person"),
     ("backup_alarm", {"health_page_person": "A\nTB_ENV=DEV"}, "plain"), ("backup_key", {}, "item"),
     ("data_source", {"source_kind": "fax", "source_dir": "/srv/his"}, "source")],
)  # fmt: skip
def test_an_answer_that_cannot_be_used_is_refused_and_changes_nothing(
    item: str, given: dict[str, str], code: str, installed: Path
) -> None:
    before = {p: p.read_bytes() for p in installed.rglob("*") if p.is_file()}
    with pytest.raises(needs_apply.NeedsError) as e:
        needs_apply.run(installed, {"item": item, **given}, restart=False, rows=lambda: 0)
    assert e.value.code == code
    assert {p: p.read_bytes() for p in installed.rglob("*") if p.is_file()} == before


def test_a_rule_is_not_changed_once_patients_are_loaded_and_a_folder_must_be_there(installed: Path) -> None:
    for given, rows in (({"item": "chart_number", "chartno_example": "00123456"}, 3),
                        ({"item": "data_source", "source_kind": "csv", "source_dir": "/srv/not-there"}, 0)):  # fmt: skip
        with pytest.raises(needs_apply.NeedsError, match="given, but not usable"):
            needs_apply.run(installed, given, restart=False, rows=_rows(rows))
        assert given["item"] in _open(installed)


def test_a_failed_settings_write_leaves_the_file_and_the_item_open(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = (installed / "settings.yaml").read_bytes()
    monkeypatch.setattr(os, "replace", _no_replace)
    with pytest.raises(OSError, match="cut off"):
        needs_apply.run(installed, {"item": "site_name", **GIVEN["site_name"]}, restart=False)
    monkeypatch.undo()
    assert (installed / "settings.yaml").read_bytes() == before and "site_name" in _open(installed)
    needs_apply.run(installed, {"item": "site_name", **GIVEN["site_name"]}, restart=False)  # again: the same end state
    assert "site_name" not in _open(installed)


def _rows(n: int) -> Any:
    return lambda: n


def _no_replace(*_a: Any, **_k: Any) -> None:
    raise OSError("cut off")


def test_the_runner_takes_the_pages_request(installed: Path, tmp_path: Path) -> None:
    ops = tb_ops.OpsDir(tmp_path / "ops")
    rid = ops.submit("site_needs", "admin", {"item": "site_name", **GIVEN["site_name"]})
    done = tb_ops.OpsRunner(tb_ops.Box.local(installed, {}), ops).run_one(
        {"id": rid, "action": "site_needs", "by": "admin", "args": {"item": "site_name", **GIVEN["site_name"]}}
    )
    assert done["ok"] and "site_name" not in _open(installed), done


def test_the_doctor_rows_warn_by_name_and_never_fail(installed: Path) -> None:
    rows = needs_apply.doctor_checks(installed, fc.read_env(installed / ".env"), {})
    assert {r[1] for r in rows} == {"WARN"} and any(r[0] == "still_needed:mail_relay" for r in rows)
    assert all("Information still needed" in r[2] for r in rows)


# ------------------------------------------------------------------------------------------------ the seed
SEED = {"site_name": "示範醫院A (synthetic)", "language": "zh-TW", "tz": "Asia/Taipei", "chartno_rule": "digits:8"}


def test_a_signed_seed_leaves_only_the_person_to_ask(tmp_path: Path) -> None:
    priv, pub = sign_bundle.keygen(tmp_path / "keys")
    f = tmp_path / "site-seed.json"
    f.write_text(json.dumps(SEED, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(site_seed.SeedError, match="missing"):
        site_seed.verify(f, pub)
    sign_bundle.sign_file(priv, f)
    seed = site_seed.verify(f, pub)
    raw = ask.four(_hw(), _prompt(["it@hospa.test", "IT Desk"]), env={}, seed=seed)
    a, _ = box.owner_answers(raw, ())
    assert (a.site_name, a.chartno_rule) == (SEED["site_name"], "digits:8")
    assert not {"site_name", "chart_number"} & ba.stand_ins(a)
    f.write_text(json.dumps({**SEED, "site_name": "another"}), encoding="utf-8")
    with pytest.raises(site_seed.SeedError, match="does not check"):
        site_seed.verify(f, pub)


@pytest.mark.parametrize(
    "bad", [{"owner_email": "a@b.test"}, {"password": "x"}, {"environment": "DEV"}, {"tz": "Mars/B"}]
)
def test_a_seed_holds_the_sites_answers_only(bad: dict[str, str], tmp_path: Path) -> None:
    f = tmp_path / "site-seed.json"
    f.write_text(json.dumps({**SEED, **bad}), encoding="utf-8")
    with pytest.raises(site_seed.SeedError):
        site_seed.answers(f)


def test_the_seed_makes_the_sample_once_and_a_second_run_does_nothing(installed: Path) -> None:
    calls: list[list[str]] = []

    def sh(argv: list[str], text: str | None = None) -> str:
        calls.append(argv)
        return ""

    assert site_seed.run(installed, sh) == ["site", "sample_hospital", "sample_loaded", "sample_study", "sample_list"]
    assert "--sites" in calls[0][-1] and site_seed.STUDY in calls[2][-1] and calls[3][-2:] == ["python", "-"]
    n = len(calls)
    assert site_seed.run(installed, sh) == [] and len(calls) == n


def test_a_seed_cut_off_goes_on_from_there_and_a_box_in_use_gets_no_sample(installed: Path) -> None:
    def stop(argv: list[str], text: str | None = None) -> str:
        if "adapter" in argv:
            raise site_seed.SeedError("cut off")
        return ""

    with pytest.raises(site_seed.SeedError):
        site_seed.run(installed, stop)
    assert site_seed.run(installed, lambda *_a: "") == ["sample_loaded", "sample_study", "sample_list"]
    (installed / site_seed.DONE).unlink()
    env = (installed / ".env").read_text(encoding="utf-8").replace("TB_ENV=VALIDATION", "TB_ENV=PRODUCTION")
    (installed / ".env").write_text(env, encoding="utf-8")
    assert site_seed.run(installed, lambda *_a: pytest.fail("a sample on a box in use")) == ["site"]


def test_a_real_folder_in_the_samples_place_gets_no_sample(installed: Path) -> None:
    env = (
        (installed / ".env")
        .read_text(encoding="utf-8")
        .replace("TB_SOURCE_DIR=./site/sample", "TB_SOURCE_DIR=/srv/his")
    )
    (installed / ".env").write_text(env, encoding="utf-8")
    assert site_seed.run(installed, lambda *_a: pytest.fail("not the hospital's folder")) == ["site"]


# ------------------------------------------------------------------------------------------------ a bare host
def test_the_runbooks_host_commands_bring_their_own_libraries() -> None:
    """R22-48: the product's host commands start with no PYTHONPATH (``tools/__init__.py``); the bench counts every one
    with the system's python3 (``python3 -m tools.runbook_install bare``)."""
    from tools import runbook_install as ri

    cmds = ri.host_commands()
    assert len(cmds) >= 50 and ("tools.keys", "unseal") in cmds and ("tools.trialbox", "doctor") in cmds
    for mod in ("tools.keys", "tools.box", "tools.site_seed"):
        done = subprocess.run([sys.executable, "-m", mod, "--help"], cwd=ROOT, env=ri.BARE_ENV, capture_output=True,
                              text=True, check=False, timeout=60)  # fmt: skip
        assert done.returncode == 0, (mod, done.stderr[-300:])


def test_no_entry_of_the_box_ever_says_its_source_is_synthetic() -> None:
    """The run gate's only way round is in code, and only the in-process box of the tools and tests takes it."""
    said = {str(f.relative_to(ROOT)) for d in ("services", "tools", "libs", "deploy") for f in (ROOT / d).rglob("*.*")
            if f.suffix in (".py", ".sh", ".yml", ".yaml") and "synthetic_source" in f.read_text(encoding="utf-8")}  # fmt: skip
    assert said == {"services/adapter/pipeline.py"}


# ------------------------------------------------------------------------------------------------ before the load
def test_a_mapping_the_answers_name_that_is_nowhere_stops_before_the_bundle_is_loaded(tmp_path: Path) -> None:
    """Found on the bench: it stopped only at the settings step, after the images were loaded."""
    import shutil

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    kit = tmp_path / "kit"
    kit.mkdir()
    answers = kit / "site.yaml"
    answers.write_text("mapping: mapping/tw_core/site_c.yaml\n", encoding="utf-8")

    def run() -> subprocess.CompletedProcess[str]:
        argv = [sys.executable, "-m", "tools.answers_files", str(answers), "--deploy", str(deploy), "--environment",
                "VALIDATION"]  # fmt: skip
        return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)

    got = run()
    assert got.returncode == 1 and "nothing was loaded or changed" in got.stderr
    with pytest.raises(settings_wizard.WizardError) as later:  # the same words as the settings step's
        settings_wizard.build({"tz": "Asia/Taipei", "mapping": "mapping/tw_core/site_c.yaml"})
    assert next(x for x in str(later.value).split("; ") if x.startswith("mapping file")) in got.stderr
    for place in (kit / "mapping" / "tw_core", deploy / "site" / "mapping" / "tw_core"):
        place.mkdir(parents=True)
        (place / "site_c.yaml").write_text("tz: Asia/Taipei\n", encoding="utf-8")
        assert run().returncode == 0
        shutil.rmtree(place)
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert install.index("python3 -m tools.answers_files") < install.index('say "bundle: verify and load')


def test_the_other_files_stop_a_box_in_use_and_the_shipped_mappings_are_the_trees(tmp_path: Path) -> None:
    from tools import answers_files as af

    given = {"tls_hostname": "a.b.test", "tls_cert_file": "/no/c.pem", "tls_key_file": "/no/k.pem"}
    assert len(af.missing(given, tmp_path, tmp_path, production=True)) == 2
    assert af.missing(given, tmp_path, tmp_path, production=False) == []
    base = ROOT / "services" / "adapter"
    tree = {str(f.relative_to(base)) for d in ("jp_core", "tw_core") for f in (base / "mapping" / d).glob("*.yaml")}
    assert af.shipped_mappings() == tree


def test_a_tree_without_the_department_list_is_not_stopped_by_it(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings_wizard.shipped_departments("ja")["RHEU"] == "Rheumatology"
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    assert settings_wizard.shipped_departments("ja") == {}
