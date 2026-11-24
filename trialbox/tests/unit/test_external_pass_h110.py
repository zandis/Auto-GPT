"""H-110: the external review pass's findings on lane H's install, start, backup and key paths, on master 8ddecb8d.

Each test here fails on 8ddecb8d and passes with the card (the card's page: docs/handover/external-pass-h110-2026-11-24.md):

* (a) a kept ``/opt/trialbox`` tree runs only when it is the signed release's tree (the bootstrap ran the kept tree's
  ``box-install.sh`` whatever it held, so the vendor key's signature did not cover the installer that ran);
* (b) the stick's launcher says why when the vendor key cannot be read (already so on master: held here);
* (c) a systemd host with no cron daemon runs the log retention and the signed audit head from a timer;
* (d) H-109: a MAILTO with a name ("IT <it@site>") is carried by the backup's timer too;
* (e) the start path refuses a ``deploy/.env`` that group or others can read;
* (f) the host check FAILs a plain site key that group or others can read, on every box and profile;
* (g) a plain key only root reads is not taken for a secret others can read (its line names no mode);
* (i) a signal at the passphrase prompt gives the terminal its echo back;
* (l) a KEK rotation to the passphrase the box is sealed under now is refused.

Synthetic keys, passphrases and settings only.
"""

from __future__ import annotations

import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

from tests.unit import test_host_baseline as hb
from tests.unit.test_kek_passphrase_file_h96 import PHRASE, _sealed_box, _write_pp
from tools import host_tree, keys, sign_bundle
from tools.trialbox import backup_schedule as bs
from tools.trialbox import launch

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "deploy" / "bootstrap.sh"
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
SIGNED_BOX = '#!/usr/bin/env bash\necho "signed box-install: $0 $*"\n'
SIGNED_INSTALL = '#!/usr/bin/env bash\necho "signed install: $0 $*"\n'


# ------------------------------------------------------------------------------------------------ (a) the bootstrap
FILES = {"deploy/install.sh": SIGNED_INSTALL, "deploy/box-install.sh": SIGNED_BOX, "deploy/docker-compose.yml": "services: {}\n",
         "tools/__init__.py": "", "tools/x.py": "X = 1\n",
         "tools/host_tree.py": (ROOT / "tools" / "host_tree.py").read_text(encoding="utf-8")}  # fmt: skip


@pytest.fixture
def release(tmp_path: Path) -> dict[str, Path]:
    """A signed bundle whose host tree is made as the vendor makes it (``HOST-SHA256SUMS`` first)."""
    if shutil.which("openssl") is None:
        pytest.skip("the bootstrap checks with openssl")
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    src = tmp_path / "src"
    for name, text in FILES.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(text, encoding="utf-8")
        (src / name).chmod(0o755 if name.endswith(".sh") else 0o644)
    host = tmp_path / "trialbox-host.tar"
    host_tree.pack(src, host, list(FILES))
    (tmp_path / "usb").mkdir()
    bundle = tmp_path / "usb" / "trialbox-1.0.0.tar"
    sign_bundle.build(priv, "1.0.0", [("host", host, "trialbox-host.tar")], bundle, release_seq=3)
    return {"pub": pub, "bundle": bundle, "opt": tmp_path / "opt" / "trialbox", "tmp": tmp_path}


def _boot(r: dict[str, Path], *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(r["opt"])}
    return subprocess.run(["bash", str(BOOT), str(r["bundle"]), "--pub", str(r["pub"]), *args], capture_output=True,
                          text=True, env=env, check=False, timeout=60)  # fmt: skip


