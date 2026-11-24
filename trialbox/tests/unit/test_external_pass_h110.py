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
