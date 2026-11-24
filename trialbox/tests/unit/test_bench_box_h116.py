"""H-116 (D-1357; the owner's ruling 7124664930, the design 7124901315): the bench mark.

A PRODUCTION box on the owner's bench host carries the mark ``deploy/install.sh --bench`` writes into its own record
(``deploy/site/bench-box.env``): every PRODUCTION protection stays (TB_ENV stays PRODUCTION), it is shown everywhere as
"PRODUCTION · BENCH (real data, bench host)", and test boxes may run beside it, sharing nothing with it.

* the mark is the install option's only: a caller's ``TB_BENCH``, ``TB_BENCH`` in deploy/.env with no record, and a
  record the option did not write (a link, another owner, writable by others, no install's trace, another folder's)
  are refused, at the install, at every start (deploy/settings_guard.sh) and by doctor;
* refused on a box that is not PRODUCTION, on a test box, on a rehearsal box and with a sending identity;
* the third kind in H-106's invariant: :func:`test_a_bench_box_test_boxes_beside_it_share_nothing`;
* the real install path, in the rehearsal job's ``test-boxes`` step (tools/rehearse_box/box.sh): a caller's variable,
  --bench on TEST and a hand-written mark refused; --bench on PRODUCTION goes on beside a running test box.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.unit.test_test_box_h106 import TEST_ARGS, Engine, H106Box, _compose_names, _published
from tools.trialbox import benchbox, doctor, testbox

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]
ROOT = Path(__file__).resolve().parents[2]
WHEN = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)


def _box(tmp_path: Path, env: str = "TB_ENV=PRODUCTION\n") -> Path:
    deploy = tmp_path / "bench" / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text(env, encoding="utf-8")
    return deploy


def _refused(deploy: Path, said: str, env: dict[str, str] | None = None) -> None:
    with pytest.raises(benchbox.Refused, match=said):
        benchbox.check(deploy, env)


# ------------------------------------------------------------------------------------------------ the record
def test_the_install_option_writes_a_record_the_check_holds(tmp_path: Path) -> None:
    deploy = _box(tmp_path)
    mark = benchbox.write(deploy, WHEN)
    rec = deploy / benchbox.RECORD
    assert rec.read_text(encoding="utf-8") == (
        f"{benchbox.HEADER}\nTB_BENCH=1\nTB_BENCH_ROOT={deploy.parent.resolve()}\nTB_BENCH_AT=2026-11-24T12:00:00Z\n"
    )
    assert (rec.stat().st_mode & 0o777) == 0o644 and rec.stat().st_uid in (0, os.geteuid())
    assert benchbox.check(deploy) == mark and mark.words().startswith("PRODUCTION · BENCH (real data, bench host): ")
    assert benchbox.write(deploy, datetime(2027, 1, 1, tzinfo=UTC)) == mark  # kept as it is when it holds
    assert benchbox.check(_box(tmp_path / "other")) is None  # no record, no TB_BENCH: no bench box


def test_a_mark_the_install_option_did_not_write_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The harm: a PRODUCTION box beside test boxes on a mark no owner's install option wrote."""
    deploy = _box(tmp_path, "TB_ENV=PRODUCTION\nTB_BENCH=1\n")
    _refused(deploy, "TB_BENCH=1 in deploy/.env with no record")  # the variable alone, in the box's own file
    rec = deploy / benchbox.RECORD
    good = benchbox.write(deploy, WHEN)
    text = rec.read_text(encoding="utf-8")
    for planted, said in (
        ("TB_BENCH=1\n", "does not carry the install's trace"),  # by hand: no first line, no folder, no time
        (text.replace(benchbox.HEADER, "# bench"), "does not carry the install's trace"),
        (text + "TB_ENV=TEST\n", "does not carry the install's trace"),
        (text.replace("TB_BENCH=1", "TB_BENCH=yes"), "TB_BENCH=1, its folder, its time"),
        (text.replace("2026-11-24T12:00:00Z", "today"), "TB_BENCH=1, its folder, its time"),
    ):
        rec.write_text(planted, encoding="utf-8")
        _refused(deploy, said)
    rec.write_text(text, encoding="utf-8")
    rec.chmod(0o666)
    _refused(deploy, r"may be written by others \(mode 0666\)")
    rec.chmod(0o644)
    if os.geteuid() == 0:
        os.chown(rec, 4242, -1)
    else:
        monkeypatch.setattr(os, "geteuid", lambda: rec.stat().st_uid + 1)
    _refused(deploy, "is owned by uid .*, not root")
    monkeypatch.undo()
    if os.geteuid() == 0:
        os.chown(rec, 0, -1)
    other = tmp_path / "elsewhere"
    other.mkdir()
    rec.write_text(text.replace(good.root, str(other)), encoding="utf-8")
    _refused(deploy, "was written for .*, not this folder")  # a record copied from another box's folder
    rec.unlink()
    (deploy / "site" / "elsewhere.env").write_text(text, encoding="utf-8")
    rec.symlink_to(deploy / "site" / "elsewhere.env")
    _refused(deploy, "is not a regular file")
    rec.unlink()
    rec.write_text(text, encoding="utf-8")
    assert benchbox.check(deploy) == good