PLANT = '#!/bin/sh\ntouch "{marker}"\necho planted\n'
CHANGES = {
    "nothing": None,
    "the box installer": "deploy/box-install.sh",
    "the installer": "deploy/install.sh",
    "a host tool": "tools/x.py",
    "the host-tree module": "tools/host_tree.py",
    "a module the release does not hold": "tools/json.py",
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_the_installer_that_runs_from_a_kept_tree_is_the_signed_one(release: dict[str, Path], change: str) -> None:
    """The invariant of (a) (the integrator's ruling 7119913331): whatever a kept tree holds, the installer that runs
    is the signed release's own, and no code of the kept tree runs. The kept tree is the site's data: its own files
    stay, a changed file of the release is set aside (never deleted), and the signed release is brought in first."""
    assert _boot(release).returncode == 0  # the first run unpacks the signed tree
    opt = release["opt"]
    (opt / "deploy" / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")  # the site's own file
    marker = release["tmp"] / "planted-ran"
    rel = CHANGES[change]
    if rel is not None:
        (opt / rel).write_text(PLANT.format(marker=marker), encoding="utf-8")
    got = _boot(release, "--box", "--", "--yes")
    assert got.returncode == 0, got.stdout + got.stderr
    assert not marker.exists() and "planted" not in got.stdout, got.stdout
    assert f"signed box-install: {opt}/deploy/box-install.sh {release['bundle']} --yes" in got.stdout
    for name, text in FILES.items():  # what runs from here on is the signed tree, every file of it
        assert (opt / name).read_text(encoding="utf-8") == text, name
    assert (opt / "deploy" / ".env").read_text(encoding="utf-8") == "TB_ENV=TEST\n"
    if rel is None:
        assert "already holds this release's host tree" in got.stdout and not (opt / "releases").exists()
    else:
        assert "none of its code is run" in got.stdout and "brought in: the signed release 1.0.0" in got.stdout
        assert os.readlink(opt / "current") == "releases/1.0.0"
        assert not (opt / "tools" / "json.py").exists()  # the kept tree's own code folder went aside whole
        kept = [p for p in (opt / "releases").glob(".replaced-*/**/*") if p.is_file()]
        assert any(p.read_text(encoding="utf-8") == PLANT.format(marker=marker) for p in kept), kept


def test_a_module_planted_at_the_top_of_a_kept_tree_stops_before_anything_runs(release: dict[str, Path]) -> None:
    """A module at the top is no release path, so bringing the release in leaves it: a python3 started there would
    import it, so nothing runs (H-94 (1): only the signed files run)."""
    assert _boot(release).returncode == 0
    marker = release["tmp"] / "planted-ran"
    (release["opt"] / "sitecustomize.py").write_text(f"open({str(marker)!r}, 'w')\n", encoding="utf-8")
    got = _boot(release, "--box")
    assert got.returncode == 1 and "still does not match the signed release (sitecustomize.py: " in got.stderr
    assert not marker.exists() and "running:" not in got.stdout


def test_an_older_bundle_is_never_brought_in_over_a_newer_box(release: dict[str, Path]) -> None:
    assert _boot(release).returncode == 0
    opt = release["opt"]
    (opt / "deploy" / "updates").mkdir(parents=True)
    (opt / "deploy" / "updates" / "installed.json").write_text('{"release_seq": 7}', encoding="utf-8")
    (opt / "deploy" / "install.sh").write_text("#!/bin/sh\necho the newer release\n", encoding="utf-8")
    got = _boot(release)
    assert got.returncode == 1 and "records release_seq 7; the bundle is release_seq 3" in got.stderr, got.stderr
    assert (opt / "deploy" / "install.sh").read_text(encoding="utf-8") == "#!/bin/sh\necho the newer release\n"
    assert not (opt / "releases").exists() and "running:" not in got.stdout


def test_an_installed_tree_of_this_release_is_kept_through_its_links(release: dict[str, Path]) -> None:
    """A box installed from this bundle: the release files are links into releases/<id> (tools/host_tree.py); the
    links are followed, the site's own files beside them are not the release's business."""
    opt = release["opt"]
    rel = opt / "releases" / "1.0.0"
    for name, text in FILES.items():
        (rel / name).parent.mkdir(parents=True, exist_ok=True)
        (rel / name).write_text(text, encoding="utf-8")
    (opt / "current").symlink_to("releases/1.0.0")
    (opt / "deploy").mkdir()
    for name in ("install.sh", "box-install.sh", "docker-compose.yml"):
        (opt / "deploy" / name).symlink_to(f"../current/deploy/{name}")
    (opt / "tools").symlink_to("current/tools")
    (opt / "deploy" / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    (opt / "deploy" / "site").mkdir()
    got = _boot(release, "--box")
    assert got.returncode == 0 and "already holds this release's host tree" in got.stdout, got.stderr
    assert "signed box-install" in got.stdout


# ------------------------------------------------------------------------------------------------ (b) the launcher
def test_a_vendor_key_that_cannot_be_read_stops_the_launcher_with_its_reason(tmp_path: Path) -> None:
    """(b): already so on master (HS-1's review, dcfbf4f8): the fingerprint's failure is said, never a silent exit."""
    stick = tmp_path / "stick"
    stick.mkdir()
    text = (ROOT / "deploy" / "launcher.sh").read_text(encoding="utf-8")
    (stick / "install").write_text(text.replace("@VENDOR_KEY_FINGERPRINT@", "aaaa bbbb cccc dddd eeee ffff"))
    (stick / "vendor_ed25519.pub").write_text("not a key\n", encoding="utf-8")
    for f in ("trialbox-bootstrap.sh", "trialbox-bootstrap.sh.sig", "trialbox-1.0.0.tar"):
        (stick / f).write_text("", encoding="utf-8")
    got = subprocess.run(["bash", str(stick / "install")], capture_output=True, text=True, check=False, timeout=30,
                         env={**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1"})  # fmt: skip
    assert (
        got.returncode == 1
        and got.stderr.strip() == "TrialBox: the vendor key on the stick cannot be read. Call the vendor."
    )


# ------------------------------------------------------------------------------------------------ (c) the retention
def _retention_part(tmp: Path, *, cron_dir: bool, cron_daemon: bool, anchor_unsafe: bool = False) -> dict[str, str]:
    """install.sh's own lines from the systemd-host test to the retention's end, as root on a systemd host."""
    a = INSTALL.index("# H-92 (D-1090): a systemd host")
    b = INSTALL.index('if [ "$(id -u)" = 0 ] && [ -d /etc/logrotate.d ]', a)
    run, units, cron, stub = tmp / "run-systemd", tmp / "units", tmp / "cron.d", tmp / "bin"
    for d in (run, units, stub):
        d.mkdir()
    if cron_dir:  # with the file an earlier install wrote there
        cron.mkdir()
        (cron / "trialbox-retention").write_text("SHELL=/bin/sh\n20 0 * * * root cd /opt/trialbox && true\n")
    log = tmp / "systemctl.log"
    active = "exit 0" if cron_daemon else "exit 3"
    for name, body in (("id", "echo 0"), ("python3", "exit 0"),
                       ("systemctl", f'echo "$*" >> {log}\ncase "$1" in is-active) {active} ;; esac\nexit 0')):  # fmt: skip
        (stub / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (stub / name).chmod(0o755)
    script = (f"stop_or_warn() {{ echo \"STOP $*\"; exit 1; }}\nROOT=/opt/trialbox\nSYSTEMD_DIR={units}\n"
              f"ANCHOR_UNSAFE={int(anchor_unsafe)}\n" + INSTALL[a:b]).replace("/run/systemd/system", str(run))  # fmt: skip
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60,
                       env={"PATH": f"{stub}:/usr/bin:/bin", "TB_ENV_SITE": "PRODUCTION", "TB_CRON_DIR": str(cron)})  # fmt: skip
    assert r.returncode == 0 and "STOP" not in r.stdout, (r.stdout, r.stderr)
    out = {"err": r.stderr, "systemctl": log.read_text(encoding="utf-8") if log.exists() else ""}
    for f in ("trialbox-retention.service", "trialbox-retention.timer"):
        out[f] = (units / f).read_text(encoding="utf-8") if (units / f).exists() else ""
    out["cron"] = (
        (cron / "trialbox-retention").read_text(encoding="utf-8") if (cron / "trialbox-retention").exists() else ""
    )
    return out


@pytest.mark.parametrize("cron_dir", [False, True], ids=["no cron folder", "a cron folder, no daemon"])
def test_a_systemd_host_without_a_cron_daemon_runs_the_retention_from_a_timer(tmp_path: Path, cron_dir: bool) -> None:
    got = _retention_part(tmp_path, cron_dir=cron_dir, cron_daemon=False)
    svc = got["trialbox-retention.service"]
    assert "python3 -m tools.trialbox logs daily; python3 -m tools.trialbox audit-sign;" in svc, got
    assert "cd /opt/trialbox && " in svc and "Type=oneshot" in svc
    assert (
        "OnCalendar=*-*-* 00:20:00" in got["trialbox-retention.timer"]
        and "Persistent=true" in got["trialbox-retention.timer"]
    )
    assert "enable --now trialbox-retention.timer" in got["systemctl"]
    assert got["cron"] == ""  # one schedule, never both
    assert "trialbox-retention.timer runs its job" in got["err"]


def test_a_host_whose_cron_daemon_runs_keeps_the_cron_file_and_no_timer(tmp_path: Path) -> None:
    got = _retention_part(tmp_path, cron_dir=True, cron_daemon=True)
    assert "audit-sign" in got["cron"] and got["trialbox-retention.service"] == "" and "enable" not in got["systemctl"]


def test_a_warned_anchor_folder_takes_the_signed_head_out_of_the_timer_too(tmp_path: Path) -> None:
    got = _retention_part(tmp_path, cron_dir=False, cron_daemon=False, anchor_unsafe=True)
    assert "logs daily" in got["trialbox-retention.service"] and "audit-sign" not in got["trialbox-retention.service"]


def test_the_host_check_takes_the_timers_for_the_cron_files(tmp_path: Path) -> None:
    args, env = hb._box(tmp_path)
    host = tmp_path / "host"
    for c in ("trialbox-retention", "trialbox-backup"):
        (host / "etc/cron.d" / c).unlink()
    (host / "etc/systemd/system").mkdir(parents=True)
    for t in ("trialbox-retention.timer", "trialbox-backup-nightly.timer"):
        (host / "etc/systemd/system" / t).write_text("[Timer]\n", encoding="utf-8")
    r = hb._sh(args, env)
    assert r.returncode == 0, r.stdout
    assert "PASS  systemd timer /etc/systemd/system/trialbox-retention.timer" in r.stdout
    assert "PASS  systemd timer /etc/systemd/system/trialbox-backup-nightly.timer" in r.stdout


# ------------------------------------------------------------------------------------------------ (d) H-109
def test_a_mailto_with_a_name_is_carried_by_the_timer_as_by_cron() -> None:
    template = (ROOT / "deploy" / "backup" / f"{bs.CRON_NAME}.cron").read_text(encoding="utf-8")
    mailto = "IT <it@site.example>"
    text = bs.cron_text(template, Path("/opt/trialbox"), mailto)
    assert f'MAILTO="{mailto}"' in text
    units = bs.unit_files(text, mailto)
    assert all(f'echo "To: {mailto}"' in units[t.replace(".timer", ".service")] for t in bs.TIMERS)
    for bad in ("IT <it@site>; reboot", "it@site`x`", 'it@site"'):
        with pytest.raises(ValueError):
            bs.unit_files(text, bad)


# ------------------------------------------------------------------------------------------------ (e) launch.py
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_the_start_path_refuses_a_box_file_others_can_read(tmp_path: Path, mode: int) -> None:
    f = tmp_path / ".env"
    f.write_text("TB_ENV=TEST\n", encoding="utf-8")
    f.chmod(mode)
    with pytest.raises(launch.BoxFileError, match=r"can be read by group or others \(chmod 600 it\): nothing was run"):
        launch.box_file(tmp_path)
    f.chmod(0o600)
    assert launch.box_file(tmp_path) == {"TB_ENV": "TEST"}


# ------------------------------------------------------------------------------------------------ (f), (g) check_host
def _kept(text: str) -> str:
    """install.sh's own tb_kept_fails on ``text``."""
    a = INSTALL.index("tb_kept_fails() {")
    b = INSTALL.index("# ---- end of STOP-OR-WARN", a)
    r = subprocess.run(["bash", "-c", INSTALL[a:b] + "tb_kept_fails"], input=text, capture_output=True, text=True,
                       check=True, timeout=30)  # fmt: skip
    return r.stdout


@pytest.mark.parametrize(("env_name", "poc"), [("DEV", False), ("VALIDATION", True), ("PRODUCTION", False)])
def test_a_plain_site_key_others_can_read_fails_the_host_check_on_every_box(tmp_path: Path, env_name: str,
                                                                            poc: bool) -> None:  # fmt: skip
    args, env = hb._box(tmp_path, plain=True, env_name=env_name)
    if poc:
        envf = Path(args[args.index("--env") + 1])
        envf.write_text(envf.read_text(encoding="utf-8") + "TB_HOST_PROFILE=poc\n", encoding="utf-8")
    (tmp_path / "secrets" / "site_hmac.key").chmod(0o644)
    r = hb._sh(args, env)
    line = (
        "FAIL  site_hmac.key mode 644: a plain site key that group or others can read (want 600, root-owned) [H-94 (5)]"
    )
    assert r.returncode == 1 and line in r.stdout.splitlines(), r.stdout
    assert "pid_map.key mode" not in r.stdout  # the other plain key is root's alone (0600)
    assert _kept(r.stdout).strip().splitlines() == [line]  # kept by the install: it stops a PoC box too


def _class_box(tmp: Path, kind: str) -> tuple[list[str], dict[str, str]]:
    args, env = hb._box(tmp)
    envf = Path(args[args.index("--env") + 1])
    if kind == "env-mode":
        envf.chmod(0o644)
    elif kind == "poc-production":
        envf.write_text("TB_ENV=PRODUCTION\nTB_HOST_PROFILE=poc\n", encoding="utf-8")
    elif kind == "disk-full":
        hb._stubs(tmp, {"df": 'case "$1" in --output=source) echo Filesystem; echo /dev/mapper/root ;;\n'
                              '  *) echo "Filesystem 1024-blocks Used Available Capacity Mounted"; '
                              'echo "/dev/mapper/root 100 96 4 96% /" ;; esac\n'})  # fmt: skip
    return args, env


CLASSES = {  # each FAIL class of a kept refusal, the line check_host.sh makes, its kind marker
    "env-mode": ("FAIL  .env mode 644 (want 600, root-owned)", "5"),
    "poc-production": ("FAIL  TB_HOST_PROFILE=poc on a PRODUCTION box", "3"),
    "disk-full": ("FAIL  free space on /var/lib/docker: 4% (below 10%)", "2"),
}


@pytest.mark.parametrize("kind", sorted(CLASSES))
def test_each_kept_fail_class_carries_its_kind_marker_and_is_kept_by_it(tmp_path: Path, kind: str) -> None:
    """(g; the integrator's ruling 7119913331): the host check writes the kind where it makes the line; the install
    keeps the line by that marker alone."""
    r = hb._sh(*_class_box(tmp_path, kind))
    start, n = CLASSES[kind]
    got = [ln for ln in r.stdout.splitlines() if ln.startswith(start)]
    assert len(got) == 1 and got[0].endswith(f" [H-94 ({n})]"), r.stdout
    assert _kept(r.stdout).strip().splitlines() == got
    assert _kept(got[0].removesuffix(f" [H-94 ({n})]") + "\n") == ""  # the same words without the marker: not kept


def test_the_old_fault_a_0600_key_line_that_names_its_mode_is_not_a_secret_fail() -> None:
    """(g) pinned: master's unsealed-key line said "(mode 600)" and so was kept as a secret others can read (its words
    held "mode" and "key"); a line is kept by its marker now, whatever its words."""
    old = "FAIL  site_hmac.key is a plain file (mode 600): seal it (deploy/hardening/seal_keys.sh; python3 -m tools.keys init)\n"
    assert _kept(old) == ""
    assert _kept("FAIL  the token file mode 644 [H-94 (4)]\nFAIL  any words at all [H-94 (5)]\n") == (
        "FAIL  any words at all [H-94 (5)]\n"
    )


def test_a_plain_key_only_root_reads_is_not_taken_for_a_secret_others_can_read(tmp_path: Path) -> None:
    """(g): on a VALIDATION box without the poc profile a plain 0600 key FAILs as unsealed, a FAIL that is none of the
    five: it carries no kind marker, so a PoC install warns on it."""
    args, env = hb._box(tmp_path, plain=True, env_name="VALIDATION")
    r = hb._sh(args, env)
    assert "FAIL  site_hmac.key is a plain file: seal it" in r.stdout, r.stdout
    assert _kept(r.stdout) == ""


# ------------------------------------------------------------------------------------------------ (i) the prompt
def _children(pid: int) -> list[int]:
    out = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if int((p / "stat").read_text().rsplit(")", 1)[1].split()[1]) == pid:
                    out.append(int(p.name))
            except (OSError, IndexError, ValueError):
                continue
    return out


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGHUP, signal.SIGTERM])
def test_a_signal_at_the_passphrase_prompt_gives_the_terminal_its_echo_back(tmp_path: Path, sig: int) -> None:
    """The KEK-INPUT block (the same lines in install.sh, box-install.sh and seal_keys.sh): the prompt turns the echo
    off; a signal there turned it back on only in the normal end. The script still ends by the signal."""
    sec = tmp_path / "sec"
    sec.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_KEK_BACKEND": "passphrase",
                                                                             "TB_HOST_ROOT": str(tmp_path)}  # fmt: skip
    pid, fd = pty.fork()
    if pid == 0:  # the terminal's shell: the script, then the terminal's settings
        cmd = f'sh {SEAL} --secrets {sec} --kek-passphrase-stdin --dry-run; echo "RC=$?"; stty -a'
        os.execvpe("bash", ["bash", "-c", cmd], env)
    seen = b""
    deadline = time.monotonic() + 20
    while b"not shown): " not in seen and time.monotonic() < deadline:
        if select.select([fd], [], [], 1)[0]:
            seen += os.read(fd, 1024)
    kids = _children(pid)
    assert b"not shown): " in seen and kids, seen
    time.sleep(0.2)
    for k in kids:
        os.kill(k, sig)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if not select.select([fd], [], [], 1)[0]:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
    os.waitpid(pid, 0)
    text = seen.decode(errors="replace")
    assert f"RC={128 + sig}" in text, text
    settings = text[text.index("RC=") :]
    assert " echo " in settings and " -echo " not in settings, settings


# ------------------------------------------------------------------------------------------------ (l) keys.py
def test_a_rotation_to_the_passphrase_the_box_is_sealed_under_is_refused(tmp_path: Path,
                                                                         capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    """D-1092 rotates an exposed passphrase: a rotation to the same one (a new salt, a new KEK id) would leave the
    exposed passphrase opening the box. Refused, nothing changed; a new passphrase still rotates."""
    sec = _sealed_box(tmp_path, capsys)
    from tb_common.audit import AuditLog

    audit = tmp_path / "audit"
    AuditLog(audit).append("test.box_ready", actor="tester")
    env = {"TB_KEK_FILE": str(tmp_path / "kek.runtime"), "TB_ENV": "DEV", "TB_AUDIT_DIR": str(audit)}
    before = (sec / K.META_FILE).read_bytes()
    wrapped = (sec / "site_hmac.key.wrapped").read_bytes()
    old_f, same_f = _write_pp(tmp_path / "old.pass"), _write_pp(tmp_path / "same.pass")
    rc = keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(old_f), "--new-passphrase-file", str(same_f)], env=env)  # fmt: skip
    out = capsys.readouterr()
    assert rc == 1 and "the new passphrase is the one the box is sealed under now" in out.err, out.err
    assert PHRASE not in out.out + out.err
    assert (sec / K.META_FILE).read_bytes() == before and (sec / "site_hmac.key.wrapped").read_bytes() == wrapped
    assert not list(sec.glob("*.next*")) and not (sec / keys.JOURNAL).exists()
    old_f, new_f = _write_pp(tmp_path / "old2.pass"), _write_pp(tmp_path / "new.pass", "synthetic-h110-a-new-one\n")
    assert keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                      "--passphrase-file", str(old_f), "--new-passphrase-file", str(new_f)], env=env) == 0  # fmt: skip
    assert PHRASE not in capsys.readouterr().out


