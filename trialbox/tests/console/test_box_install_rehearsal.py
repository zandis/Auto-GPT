"""T-729 (D-466): the box-install rehearsal as far as it goes without Docker. ``deploy/box-install.sh`` runs for real,
with stand-ins only where a Docker daemon would be (the inner ``install.sh``, ``docker compose up``, the host check)
and the image's Python run in place. The console's first-run wizard runs in process on the same first-run folder.
So the path "install with only the wizard's answers" is exercised: the hardware is confirmed, the plan is made, the
install is called with the plan's flags in box mode, the code reaches the root-only file (H-97: with no terminal, as
the boot's service runs it; never the output, which the journal keeps), the owner
answers in the browser, and the apply step rewrites the settings and ``.env`` from those answers alone (keeping the
install's passwords) and restarts the stack. What only a real box proves is listed in D-466 for T-213b."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from console.app import create_app
from console.auth import UserStore
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog

from tests.console.test_console_app import PILOT_ENV, FakeBackend
from tests.console.test_firstrun import HW, _answers
from tests.unit.test_install_refuses_unsafe_folders_10k4 import GOOD, fake_host, knobs

ROOT = Path(__file__).resolve().parents[2]
PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"


def _tree(tmp_path: Path) -> dict[str, Path]:
    """A box folder: the script and the compose files copied (it writes beside them), the code linked."""
    box = tmp_path / "box"
    deploy = box / "deploy"
    (deploy / "systemd").mkdir(parents=True)
    for name in ("box-install.sh", "gpu_profile.sh", "docker-compose.yml", "docker-compose.identity.yml",
                 "docker-compose.rtxpro6000.yml", "docker-compose.box.yml", "systemd/trialbox-firstrun.service"):  # fmt: skip
        shutil.copy2(ROOT / "deploy" / name, deploy / name)
    for name in ("libs", "services", "tools", "schemas"):
        (box / name).symlink_to(ROOT / name)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls.log"
    install = stubs / "install.sh"
    install.write_text(
        "#!/bin/sh\n"
        f'echo "install TB_BOX=$TB_BOX TB_BOX_DEFER_SEAL=$TB_BOX_DEFER_SEAL $*" >> {calls}\n'
        f"printf 'POSTGRES_PASSWORD=made-by-install\\nTB_DB_PW_LAKE=made-by-install\\n"
        f"COMPOSE_FILE={deploy}/docker-compose.yml\\n' > {deploy}/.env\n"
        "echo '  TrialBox is running.'\n"
        "echo 'install: FAIL: no backup yet' >&2\nexit 1\n",  # a FAIL list at the end: the stack is up
        encoding="utf-8",
    )
    for name in ("compose", "hostcheck"):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {calls}\n', encoding="utf-8")
    # H-97: the passwd entry names the home of the root-only code file (a stand-in getent: never the tester's own home)
    pw_home = tmp_path / "pwhome"
    pw_home.mkdir()
    (stubs / "getent").write_text(f'#!/bin/sh\necho "tester:x:$(id -u):$(id -g)::{pw_home}:/bin/sh"\n', encoding="utf-8")
    for f in stubs.iterdir():
        f.chmod(0o755)
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({**HW, "gpu_name": PRO6000, "gpu_mem_gib": 96.0}), encoding="utf-8")
    fr = tmp_path / "firstrun"
    env = {
        **os.environ, "TB_BOX_NO_ROOT": "1", "TB_BOX_HARDWARE": str(hw), "TB_BOX_INSTALL": str(install),
        "TB_BOX_PY": sys.executable, "TB_BOX_COMPOSE": str(stubs / "compose"),
        "TB_BOX_HOST_CHECK": str(stubs / "hostcheck"), "PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}",
        "TB_FIRSTRUN_HOST_DIR": str(fr), "TB_BOX_POLL_S": "0.2", "TB_SYSTEMD": "0",
    }  # fmt: skip
    bundle = tmp_path / "trialbox-1.0.0.tar"
    bundle.write_bytes(b"stand-in bundle")
    return {"box": box, "deploy": deploy, "calls": calls, "fr": fr, "bundle": bundle, "env": env,  # type: ignore[dict-item]
            "issue": pw_home / "trialbox-firstrun-code"}  # fmt: skip  # H-97: the root-only file, no terminal


def _wait(path: Path, proc: subprocess.Popen[str], seconds: float = 60) -> str:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8")
        assert proc.poll() is None, proc.communicate()[0][-2000:]
        time.sleep(0.1)
    raise AssertionError(f"{path} never came")


def test_a_box_installs_from_the_installer_with_only_the_wizards_answers(tmp_path: Path) -> None:
    t: dict[str, Any] = _tree(tmp_path)
    h = fake_host(tmp_path / "host")  # 10K-4: the host the finish check reads, and the console image's read probe
    (tmp_path / "stubs" / "probe").write_text(f'#!/bin/sh\necho "probe $*" >> {t["calls"]}\n', encoding="utf-8")
    (tmp_path / "stubs" / "probe").chmod(0o755)
    t["env"] = {**t["env"], **knobs(h), "TB_BOX_DOCKER": str(tmp_path / "stubs" / "probe")}
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env=t["env"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)  # fmt: skip
    try:
        screen = _wait(t["issue"], proc)
        code = re.search(r"One-time code:\s+(\S+)", screen)
        assert code and "https://box1.local/login/first-run" in screen
        install = t["calls"].read_text(encoding="utf-8")
        assert "install TB_BOX=1 TB_BOX_DEFER_SEAL=0" in install and "--mode gpu --gpu rtxpro6000 --yes" in install
        provisional = json.loads((t["deploy"] / "site" / "box" / "answers.json").read_text(encoding="utf-8"))
        assert provisional["tls_mode"] == "internal" and provisional["env_extra"]["TB_MEM_DB"].endswith("m")
        # the owner, in a browser: the code from the screen, then the answers
        app = create_app({**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "console"), "TB_FIRSTRUN_DIR": str(t["fr"]),
                          "TB_CONSOLE_MFA": "totp"}, backend=FakeBackend(), audit=AuditLog(tmp_path / "audit"),
                         users=UserStore())  # fmt: skip
        c = TestClient(app, base_url="https://testserver")
        assert c.post("/login/first-run", data={"code": code.group(1)}, follow_redirects=False).status_code == 303
        # 10K-4 (D-1390): a PRODUCTION box finishes with a backup off the box and an audit anchor folder of its
        # own: the second disk's folder and the share's folder on the test's own host (fake_host's mount table)
        r, _ = _answers(c, backup_dir=GOOD["backup"], anchor_dir=GOOD["anchor"])
        assert r.status_code == 200 and 'data-testid="firstrun-done"' in r.text, r.text[-500:]
        out, _ = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, out[-3000:]
    settings = yaml.safe_load((t["deploy"] / "settings.yaml").read_text(encoding="utf-8"))
    assert settings["site"]["name"] == "示範醫院A (synthetic)" and settings["site"]["tz"] == "Asia/Tokyo"
    assert settings["site"]["locale"] == "ja" and settings["data_source"]["mapping"] == "mapping/tw_core/box_site.yaml"
    env = dict(ln.split("=", 1) for ln in (t["deploy"] / ".env").read_text(encoding="utf-8").splitlines() if "=" in ln)
    assert env["POSTGRES_PASSWORD"] == "made-by-install" and env["TB_DB_PW_LAKE"] == "made-by-install"
    assert env["TB_TLS_HOSTNAME"] == "trialbox.local" and env["TB_TLS_MODE"] == "internal"
    assert env["TB_BACKUP_TARGETS"] == GOOD["backup"] and env["TB_TZ"] == "Asia/Tokyo"
    assert "tz: Asia/Tokyo" in (t["deploy"] / "site" / "mapping" / "tw_core" / "box_site.yaml").read_text(
        encoding="utf-8"
    )
    calls = t["calls"].read_text(encoding="utf-8")
    assert "compose up -d --wait" in calls and "hostcheck" in calls
    assert not (t["fr"] / "answers.json").exists() and not t["issue"].exists()  # nothing of the owner's is left
    assert "TrialBox is ready: https://trialbox.local" in out
    # BOX-APPLIED (D-576): the mark, and a start after the apply (the window closed before the last line): no new
    # code, no wait for answers that will never come; the set-up is finished and the same last line is printed
    applied = t["deploy"] / "site" / "box" / "applied"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", applied.read_text(encoding="utf-8").strip())
    t["calls"].write_text("", encoding="utf-8")
    try:
        again = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), "--firstrun"], cwd=tmp_path, env=t["env"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30, check=False)  # fmt: skip
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f"the second start waits for ever:\n{(e.stdout or b'')[-600:]!r}") from e
    assert again.returncode == 0, again.stdout[-2000:]
    assert "One-time code:" not in again.stdout and not t["issue"].exists()
    assert "the owner's answers were applied on" in again.stdout
    assert "TrialBox is ready: https://trialbox.local" in again.stdout
    calls = t["calls"].read_text(encoding="utf-8")
    assert "compose up -d --wait" in calls and "hostcheck" in calls and "install " not in calls


def test_the_prepared_image_stops_before_the_wizard(tmp_path: Path) -> None:
    t: dict[str, Any] = _tree(tmp_path)
    r = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--prepare", "--yes"],
                       cwd=tmp_path, env=t["env"], capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert (t["deploy"] / "site" / "box" / "prepared").is_file()
    assert not t["issue"].exists() and not (t["fr"] / "code.json").exists()  # the code is made at the site


def test_a_stopped_install_stops_the_box_installer(tmp_path: Path) -> None:
    t: dict[str, Any] = _tree(tmp_path)
    failing = tmp_path / "stubs" / "install.sh"
    failing.write_text("#!/bin/sh\necho 'install: the bundle is not a valid signed TrialBox release' >&2\nexit 1\n",
                       encoding="utf-8")  # fmt: skip
    r = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                       env=t["env"], capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert r.returncode == 1 and "the install stopped" in r.stderr
    assert not t["issue"].exists()
    r = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), "--yes"], cwd=tmp_path, env=t["env"],
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 1 and "usage" in r.stderr


# ------------------------------------------------------------------------------------------------ BOX-WSL2 (D-571)
def _until_code(proc: subprocess.Popen[str], seconds: float = 60) -> str:
    """The script's output up to the line that says where the one-time code is (H-97: never the code itself)."""
    assert proc.stdout is not None
    seen = ""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        line = proc.stdout.readline()
        if not line:
            break
        seen += line
        if "the one-time code is" in line:
            return seen
    raise AssertionError(f"no line about the code on the output:\n{seen[-2000:]}")