@pytest.mark.parametrize(
    ("env", "said"),
    [
        ("TB_ENV=TEST\n", "this box is TEST .*: the bench mark is a PRODUCTION box's only"),
        ("TB_ENV=VALIDATION\n", "this box is VALIDATION"),
        ("TB_ENV=PRODUCTION\nSMTP_HOST=relay.hospital.example\n", r"sending identity \(SMTP_HOST=relay.hospital"),
        ("TB_ENV=PRODUCTION\nSMTP_HOST=localhost\nSMTP_USER=trialbox\n", r"sending identity \(SMTP_USER is set"),
        ("TB_ENV=PRODUCTION\nTB_BENCH=2\n", "TB_BENCH=2 in deploy/.env is not the record's"),
    ],
    ids=["test", "validation", "relay", "relay-login", "env-value"],
)
def test_the_mark_is_a_production_box_s_with_no_sending_identity(tmp_path: Path, env: str, said: str) -> None:
    deploy = _box(tmp_path)
    benchbox.write(deploy, WHEN)
    (deploy / ".env").write_text(env, encoding="utf-8")
    _refused(deploy, said)


def test_the_host_s_own_relay_is_no_sending_identity(tmp_path: Path) -> None:
    deploy = _box(tmp_path)
    benchbox.write(deploy, WHEN)
    for host in ("", "localhost", "127.0.0.1", "mailpit"):
        (deploy / ".env").write_text(f"TB_ENV=PRODUCTION\nTB_BENCH=1\nSMTP_HOST={host}\n", encoding="utf-8")
        assert benchbox.check(deploy) is not None


def test_a_test_box_never_carries_the_mark(tmp_path: Path) -> None:
    deploy = _box(tmp_path, "TB_ENV=TEST\n")
    testbox.record(deploy, "walk", "1")
    with pytest.raises(benchbox.Refused, match="a test box never carries the bench mark"):
        benchbox.write(deploy, WHEN)
    assert not (deploy / benchbox.RECORD).exists()


# ------------------------------------------------------------------------------------------------ the install
def _prod(tmp_path: Path, extra: str = "") -> H106Box:
    """A PRODUCTION box on H-94's bench with what a PRODUCTION install asks of the site (a feed folder, a TLS name,
    the SAE office's mailbox); the bench's id stand-in is not root, so its install stops at the sealing of the keys,
    after every step this card adds."""
    (tmp_path / "feed").mkdir(parents=True, exist_ok=True)
    return H106Box(tmp_path / "prod", env=f"TB_ENV=PRODUCTION\nTB_SOURCE_DIR={tmp_path / 'feed'}\n"
                   f"TB_TLS_HOSTNAME=box.invalid\nTB_SAE_OFFICE_MAILBOX=sae@hospa.test\n{extra}")  # fmt: skip