# ================================================================================ the sweep's items (7120987904)
# ------------------------------------------------------------------------------------------------ M-IB-2
def _merge_env(env: Path, key: str, value: str) -> None:
    from tools.box import __main__ as boxmain

    boxmain.merge_env(env, {key: value})


def _set_env(env: Path, key: str, value: str) -> None:
    from tools.trialbox import backup_schedule as bs

    bs.set_env(env, key, value)


def _memcaps(env: Path, key: str, value: str) -> None:
    from tools.trialbox import memcaps

    memcaps.write(env, {key: value}, 1, "synthetic")


def _pgsize(env: Path, key: str, value: str) -> None:
    from tools.trialbox import pgsize

    pgsize.write(env, {key: value})


def _image_pins(env: Path, key: str, value: str) -> None:
    from tools import image_pins

    image_pins.write_env(env, {key: value})


@pytest.mark.parametrize(
    "write",
    [_merge_env, _set_env, _memcaps, _pgsize, _image_pins],
    ids=["M-IB-2 box apply", "ESC-5 backup-install", "memcaps", "pgsize", "image_pins"],
)
def test_the_box_settings_are_replaced_whole_never_rewritten_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: Any
) -> None:
    """Every writer of ``deploy/.env`` (the box's apply, backup-install, the memory caps, PostgreSQL's sizes, the image
    pins) rewrote it in place or by a shared temp name with no sync: a cut write left it empty
    or short (every password gone), and a new file was 0644 until the chmod. Now one helper: a new file beside it,
    0600 from its first byte, on disk, renamed over it."""
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=synthetic-old\nTB_TZ=UTC\n", encoding="utf-8")
    env.chmod(0o600)
    before = env.stat().st_ino
    modes: list[int] = []
    real_replace = os.replace

    def replace(src: str | Path, dst: str | Path) -> None:
        modes.append(os.stat(src).st_mode & 0o777)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    write(env, "TB_TZ", "Asia/Tokyo")
    assert env.stat().st_ino != before and modes == [0o600] and env.stat().st_mode & 0o777 == 0o600
    after = env.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=synthetic-old\n" in after and "TB_TZ=Asia/Tokyo\n" in after and "TB_TZ=UTC" not in after

    def cut(fd: int) -> None:
        raise OSError("synthetic: the power went")

    monkeypatch.setattr(os, "fsync", cut)
    with pytest.raises(OSError, match="the power went"):
        write(env, "TB_TZ", "Europe/Paris")
    assert env.read_text(encoding="utf-8") == after
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]  # no temp file left


