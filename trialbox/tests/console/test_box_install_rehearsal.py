"""T-729 (D-466): the box-install rehearsal as far as it goes without Docker. ``deploy/box-install.sh`` runs for real,
with stand-ins only where a Docker daemon would be (the inner ``install.sh``, ``docker compose up``, the host check)
and the image's Python run in place. The console's first-run wizard runs in process on the same first-run folder.
So the path "install with only the wizard's answers" is exercised: the hardware is confirmed, the plan is made, the
install is called with the plan's flags in box mode, the code reaches the box's screen (the issue file), the owner
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

import yaml
from console.app import create_app
from console.auth import UserStore
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog

from tests.console.test_console_app import PILOT_ENV, FakeBackend
from tests.console.test_firstrun import HW, _answers

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
        f"printf 'POSTGRES_PASSWORD=made-by-install\\nTB_DB_PW_LAKE=made-by-install\\n' > {deploy}/.env\n"
        "echo '  TrialBox is running.'\n"
        "echo 'install: FAIL: no backup yet' >&2\nexit 1\n",  # a FAIL list at the end: the stack is up
        encoding="utf-8",
    )
    for name in ("compose", "hostcheck"):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {calls}\n', encoding="utf-8")
    for f in stubs.iterdir():
        f.chmod(0o755)
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({**HW, "gpu_name": PRO6000, "gpu_mem_gib": 96.0}), encoding="utf-8")
    fr = tmp_path / "firstrun"
    env = {
        **os.environ, "TB_BOX_NO_ROOT": "1", "TB_BOX_HARDWARE": str(hw), "TB_BOX_INSTALL": str(install),
        "TB_BOX_PY": sys.executable, "TB_BOX_COMPOSE": str(stubs / "compose"),
        "TB_BOX_HOST_CHECK": str(stubs / "hostcheck"), "TB_ISSUE_DIR": str(tmp_path / "issue.d"),
        "TB_FIRSTRUN_HOST_DIR": str(fr), "TB_BOX_POLL_S": "0.2", "TB_SYSTEMD": "0",
    }  # fmt: skip
    bundle = tmp_path / "trialbox-1.0.0.tar"
    bundle.write_bytes(b"stand-in bundle")
    return {"box": box, "deploy": deploy, "calls": calls, "fr": fr, "bundle": bundle, "env": env,  # type: ignore[dict-item]
            "issue": tmp_path / "issue.d" / "trialbox-firstrun.issue"}  # fmt: skip


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
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env=t["env"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # fmt: skip
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
        r, _ = _answers(c)
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
    assert env["TB_BACKUP_TARGETS"] == "/srv/trialbox-backup" and env["TB_TZ"] == "Asia/Tokyo"
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
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)  # fmt: skip
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
    """The script's output up to the line that holds the one-time code."""
    assert proc.stdout is not None
    seen = ""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        line = proc.stdout.readline()
        if not line:
            break
        seen += line
        if "One-time code:" in line:
            return seen
    raise AssertionError(f"no code on the output:\n{seen[-2000:]}")


def test_under_wsl2_the_code_is_on_the_output_and_no_issue_file_is_written(tmp_path: Path) -> None:
    """No screen shows /etc/issue.d under WSL2; the Windows installer's window shows the script's output."""
    t: dict[str, Any] = _tree(tmp_path)
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env={**t["env"], "TB_BOX_WSL2": "1"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)  # fmt: skip
    try:
        out = _until_code(proc)
        assert "TrialBox set-up:  https://box1.local/login/first-run" in out
        assert re.search(r"One-time code:\s+\S+", out)
        assert (t["fr"] / "code.json").is_file()  # the wizard is waiting for that code
        assert not t["issue"].exists() and not t["issue"].parent.exists()
    finally:
        proc.kill()
        proc.communicate()


def test_off_wsl2_the_code_is_on_the_output_and_on_the_boxs_screen(tmp_path: Path) -> None:
    t: dict[str, Any] = _tree(tmp_path)
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env={**t["env"], "TB_BOX_WSL2": "0"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)  # fmt: skip
    try:
        out = _until_code(proc)
        screen = _wait(t["issue"], proc)
        code = re.search(r"One-time code:\s+(\S+)", out)
        assert code and code.group(1) in screen and "https://box1.local/login/first-run" in screen
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