def _loaded(box: H106Box) -> bool:
    calls = box.tmp / "calls.log"
    return calls.exists() and "load " in calls.read_text(encoding="utf-8")


SEALING = "install: sealing the site keys needs root (the secrets volume, the TPM): run the installer as root"


def test_bench_goes_on_beside_a_test_box_where_production_is_refused(tmp_path: Path) -> None:
    """The one thing the mark changes: a PRODUCTION install with --bench goes on beside a test box (it is loaded, its
    deploy/.env says TB_BENCH=1); the same install without it is refused, as H-106 has it."""
    t = tmp_path / "t" / "deploy"
    (t / "site").mkdir(parents=True)
    testbox.record(t, "walk", "1")
    proj = testbox.project_for("walk", t.parent)
    engine = f"volume trialbox\nvolume {proj}\ndir {proj} {t}\n"
    p = _prod(tmp_path)
    r = p.run("--environment", "PRODUCTION", *TEST_ARGS, engine=engine)
    assert r.rc == 1 and "this host runs test boxes" in r.err.splitlines()[-1], r.text[-2000:]
    assert not (p.deploy / benchbox.RECORD).exists()
    r = p.run("--environment", "PRODUCTION", "--bench", *TEST_ARGS, engine=engine)
    assert f"install: note: a bench box (PRODUCTION · BENCH); test boxes beside it on this host: {proj}" in r.err
    assert r.rc == 1 and r.err.splitlines()[-1] == SEALING, r.text[-2000:]  # past the host check, loaded
    assert _loaded(p)
    assert (
        benchbox.check(p.deploy) is not None and p.dotenv()["TB_BENCH"] == "1" and p.dotenv()["TB_ENV"] == "PRODUCTION"
    )
    r = p.run("--environment", "PRODUCTION", *TEST_ARGS, engine=engine)  # again, without the option: its record speaks
    assert "test boxes beside it on this host" in r.err and r.err.splitlines()[-1] == SEALING, r.text[-2000:]


@pytest.mark.parametrize(
    ("args", "env", "said"),
    [
        (("--environment", "PRODUCTION"), {"TB_BENCH": "1"}, "TB_BENCH is set in this run's environment"),
        (("--environment", "PRODUCTION"), {"TB_BENCH": ""}, "TB_BENCH is set in this run's environment"),
        (("--environment", "TEST", "--bench"), {}, "--bench marks a PRODUCTION box, not TEST"),
        (("--environment", "VALIDATION", "--bench"), {}, "--bench marks a PRODUCTION box, not VALIDATION"),
        (("--bench", "--test-box", "x", "--port-offset", "1"), {}, "--bench and --test-box"),
        (("--bench", "--rehearsal"), {}, "--bench and --rehearsal"),
    ],
    ids=["variable", "empty-variable", "test", "validation", "test-box", "rehearsal"],
)
def test_the_mark_comes_from_the_option_on_production_only(tmp_path: Path, args: tuple[str, ...],
                                                           env: dict[str, str], said: str) -> None:  # fmt: skip
    p = _prod(tmp_path)
    r = p.run(*args, *TEST_ARGS, env=env)
    assert r.rc == 1 and said in r.err, r.text[-2000:]
    assert not (p.deploy / benchbox.RECORD).exists() and not _loaded(p)