# ------------------------------------------------------------------------------------------------ M-LH-1
@pytest.mark.parametrize("case", ["another user's", "a link", "two names"])
def test_a_box_file_not_roots_alone_fails_the_host_check_whatever_its_mode(tmp_path: Path, case: str) -> None:
    args, env = hb._box(tmp_path)
    envf = Path(args[args.index("--env") + 1])
    if case == "another user's" and os.geteuid() == 0:  # as root: the file given to another uid
        os.chown(envf, 4242, 4242)
    elif case == "another user's":  # as a user (CI): the check runs as uid 4242 (a stand-in id), the file is ours
        hb._stubs(tmp_path, {"id": 'case "$1" in -u) echo 4242 ;; *) /usr/bin/id "$@" ;; esac\n'})
    elif case == "a link":
        real = tmp_path / "real.env"
        envf.rename(real)
        envf.symlink_to(real)
    else:
        os.link(envf, tmp_path / "second-name")
    r = hb._sh(args, env)
    kept = _kept(r.stdout).strip().splitlines()
    want = {"another user's": ".env is owned by uid ", "a link": ".env is a link", "two names": ".env has 2 names"}
    assert r.returncode == 1 and [k for k in kept if k.startswith(f"FAIL  {want[case]}")], r.stdout
    assert all(k.endswith("[H-94 (5)]") for k in kept)


def test_the_install_makes_the_box_file_roots() -> None:
    i = INSTALL.index("\nchmod 600 deploy/.env\n")
    assert INSTALL[i : i + 120].splitlines()[2].startswith('[ "$(id -u)" != 0 ] || chown 0:0 deploy/.env')


# ------------------------------------------------------------------------------------------------ M-LH-2
def _override_part(tmp: Path, ovr: Path, pre: str = "") -> subprocess.CompletedProcess[str]:
    """install.sh's own override lines, run on a box folder of the test's own (``pre``: shell run before them)."""
    a = INSTALL.index('NO_OVR="the compose override (not used)"')
    b = INSTALL.index('COMPOSE+=(--profile "$MODE")', a)
    root = tmp / "box"
    (root / "deploy" / "site").mkdir(parents=True, exist_ok=True)
    script = ("set -euo pipefail\nstop_or_warn() { echo \"STOP $*\"; exit 1; }\nis_standins() { return 1; }\n"
              f"ROOT={root}\nCOMPOSE=(docker compose); FILES=base.yml; MODE=stub\nTB_COMPOSE_OVERRIDE={ovr}\n"
              + pre + INSTALL[a:b] + 'echo "FILES=$FILES"\n')  # fmt: skip
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60)