@pytest.mark.parametrize("wsl2", ["1", "0"])
def test_on_or_off_wsl2_the_code_is_never_on_the_output_and_no_issue_file_is_written(
    tmp_path: Path, wsl2: str
) -> None:
    """H-97 (ruling 7101844662): with no terminal (the boot's service; a run whose output a log keeps) the code is in
    the root-only file the output names, on or off WSL2; never on the output and never in /etc/issue.d. (Under WSL2
    the Windows installer's window is the controlling terminal: tests/unit/test_first_run_code_h97.py.)"""
    t: dict[str, Any] = _tree(tmp_path)
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env={**t["env"], "TB_BOX_WSL2": wsl2}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)  # fmt: skip
    try:
        out = _until_code(proc)
        screen = _wait(t["issue"], proc)
        code = re.search(r"One-time code:\s+(\S+)", screen)
        assert code and "https://box1.local/login/first-run" in screen
        assert code.group(1) not in out and "One-time code" not in out
        assert f"in {t['issue']} (root only, 0600)" in out and f"sudo cat {t['issue']}" in out
        assert oct(t["issue"].stat().st_mode & 0o777) == "0o600"
        assert (t["fr"] / "code.json").is_file()  # the wizard is waiting for that code
        assert not (tmp_path / "issue.d").exists()
    finally:
        proc.kill()
        proc.communicate()