def test_the_install_refuses_a_mark_it_did_not_write_and_a_sending_identity(tmp_path: Path) -> None:
    p = _prod(tmp_path)
    (p.deploy / "site").mkdir(parents=True, exist_ok=True)
    (p.deploy / benchbox.RECORD).write_text("TB_BENCH=1\n", encoding="utf-8")
    r = p.run("--environment", "PRODUCTION", *TEST_ARGS)
    assert r.rc == 1 and r.err.splitlines()[-1] == "install: the bench mark of this box is refused (above)", r.text
    assert "does not carry the install's trace" in r.err and not _loaded(p)
    (p.deploy / benchbox.RECORD).unlink()
    q = _prod(tmp_path / "relay", "SMTP_HOST=relay.hospital.example\n")
    r = q.run("--environment", "PRODUCTION", "--bench", *TEST_ARGS)
    assert r.rc == 1 and "sending identity (SMTP_HOST=relay.hospital.example" in r.err, r.text[-2000:]
    # the relay is the site's settings' (deploy/.env as the wizard writes it): refused when it is known, before the
    # stack is started; a relay already in deploy/.env is refused before the mark is written
    assert r.err.splitlines()[-1] == "install: the bench mark of this box is refused (above)", r.text[-2000:]
    assert "compose" not in " ".join(c for c in q.calls() if " up " in c)


# ------------------------------------------------------------------------------------------------ every start
def _guard(deploy: Path) -> subprocess.CompletedProcess[str]:
    """deploy/settings_guard.sh, as the unit and tools/apply_update.sh run it, on a tree with this repository's tools."""
    (deploy.parent / "tools").mkdir(exist_ok=True)
    if not (deploy.parent / "tools" / "trialbox").exists():
        (deploy.parent / "tools" / "trialbox").symlink_to(ROOT / "tools" / "trialbox")
        (deploy.parent / "tools" / "__init__.py").write_text("", encoding="utf-8")
    return subprocess.run(["sh", str(ROOT / "deploy" / "settings_guard.sh"), str(deploy)], capture_output=True,
                          text=True, timeout=60, check=False, env={**os.environ, "PYTHONPATH": str(ROOT / "libs")})  # fmt: skip


def test_every_start_checks_the_mark(tmp_path: Path) -> None:
    deploy = _box(tmp_path, "TB_ENV=PRODUCTION\nTB_BENCH=1\n")
    r = _guard(deploy)
    assert r.returncode == 1 and "TrialBox REFUSED to start: this box's bench mark is refused" in r.stderr, r
    assert "with no record" in r.stderr
    benchbox.write(deploy, WHEN)
    assert _guard(deploy).returncode == 0
    (deploy / ".env").write_text("TB_ENV=TEST\nTB_BENCH=1\n", encoding="utf-8")  # a hand edit before a reboot
    r = _guard(deploy)
    assert r.returncode == 1 and "this box is TEST" in r.stderr, r
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    (deploy / benchbox.RECORD).chmod(0o666)
    assert _guard(deploy).returncode == 1
    assert _guard(_box(tmp_path / "plain")).returncode == 0  # a box with no mark is not asked