def test_the_override_root_reads_later_is_a_copy_in_deploy_site(tmp_path: Path) -> None:
    """The override was used where the caller kept it: a user who can write a folder above it could replace it before
    any later root start. Root's compose commands now read a copy in deploy/site, 0644."""
    shared = tmp_path / "shared"
    shared.mkdir()
    ovr = shared / "override.yml"
    ovr.write_text("services: {}\n", encoding="utf-8")
    ovr.chmod(0o644)
    r = _override_part(tmp_path, ovr)
    copy = tmp_path / "box" / "deploy" / "site" / "compose-override.yml"
    assert r.returncode == 0 and f"FILES=base.yml:{copy}" in r.stdout, (r.stdout, r.stderr)
    assert copy.read_text(encoding="utf-8") == "services: {}\n" and copy.stat().st_mode & 0o777 == 0o644
    ovr.write_text("services: {evil: {image: x}}\n", encoding="utf-8")  # a later change to the caller's file
    assert copy.read_text(encoding="utf-8") == "services: {}\n"


def test_the_override_copied_is_the_file_that_was_checked(tmp_path: Path) -> None:
    """OCR 1455-2 (B): the override was checked by name, then copied by name: a file swapped in under that name after
    the check became root's copy. It is now opened once, checked and copied through that one descriptor. The swap is
    made by a stand-in for stat, right after the first look at the file's owner and mode."""
    shared = tmp_path / "shared"
    shared.mkdir()
    ovr = shared / "override.yml"
    ovr.write_text("services: {}\n", encoding="utf-8")
    ovr.chmod(0o644)
    evil = shared / "swap.yml"
    evil.write_text("services: {evil: {image: x, volumes: ['/:/host']}}\n", encoding="utf-8")
    evil.chmod(0o644)
    flag = tmp_path / "swap-once"
    flag.touch()
    pre = f'stat() {{ command stat "$@"; r=$?; if [ -e {flag} ]; then rm -f {flag}; mv -f {evil} {ovr}; fi; return $r; }}\n'
    r = _override_part(tmp_path, ovr, pre)
    copy = tmp_path / "box" / "deploy" / "site" / "compose-override.yml"
    assert not flag.exists(), "the stand-in never ran: " + r.stderr
    assert r.returncode == 0 and f"FILES=base.yml:{copy}" in r.stdout, (r.stdout, r.stderr)
    assert copy.read_text(encoding="utf-8") == "services: {}\n"


def test_the_override_s_owner_and_mode_are_those_of_the_file_copied(tmp_path: Path) -> None:
    """OCR 1455-2 (B), the other order: the file opened is group-writable and a sound file is put under its name before
    the look at owner and mode. The look is at the open file, so the override is refused (not used)."""
    shared = tmp_path / "shared"
    shared.mkdir()
    ovr = shared / "override.yml"
    ovr.write_text("services: {evil: {image: x}}\n", encoding="utf-8")
    ovr.chmod(0o664)
    good = shared / "good.yml"
    good.write_text("services: {}\n", encoding="utf-8")
    good.chmod(0o644)
    flag = tmp_path / "swap-once"
    flag.touch()
    pre = f'stat() {{ if [ -e {flag} ]; then rm -f {flag}; mv -f {good} {ovr}; fi; command stat "$@"; }}\n'
    r = _override_part(tmp_path, ovr, pre)
    assert not flag.exists(), "the stand-in never ran: " + r.stderr
    assert r.returncode == 1 and "STOP override-mode" in r.stdout, (r.stdout, r.stderr)
    assert not (tmp_path / "box" / "deploy" / "site" / "compose-override.yml").exists()


def test_the_install_starts_only_from_compose_files_in_its_tree(tmp_path: Path) -> None:
    """OCR 1455-2 (A), the integrator's ruling 7128436810 (the copy layout): a compose file of the set that resolves
    outside the tree is copied into deploy/site (root's, 0644) and the copy is what COMPOSE_FILE and compose name;
    a file of the tree, a link into the tree included, is used where it is."""
    a = INSTALL.index("# OCR 1455-2 (A), the integrator's ruling 7128436810: root's later starts")
    b = INSTALL.index("# the same file set for every later", a)
    root = tmp_path / "box"
    (root / "deploy" / "site").mkdir(parents=True)
    (root / "releases" / "r1").mkdir(parents=True)
    (root / "releases" / "r1" / "base.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "deploy" / "docker-compose.yml").symlink_to(root / "releases" / "r1" / "base.yml")
    out = tmp_path / "elsewhere" / "extra.yml"
    out.parent.mkdir()
    out.write_text("services: {extra: {}}\n", encoding="utf-8")
    inside = root / "deploy" / "docker-compose.yml"
    script = (f"set -euo pipefail\nROOT={root}\nFILES={inside}:{out}\nCOMPOSE=(docker compose -f {inside} -f {out})\n"
              + INSTALL[a:b] + 'echo "FILES=$FILES"; echo "COMPOSE=${COMPOSE[*]}"\n')  # fmt: skip
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60)
    copy = root / "deploy" / "site" / "compose-extra.yml"
    assert r.returncode == 0, r.stderr
    assert f"FILES={inside}:{copy}\n" in r.stdout and f"-f {inside} -f {copy}" in r.stdout, r.stdout
    assert copy.read_text(encoding="utf-8") == "services: {extra: {}}\n" and copy.stat().st_mode & 0o777 == 0o644
    out.write_text("services: {evil: {}}\n", encoding="utf-8")  # a later change where it lay changes nothing
    assert copy.read_text(encoding="utf-8") == "services: {extra: {}}\n"


def _guard(tmp: Path, env_name: str, compose: Path) -> subprocess.CompletedProcess[str]:
    deploy = tmp / "deploy"
    deploy.mkdir(exist_ok=True)
    (deploy / ".env").write_text(f"TB_ENV={env_name}\nCOMPOSE_FILE={compose}\n", encoding="utf-8")
    (deploy / ".env").chmod(0o600)
    return subprocess.run(["sh", str(ROOT / "deploy" / "settings_guard.sh"), str(deploy)], capture_output=True,
                          text=True, check=False, timeout=60, env={"PATH": "/usr/bin:/bin"})  # fmt: skip


@pytest.mark.parametrize("env_name", ["PRODUCTION", "TEST"])
def test_every_start_refuses_a_compose_file_in_a_folder_others_can_write(tmp_path: Path, env_name: str) -> None:
    """settings_guard.sh (the unit's ExecStartPre) checked the compose files only for the rehearsal mark: a file in a
    folder others can write was read by root's start as it was. The start is refused on every box (H-94 (1); the
    TEST case was rc 0 with a warning until the integrator's ruling 7128436810 on OCR 1455-2 (A))."""
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    f = open_dir / "extra.yml"
    f.write_text("services: {}\n", encoding="utf-8")
    open_dir.chmod(0o777)
    r = _guard(tmp_path, env_name, f)
    why = f"the compose file {f}: {open_dir} can be written by group or others (mode 777)"
    assert r.returncode == 1 and f"TrialBox REFUSED to start: {why}" in r.stderr, r.stderr
    open_dir.chmod(0o755)
    r = _guard(tmp_path, env_name, f)
    assert r.returncode == 0 and "compose file" not in r.stderr, r.stderr