def test_the_wsl2_switch_reads_the_kernel_and_its_knob_takes_two_values(tmp_path: Path) -> None:
    text = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
    start = text.index("# BOX-WSL2 (D-571)")
    block = text[start : text.index("\n", text.index("TB_BOX_WSL2 is 0 or 1", start)) + 1]

    def wsl2(release: str, knob: str | None) -> subprocess.CompletedProcess[str]:
        script = (
            f'set -euo pipefail\ndie() {{ echo "box-install: $*" >&2; exit 1; }}\nuname() {{ echo "{release}"; }}\n'
            f'{block}\necho "WSL2=$WSL2"\n'
        )
        env = {"PATH": os.environ["PATH"], **({} if knob is None else {"TB_BOX_WSL2": knob})}
        return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)

    assert wsl2("6.6.87.2-microsoft-standard-WSL2", None).stdout.strip() == "WSL2=1"
    assert wsl2("5.15.0-Microsoft", None).stdout.strip() == "WSL2=1"
    assert wsl2("6.8.0-45-generic", None).stdout.strip() == "WSL2=0"
    assert wsl2("6.8.0-45-generic", "1").stdout.strip() == "WSL2=1"
    assert wsl2("6.6.87.2-microsoft-standard-WSL2", "0").stdout.strip() == "WSL2=0"
    r = wsl2("6.8.0-45-generic", "yes")
    assert r.returncode == 1 and "TB_BOX_WSL2 is 0 or 1" in r.stderr
    # the host's zone: Windows keeps it under WSL2, and one line says so
    zone = text[text.index('TZ_NEW="$(') :]
    zone = zone[zone.index('if [ "$WSL2" = 1 ]') : zone.index("chown ")]
    assert "Windows keeps the clock and the time zone" in zone and zone.index("timedatectl set-timezone") > zone.index(
        "elif "
    )
    # the two lines the Windows installer reads (lane W, tests/unit/test_windows_box_install.py)
    assert "\\n  TrialBox is ready: https://%s" in text
    assert "\n  TrialBox is running.\n" in (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")


def test_a_new_install_removes_the_applied_mark() -> None:
    """D-576: planning the box again from its hardware makes the answers provisional again; the wizard is due."""
    text = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
    plan = text[
        text.index(
            "# ---------------------------------------------------------------------------------------------- 2. plan"
        ) :
    ]
    plan = plan[: plan.index("3. install")]
    assert 'rm -f "$BOX/applied"' in plan
    first_run = text[text.index("5. first run") :]
    assert first_run.index('if [ -f "$BOX/applied" ]; then') < first_run.index("show_code() {")
    assert first_run.index("box_py apply") < first_run.index('> "$BOX/applied"') < first_run.index("timedatectl")


# ------------------------------------------------------------------------------- BOX-ANSWERS (D-898): unattended
OWNER = {
    "site_name": "示範醫院A (synthetic)", "tz": "Asia/Tokyo", "language": "ja", "owner_full_name": "Dr Owner",
    "owner_username": "owner", "owner_email": "owner@hospa.test", "box_name": "trialbox",
    "backup_kind": "second_disk", "backup_disk": "/dev/sdb", "source": "spreadsheet", "environment": "VALIDATION",
}  # fmt: skip


def _unattended(t: dict[str, Any], tmp_path: Path, owner: dict[str, Any], *extra: str,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
    f = tmp_path / "owner.json"
    f.write_text(json.dumps(owner, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--answers", str(f), *extra],
                          cwd=tmp_path, env={**t["env"], **(env or {})}, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120, check=False)  # fmt: skip


def test_a_box_installs_unattended_from_the_owners_answers_file(tmp_path: Path) -> None:
    """The hospital's install is unattended: no question, no first-run code, no wait. The plan is made from the
    owner's answers (here a VALIDATION box), the install makes the first administrator as the IT form does (TB_BOX=0:
    its password and enrolment code printed once), then the host check and the last line."""
    t: dict[str, Any] = _tree(tmp_path)
    r = _unattended(t, tmp_path, OWNER)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    install = t["calls"].read_text(encoding="utf-8")
    assert "install TB_BOX=0 TB_BOX_DEFER_SEAL=0" in install and "--mode gpu --gpu rtxpro6000 --yes" in install
    planned = json.loads((t["deploy"] / "site" / "box" / "answers.json").read_text(encoding="utf-8"))
    assert planned["env_extra"]["TB_ENV"] == "VALIDATION" and planned["tls_hostname"] == "trialbox.local"
    assert "hostcheck" in install and not t["issue"].exists() and not (t["fr"] / "code.json").exists()
    assert "One-time code" not in r.stdout and "unattended" in r.stdout
    assert "TrialBox is ready: https://trialbox.local" in r.stdout and "printed above" in r.stdout
    assert (t["deploy"] / "site" / "box" / "applied").is_file()  # a later --firstrun asks nothing again


def test_an_answers_file_with_a_password_or_that_does_not_parse_changes_nothing(tmp_path: Path) -> None:
    t: dict[str, Any] = _tree(tmp_path)
    for bad, said in (({**OWNER, "password": "x" * 16}, "password"), ({**OWNER, "kek_passphrase": "y" * 16},
                      "kek_passphrase"), ({**OWNER, "site_name": ""}, "site_name")):  # fmt: skip
        r = _unattended(t, tmp_path, bad)
        assert r.returncode == 1 and said in r.stderr and "nothing was changed" in r.stderr, r.stderr
        assert not t["calls"].exists() or "install " not in t["calls"].read_text(encoding="utf-8")
        assert not (t["deploy"] / "site" / "box" / "answers.json").exists()


def test_without_a_tpm_the_passphrase_comes_from_a_root_only_file_never_the_environment(tmp_path: Path) -> None:
    """H-96 (the integrator's ruling 7094934985): the environment form logged the passphrase in the system journal
    (sudo --preserve-env). Without a TPM the passphrase comes from a file only root can read (or stdin), never the
    answers file and never the environment: one there is refused before anything."""
    t: dict[str, Any] = _tree(tmp_path)
    hw = json.loads(Path(t["env"]["TB_BOX_HARDWARE"]).read_text(encoding="utf-8"))
    Path(t["env"]["TB_BOX_HARDWARE"]).write_text(json.dumps({**hw, "tpm": False}), encoding="utf-8")
    r = _unattended(t, tmp_path, OWNER)
    assert r.returncode == 1 and "--kek-passphrase-file" in r.stderr and "nothing was changed" in r.stderr
    assert not t["calls"].exists()
    r = _unattended(t, tmp_path, OWNER, env={"TB_KEK_PASSPHRASE": "a long synthetic test phrase"})
    assert r.returncode == 2 and "TB_KEK_PASSPHRASE is set in the environment: refused" in r.stderr
    assert "exposed" in r.stderr and not t["calls"].exists()
    assert "a long synthetic test phrase" not in r.stdout + r.stderr
    pp = tmp_path / "kek.pass"
    pp.write_text("a long synthetic test phrase\n", encoding="utf-8")
    pp.chmod(0o600)
    r = _unattended(t, tmp_path, OWNER, "--kek-passphrase-file", str(pp))
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    calls = t["calls"].read_text(encoding="utf-8")
    assert "install TB_BOX=0 TB_BOX_DEFER_SEAL=0" in calls and f"--kek-passphrase-file {pp}" in calls  # sealed there
    assert "KEK_BACKEND=passphrase" in (t["deploy"] / "site" / "hardening.conf").read_text(encoding="utf-8")
    assert "a long synthetic test phrase" not in r.stdout + r.stderr + calls


def test_answers_is_not_for_a_prepared_or_a_rehearsal_box(tmp_path: Path) -> None:
    t: dict[str, Any] = _tree(tmp_path)
    for other in ("--prepare", "--rehearsal"):
        r = _unattended(t, tmp_path, OWNER, other)
        assert r.returncode == 2 and "--answers" in r.stderr and not t["calls"].exists()
    r = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--answers"], cwd=tmp_path,
                       env=t["env"], capture_output=True, text=True, timeout=30, check=False)  # fmt: skip
    assert r.returncode == 2 and "--answers needs" in r.stderr


def _stale(t: dict[str, Any]) -> Path:
    from tb_common import preflight as text

    t["fr"].mkdir()
    f: Path = t["fr"] / text.FILE
    f.write_text('{"format": "stale"}', encoding="utf-8")
    return f


def test_the_installer_writes_the_preflight_for_the_first_run_page(tmp_path: Path) -> None:
    """10K-3 (D-1361): before the code is shown the installer runs the live preflight (TB_BOX_PREFLIGHT: the python
    that runs it, here this one) and writes its file into the first-run folder: owner-only, given to the console's
    user; an earlier run's file is removed first."""
    from tb_common import preflight as text

    t: dict[str, Any] = _tree(tmp_path)
    f = _stale(t)
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env={**t["env"], "TB_BOX_WSL2": "1", "TB_BOX_PREFLIGHT": sys.executable},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)  # fmt: skip
    try:
        _until_code(proc, 150)
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["format"] == text.FORMAT and [ln["id"] for ln in doc["lines"]] == list(text.IDS)
        assert oct(f.stat().st_mode & 0o777) == "0o600"
        if os.geteuid() == 0:  # chown works as root only (the box's installer runs as root)
            assert (f.stat().st_uid, f.stat().st_gid) == (10001, 10001)
    finally:
        proc.kill()
        proc.communicate()


def test_a_preflight_that_hangs_never_holds_the_code_back(tmp_path: Path) -> None:
    """10K-3: the preflight is stopped at its time limit; the code is shown and no earlier run's lines are left."""
    t: dict[str, Any] = _tree(tmp_path)
    f = _stale(t)
    hangs = tmp_path / "hangs"
    hangs.write_text("#!/bin/sh\nexec sleep 60\n", encoding="utf-8")
    hangs.chmod(0o755)
    env = {**t["env"], "TB_BOX_WSL2": "1", "TB_BOX_PREFLIGHT": str(hangs), "TB_BOX_PREFLIGHT_S": "1"}
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)  # fmt: skip
    t0 = time.monotonic()
    try:
        out = _until_code(proc)
        assert time.monotonic() - t0 < 50
        assert "the preflight did not finish in 1 s" in out and not f.exists()
    finally:
        proc.kill()
        proc.communicate()