# ------------------------------------------------------------------------------------------------ what it says
def test_doctor_and_the_console_say_production_bench_on_every_page(tmp_path: Path) -> None:
    deploy = _box(tmp_path, "TB_ENV=PRODUCTION\nTB_BENCH=1\n")
    benchbox.write(deploy, WHEN)
    inp = doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_BENCH": "1"}, deploy=deploy)
    c = doctor.check_rehearsal(inp)
    assert c.status == "WARN" and c.detail.startswith("PRODUCTION · BENCH (real data, bench host)"), c
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=deploy))
    assert c.status == "FAIL" and "no TB_BENCH=1" in c.detail, c
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "TEST", "TB_BENCH": "1"}, deploy=deploy))
    assert c.status == "FAIL" and "PRODUCTION box's only" in c.detail, c
    from console.app import environment_banner

    assert environment_banner({"TB_ENV": "PRODUCTION", "TB_BENCH": "1"}) == benchbox.LABEL
    assert environment_banner({"TB_ENV": "TEST", "TB_BENCH": "1"}) == "TEST"  # never on a box that is not PRODUCTION
    assert environment_banner({"TB_ENV": "PRODUCTION"}) == "PRODUCTION"
    base = (ROOT / "services" / "console" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "'BENCH' in settings.environment_label" in base  # the banner on every page, the footer names it too


# ------------------------------------------------------------------------------------------------ the third kind
def test_a_bench_box_test_boxes_beside_it_share_nothing(tmp_path: Path) -> None:
    """H-106's invariant with its third kind: the bench box is the host's ordinary project (trialbox, port offset 0),
    the engine lists it as a bench box, a test box installs beside it, and the two share no volume, network,
    published port or secrets volume."""
    bench = _box(tmp_path)
    benchbox.write(bench, WHEN)
    t = H106Box(tmp_path / "t")
    eng = Engine({"trialbox": str(bench.parent)})
    assert [(s.project, s.kind) for s in testbox.boxes(eng)] == [("trialbox", "bench")]
    r = t.run("--test-box", "t", "--port-offset", "1", *TEST_ARGS, engine=f"volume trialbox\ndir trialbox {bench}\n")
    assert r.rc == 0 and "other boxes on this host: trialbox (bench)" in r.err, r.text[-3000:]
    pt = t.dotenv()["COMPOSE_PROJECT_NAME"]
    (vt, nt), (vb, nb) = _compose_names(pt), _compose_names("trialbox")
    assert not vt & vb and not nt & nb and "trialbox_tb-secrets" in vb and f"{pt}_tb-secrets" in vt
    assert not _published(t.dotenv()) & _published({})
    (bench / benchbox.RECORD).chmod(0o666)  # a mark refused: the box counts as PRODUCTION, and no test box goes beside
    assert [(s.project, s.kind) for s in testbox.boxes(eng)] == [("trialbox", "production")]
    r = H106Box(tmp_path / "u").run("--test-box", "u", "--port-offset", "2", *TEST_ARGS,
                                    engine=f"volume trialbox\ndir trialbox {bench}\n")  # fmt: skip
    assert r.rc == 1 and "this host holds a PRODUCTION box (project trialbox)" in r.err, r.text[-2000:]


def test_the_option_writes_nothing_on_a_box_that_may_not_carry_the_mark(tmp_path: Path) -> None:
    for env, said in (("TB_ENV=PRODUCTION\nSMTP_HOST=relay.hospital.example\n", "sending identity"),
                      ("TB_ENV=VALIDATION\n", "this box is VALIDATION")):  # fmt: skip
        deploy = _box(tmp_path / said.split()[0], env)
        with pytest.raises(benchbox.Refused, match=said):
            benchbox.write(deploy, WHEN)
        assert not (deploy / benchbox.RECORD).exists()


def test_the_mark_changes_no_production_rule() -> None:
    """D-1357: a bench box keeps every PRODUCTION protection because the mark is no environment. TB_ENV stays
    PRODUCTION (the install writes TB_BENCH beside it), and TB_BENCH is read only where the mark is written, checked
    or shown; every rule that keys on PRODUCTION (encryption at rest and the keys, the audit chain, no egress,
    retention and backups, the gateway's limits) reads TB_ENV and runs on a bench box as on any PRODUCTION box."""
    readers = sorted(
        str(p.relative_to(ROOT))
        for top in ("libs", "services", "tools", "deploy")
        for p in (ROOT / top).rglob("*")
        if p.is_file()
        and p.suffix in (".py", ".sh", ".yml", ".yaml", ".html", ".toml", ".json")
        and re.search(r"\bTB_BENCH\b", p.read_text(encoding="utf-8", errors="replace"))
    )
    assert readers == [
        "deploy/install.sh",  # writes it beside TB_ENV=PRODUCTION (--bench), and refuses it from a caller
        "deploy/settings_guard.sh",  # every start: the record checked
        "libs/tb_common/config.py",  # declared
        "services/console/app.py",  # the banner, every page
        "tools/rehearse_box/box.sh",  # the real install path's refusals
        "tools/trialbox/benchbox.py",  # the record and its check
        "tools/trialbox/doctor.py",  # doctor's line
    ], readers
    from tb_common.config import environment_name

    assert environment_name({"TB_ENV": "PRODUCTION", "TB_BENCH": "1"}) == "PRODUCTION"