# ------------------------------------------------------------------------------------------------ M-BK-1, L-BK-1
def _opens(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, int]]:
    seen: list[tuple[str, int, int]] = []
    real = os.open

    def spy(path: str | Path, flags: int, mode: int = 0o777, **kw: object) -> int:
        seen.append((str(path), flags, mode))
        return real(path, flags, mode, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", spy)
    return seen


def test_a_vendor_key_is_never_replaced_and_is_private_from_its_first_byte(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    seen = _opens(monkeypatch)
    priv, pub = sign_bundle.keygen(tmp_path / "keys")
    made = [(p, fl, m) for p, fl, m in seen if Path(p).name.startswith(".vendor_ed25519.key.")]
    assert made and all(fl & os.O_EXCL and m == 0o600 for _, fl, m in made)
    assert priv.stat().st_mode & 0o777 == 0o600
    before = (priv.read_bytes(), pub.read_bytes())
    for _ in range(2):  # the command a person re-runs: refused, nothing written
        assert sign_bundle.main(["keygen", "--out", str(tmp_path / "keys")]) == 1
    assert (priv.read_bytes(), pub.read_bytes()) == before
    assert sign_bundle.main(["keygen", "--out", str(tmp_path / "keys"), "--force"]) == 0
    assert priv.read_bytes() != before[0] and priv.stat().st_mode & 0o777 == 0o600


def test_the_backup_private_key_is_made_0600_and_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import backup as bk

    seen = _opens(monkeypatch)
    bk.keygen(tmp_path / "it.key", tmp_path / "box.pub")
    mine = [(fl, m) for p, fl, m in seen if p == str(tmp_path / "it.key")]
    assert mine and all(fl & os.O_EXCL and m == 0o600 for fl, m in mine), seen
    assert (tmp_path / "it.key").stat().st_mode & 0o777 == 0o600


# ------------------------------------------------------------------------------------------------ M-SC-1
def _egress() -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tb_egress_h110", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # its dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


SAVER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("e", sys.argv[1]); e = importlib.util.module_from_spec(spec)
sys.modules["e"] = e; spec.loader.exec_module(e)
from pathlib import Path
bad = 0
for i in range(300):
    try:
        e.save_state(Path(sys.argv[2]), e.Box(subnets={"172.30.%d.0/24" % (i % 200)}), "# synthetic\\n" * 50)
    except OSError:
        bad += 1
print(bad)
"""


def test_two_applies_at_once_never_break_the_state_file(tmp_path: Path) -> None:
    """Two runs (the 2-minute timer, the watch on a container start) shared one temp file: renames failed, and a
    reader (the boot's restore) could find no usable state. Each run's temp file is its own and on disk first."""
    state = tmp_path / "egress-state.json"
    eg = _egress()
    eg.save_state(state, eg.Box(subnets={"172.30.0.0/24"}), "# synthetic\n")  # type: ignore[attr-defined]
    procs = [subprocess.Popen([sys.executable, "-c", SAVER, str(ROOT / "deploy" / "egress.py"), str(state)],
                              stdout=subprocess.PIPE, text=True) for _ in range(2)]  # fmt: skip
    unreadable = 0
    while any(p.poll() is None for p in procs):
        try:
            eg.load_state(state)  # type: ignore[attr-defined]
        except (OSError, ValueError):
            unreadable += 1
    errors = [int((p.communicate()[0] or "0").strip()) for p in procs]
    assert errors == [0, 0] and unreadable == 0
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_apply_and_save_take_the_one_lock_before_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eg = _egress()

    class Taken(Exception):
        pass

    def lock(state: Path) -> int:
        raise Taken(str(state))

    monkeypatch.setattr(eg, "state_lock", lock)
    monkeypatch.setattr(eg, "allowlist", lambda *a, **k: pytest.fail("read before the lock"))
    for action in ("apply", "save"):
        with pytest.raises(Taken):
            eg.main([action, "--state", str(tmp_path / "s.json"), "--env", str(tmp_path / ".env")])  # type: ignore[attr-defined]


def test_a_second_apply_waits_for_the_first(tmp_path: Path) -> None:
    eg = _egress()
    state = tmp_path / "egress-state.json"
    code = (f"import importlib.util; s = importlib.util.spec_from_file_location('e', {str(ROOT / 'deploy' / 'egress.py')!r}); "
            f"e = importlib.util.module_from_spec(s); import sys; sys.modules['e'] = e; s.loader.exec_module(e); "
        f"from pathlib import Path; "
            f"e.state_lock(Path({str(state)!r})); print('got it')")  # fmt: skip
    fd = eg.state_lock(state)  # type: ignore[attr-defined]
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    with pytest.raises(subprocess.TimeoutExpired):
        p.wait(timeout=1.5)
    os.close(fd)
    assert p.communicate(timeout=30)[0].strip() == "got it"


# ------------------------------------------------------------------------------------------------ M-SC-2, M-SC-3
#: the helper as it ends on each box: PRODUCTION stops with its words and exit 1, a PoC box warns and goes on
HELPER = (
    'stop_or_warn() {{ shift 2; if [ "{poc}" = 1 ]; then echo "install: warning (PoC box, H-94): $*" >&2; '
    'return 0; fi; echo "install: $*" >&2; exit 1; }}\n'
)


def _units_part(tmp: Path, *, egress_ok: bool, poc: bool = False) -> subprocess.CompletedProcess[str]:
    a = INSTALL.index('SYSTEMD_DIR="${TB_SYSTEMD_DIR:-/etc/systemd/system}"')
    b = INSTALL.index("# H-92 (D-1090): a systemd host", a)
    script = (f"ROOT=/opt/trialbox\nEGRESS_OK={int(egress_ok)}\nsay() {{ :; }}\n" + HELPER.format(poc=int(poc))
              + INSTALL[a:b])  # fmt: skip
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "TB_SYSTEMD": "0"})  # fmt: skip


@pytest.mark.parametrize("poc", [False, True], ids=["PRODUCTION stops", "PoC box warns"])
def test_a_host_without_systemd_is_told_nothing_restores_egress_at_boot(tmp_path: Path, poc: bool) -> None:
    """M-SC-2 (the integrator's ruling 7122559749): a stop on PRODUCTION, a warning on a PoC box."""
    r = _units_part(tmp_path, egress_ok=True, poc=poc)
    assert r.returncode == (0 if poc else 1) and "nothing restores the egress rules after a reboot" in r.stderr, (
        r.stderr
    )
    assert "deploy/network.sh restore" in r.stderr and ("warning (PoC box" in r.stderr) is poc
    assert "nothing restores" not in _units_part(tmp_path, egress_ok=False).stderr


def test_a_cron_folder_with_no_cron_daemon_is_said(tmp_path: Path) -> None:
    a = INSTALL.index("# H-92 (D-1090): a systemd host")
    b = INSTALL.index('if [ "$(id -u)" = 0 ] && [ -d /etc/logrotate.d ]', a)
    stub = tmp_path / "bin"
    stub.mkdir()
    for name, body in (("id", "echo 0"), ("python3", "exit 0"), ("pgrep", "exit 1")):
        (stub / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (stub / name).chmod(0o755)
    (tmp_path / "cron.d").mkdir()
    script = HELPER.format(poc=0) + "ROOT=/opt/trialbox\nANCHOR_UNSAFE=0\n" + INSTALL[a:b]
    r = subprocess.run(["bash", "-c", script.replace("/run/systemd/system", str(tmp_path / "no-systemd"))],
                       capture_output=True, text=True, check=False, timeout=60,
                       env={"PATH": f"{stub}:/usr/bin:/bin", "TB_ENV_SITE": "PRODUCTION",
                            "TB_CRON_DIR": str(tmp_path / "cron.d")})  # fmt: skip
    assert r.returncode == 1 and (tmp_path / "cron.d" / "trialbox-retention").is_file(), r.stderr  # PRODUCTION stops
    assert "install: no cron daemon runs on this host: nothing runs" in r.stderr


def _retention_said(
    tmp: Path, poc: bool, stubs: dict[str, str], systemd: bool, path: str
) -> subprocess.CompletedProcess[str]:
    """install.sh's own retention lines with the stop helper (a PoC box warns, PRODUCTION stops)."""
    a = INSTALL.index("# H-92 (D-1090): a systemd host")
    b = INSTALL.index('if [ "$(id -u)" = 0 ] && [ -d /etc/logrotate.d ]', a)
    stub, run = tmp / "bin", tmp / ("run-systemd" if systemd else "no-systemd")
    stub.mkdir(exist_ok=True)
    if systemd:
        run.mkdir()
        (tmp / "units").mkdir()
    for name, body in stubs.items():
        (stub / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (stub / name).chmod(0o755)
    (tmp / "cron.d").mkdir(exist_ok=True)
    script = (
        HELPER.format(poc=int(poc))
        + f"ROOT=/opt/trialbox\nANCHOR_UNSAFE=0\nSYSTEMD_DIR={tmp / 'units'}\n"
        + INSTALL[a:b]
    )
    return subprocess.run(["bash", "-c", script.replace("/run/systemd/system", str(run))], capture_output=True,
                          text=True, check=False, timeout=60,
                          env={"PATH": f"{stub}:{path}", "TB_ENV_SITE": "PRODUCTION", "TB_CRON_DIR": str(tmp / "cron.d")})  # fmt: skip


@pytest.mark.parametrize("poc", [False, True], ids=["PRODUCTION stops", "PoC box warns"])
def test_a_retention_timer_that_cannot_be_installed_is_a_stop_on_production(tmp_path: Path, poc: bool) -> None:
    """OCR 1455-8 (the integrator's ruling 7128436810): a systemd host with no cron daemon whose timer cannot be
    enabled only warned, PRODUCTION too: the retention and the signed audit head never ran."""
    systemctl = 'case "$1" in is-active) exit 3 ;; enable) exit 1 ;; esac\nexit 0'
    r = _retention_said(tmp_path, poc, {"id": "echo 0", "python3": "exit 0", "systemctl": systemctl}, True,
                        "/usr/bin:/bin")  # fmt: skip
    assert r.returncode == (0 if poc else 1), r.stderr
    assert "trialbox-retention.timer could not be installed" in r.stderr and ("warning (PoC box" in r.stderr) is poc


@pytest.mark.parametrize("poc", [False, True], ids=["PRODUCTION stops", "PoC box warns"])
def test_a_host_without_pgrep_is_told_its_cron_daemon_cannot_be_checked(tmp_path: Path, poc: bool) -> None:
    """OCR 1455-8: on a host without pgrep the cron-daemon check was skipped in silence."""
    tools = tmp_path / "tools"  # every tool of /usr/bin and /bin but pgrep
    tools.mkdir()
    for d in ("/usr/bin", "/bin"):
        for t in Path(d).iterdir():
            if t.name != "pgrep" and not (tools / t.name).exists():
                (tools / t.name).symlink_to(t)
    r = _retention_said(tmp_path, poc, {"id": "echo 0", "python3": "exit 0"}, False, str(tools))
    assert r.returncode == (0 if poc else 1), r.stderr
    assert "this host has no pgrep" in r.stderr and ("warning (PoC box" in r.stderr) is poc


# ------------------------------------------------------------------------------------------------ L-IB-2
def test_a_callers_vendor_key_never_stands_in_for_the_boxs(tmp_path: Path) -> None:
    """Before trust.json, TB_VENDOR_PUBKEY (through sudo -E or env_keep) chose the key the bundle was checked with."""
    root = tmp_path / "box"
    (root / "tools").mkdir(parents=True)
    (root / "deploy" / "keys").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "apply_update.sh", root / "tools" / "apply_update.sh")
    _, pinned = sign_bundle.keygen(tmp_path / "vendor")
    _, other = sign_bundle.keygen(tmp_path / "other")
    shutil.copy(pinned, root / "deploy" / "keys" / "vendor_ed25519.pub")
    bundle = tmp_path / "trialbox-1.tar"
    bundle.write_bytes(b"synthetic")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TB_VENDOR_PUBKEY": str(other)}
    r = subprocess.run(["sh", str(root / "tools" / "apply_update.sh"), str(bundle), "--dry-run"], capture_output=True,
                       text=True, check=False, timeout=60, env=env)  # fmt: skip
    assert r.returncode == 1 and f"TB_VENDOR_PUBKEY ({other}) is not the box's vendor key" in r.stderr, r.stderr
    env["TB_VENDOR_PUBKEY"] = str(pinned)  # the same key: as before (the signature check goes on, here to its refusal)
    r = subprocess.run(["sh", str(root / "tools" / "apply_update.sh"), str(bundle), "--dry-run"], capture_output=True,
                       text=True, check=False, timeout=60, env=env)  # fmt: skip
    assert "is not the box's vendor key" not in r.stderr


# ------------------------------------------------------------------------------------------------ L-CI-1
@pytest.mark.parametrize("path", ["trialbox/libs/tb_llm/prompts/assist_v2.md", "trialbox/models/cards/x.md"])
def test_a_prompt_or_a_model_card_is_never_a_documents_only_change(path: str) -> None:
    from tools import ci_docs_only, ci_tier

    only = ci_docs_only.docs_only([path])  # what the `changes` job hands the tier as DOCS_ONLY
    assert not only
    _, _, why = ci_tier.decide({"EVENT": "pull_request", "HEAD_REF": "x", "DOCS_ONLY": str(only).lower()}, [path])
    assert "documents only" not in why


# ------------------------------------------------------------------------------------------------ GP-PL-1
PW = "synthetic-" + "pw"  # a made-up password, joined so the secret scan sees no URL with credentials
DAY2_ENV = {"TB_DB_URL": "postgresql://tb:" + PW + "@db:5432/trialbox_wf",
            "TB_HAPI_DB_URL": "postgresql://hapi:" + PW + "@db:5432/hapi"}  # fmt: skip
URL = DAY2_ENV["TB_DB_URL"]


@pytest.mark.parametrize(
    "args",
    [["--dbname", URL], [f"--dbname={URL}"], ["-d", URL], [f"-d{URL}"], [URL]],
    ids=["long", "long=", "-d", "-dVALUE", "positional"],
)
def test_the_spool_never_writes_the_jobs_connection_in_any_form(args: list[str]) -> None:
    """GP-PL-1: the spool mapped only --dbname: a connection given by -d, -dVALUE or by position went to the spool
    volume with its password."""
    from tools.trialbox import platform_day2 as d2

    lines = d2.spool_args("psql", [*args, "-c", "select 1"], DAY2_ENV)
    assert lines == ["psql", "--dbname", "@TB_DB_URL", "-c", "select 1"] and PW not in "".join(lines)


@pytest.mark.parametrize(
    "arg",
    [
        "postgresql://x:" + "y@elsewhere/db",
        "postgres://x@elsewhere/db",
        "host=elsewhere dbname=x password=" + "y",
        "dbname=trialbox_wf user=tb",
    ],
    ids=["uri", "postgres-uri", "key=value with a password", "key=value"],
)
def test_the_spool_refuses_any_other_connection_in_any_form(arg: str) -> None:
    from tools.trialbox import platform_day2 as d2

    for args in (["-d", arg], [f"-d{arg}"], [arg]):
        with pytest.raises(d2.Day2Error, match="refused"):
            d2.spool_args("psql", args, DAY2_ENV)


# ------------------------------------------------------------------------------------------------ the ticker
@pytest.mark.parametrize(("script", "start"), [("deploy/poc.sh", "ALIVE_PID=\"\"\nalive_start() {"),
                                                ("deploy/install.sh", "alive_start() {")])  # fmt: skip
def test_a_ticker_a_stop_orphans_never_holds_the_callers_output(tmp_path: Path, script: str, start: str) -> None:
    """The once-a-minute ticker's sleep inherited the caller's stdout and stderr. A stop whose TERM landed before
    ``s=$!`` left the sleep running (37 of 3000 start/stop pairs here), and a caller reading the output (a test's
    subprocess.run, a log pipe) waited for it: test_poc_real_embedder's 120 s timeout under load. Now no orphan holds
    the output: a thousand start/stop pairs return at once."""
    text = (ROOT / script).read_text(encoding="utf-8")
    a = text.index(start)
    b = text.index("\n}\n", text.index("alive_stop()", a)) + 3
    body = text[a:b].replace("sleep 60 ", 'sleep "${TB_POC_ALIVE_S:-60}" ')
    run = tmp_path / "ticker.sh"
    run.write_text("ALIVE_PID=\"\"\n" + body + "TB_POC_ALIVE_S=600\nfor i in $(seq 1 1000); do alive_start x; alive_stop; done\n",
                   encoding="utf-8")  # fmt: skip
    t = time.monotonic()
    r = subprocess.run(["bash", str(run)], capture_output=True, text=True, check=False, timeout=60)
    assert r.returncode == 0 and time.monotonic() - t < 30, r.stderr


# ------------------------------------------------------------------------------------------------ 1396-1 (High)
def _pair_run(tmp: Path, poc: bool) -> subprocess.CompletedProcess[str]:
    """install.sh's own model-pair lines (promoted on its shipped record, this box's canary failing, the put-back
    failing too) and its own closing lines, with stand-ins for the tools: a PoC box or PRODUCTION."""
    a = INSTALL.index('  pin_tool --promote-shipped "$GPU" --records /q --images-lock /images.lock\n')
    b = INSTALL.index("  set -e\nfi\n", a)
    c = INSTALL.index("# H-94: on a PoC box each FAIL line is a warning and a line of the list")
    stub = tmp / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "python3").write_text("#!/bin/sh\necho 'selftest: the canary did not pass'\nexit 1\n", encoding="utf-8")
    (stub / "python3").chmod(0o755)
    script = (
        "set -euo pipefail\nGPU=rtxpro6000\nFAILS=()\nKEPT_FAILS=()\nSECRET_FAILS=()\nCOMPOSE=(true)\nsay() { :; }\n"
        'pin_tool() { case "$1" in --promote-shipped) return 0 ;; *) return 1 ;; esac; }\n'
        f"tb_poc_box() {{ return {0 if poc else 1}; }}\n"
        'stop_or_warn() { shift 3 2>/dev/null; tb_poc_box && { echo "warning (PoC box, H-94): $*" >&2; return 0; }; exit 1; }\n'
        "set +e\n" + INSTALL[a:b] + "set -e\n" + INSTALL[c:]
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60,
                          env={"PATH": f"{stub}:/usr/bin:/bin"})  # fmt: skip


@pytest.mark.parametrize("poc", [True, False], ids=["PoC box (TEST)", "PRODUCTION"])
def test_a_model_pair_that_cannot_be_put_back_ends_the_install_1_with_its_line_last(tmp_path: Path, poc: bool) -> None:
    """1396-1: a pair promoted on its shipped record that failed this box's canary and could not be demoted stays
    promoted: the box cannot run it (H-94 (2)). On a PoC box that FAIL only warned and the install ended 0; now the
    install's closing lines end it 1 with that FAIL line last, as on PRODUCTION (OCR 1455-7: the exit code and the
    last line are what this proves; the summary printed before them is not run here)."""
    r = _pair_run(tmp_path, poc)
    last = r.stderr.strip().splitlines()[-1]
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert (
        last.startswith("install: FAIL: the model pair was promoted on its shipped record")
        and "could NOT be put back" in last
    )


# ------------------------------------------------------------------------------------------------ 1421-4 (ruled)
def test_the_restore_container_is_removed_when_it_ends_and_its_passwords_are_on_no_command_line(tmp_path: Path) -> None:
    """1421-4, ruled not a fault on one condition (the integrator's 7122559749): the passwords go to the restore
    container as ``-e NAME`` (the values in the engine's environment, never on a command line), and the container runs
    with ``--rm``, so that environment does not outlive it in the engine's inspect. Both held here."""
    from types import SimpleNamespace

    from tools.trialbox import box_restore

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    pw = "synthetic-" + "restore-pw"
    (deploy / ".env").write_text(
        f"TB_DB_URL=postgresql://trialbox:{pw}@db:5432/trialbox_wf\nPOSTGRES_PASSWORD={pw}\n"
        f"TB_DOCKER_VOLUMES={tmp_path / 'volumes'}\nTB_ENV=TEST\n",
        encoding="utf-8",
    )
    (deploy / ".env").chmod(0o600)
    for name in ("backup.tbbak", "it.key", "box.pub"):
        (tmp_path / name).write_text("synthetic\n", encoding="utf-8")
    a = SimpleNamespace(key=tmp_path / "it.key", public=tmp_path / "box.pub", keep_to=tmp_path / "keep",
                        refdata=tmp_path / "refdata", restic_share=[], dir=[], restic_from_box=False, no_copy=False,
                        other_site=False, older_ok=False)  # fmt: skip
    restore = box_restore.BoxRestore(deploy, run=lambda *args, **kw: "")
    argv, values = restore.container(a, tmp_path / "backup.tbbak", tmp_path / "work", "0" * 64)
    assert argv[argv.index("run") + 1] == "--rm", argv
    assert pw not in " ".join(argv) and any(pw in v for v in values.values())
    for name in values:
        assert argv[argv.index(name) - 1] == "-e"  # the name alone; its value from the engine's own environment
