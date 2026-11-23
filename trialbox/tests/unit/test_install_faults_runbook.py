"""Operator commands on a freshly installed box."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tools.support_bundle import SECRET_SETTINGS

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "docs/runbook"
secret_names = "|".join(re.escape(name) for name in (*SECRET_SETTINGS, "TB_DB_URL", "TB_HAPI_DB_URL"))
SECRET_ASSIGNMENT = (
    rf"\b(?:{secret_names}|"
    r"(?![A-Z0-9_]*_(?:FILE|DIR|PATH)=)[A-Z0-9_]*(?:PASS(?:WORD|PHRASE)?|TOKEN|SECRET|API_KEY|_PW)[A-Z0-9_]*)="
)
SUDO_SECRET = re.compile(r"\bsudo\s+[^\n`;&|]*?" + SECRET_ASSIGNMENT)


def test_runbook_never_puts_secret_assignments_in_sudo_arguments() -> None:
    for var in ("TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE", "TB_KMS_TOKEN", "TB_DB_PW_LAKE"):
        assert SUDO_SECRET.search(f"sudo -H env {var}=$value cmd")
    assert SUDO_SECRET.search("sudo TB_SOURCE_DSN=$dsn cmd")
    assert not SUDO_SECRET.search("sudo RESTIC_PASSWORD_FILE=$private_file cmd")
    for page in [ROOT / "docs/RUNBOOK.md", *PAGES.rglob("*.md")]:
        assert not SUDO_SECRET.search(page.read_text().replace("\\\n", " ")), page


def test_operator_docs_and_installer_help_keep_secrets_off_command_lines() -> None:
    # --from-file=NAME=path on kubectl names a stream or file, not a secret value.
    assignment = re.compile(r"(?<!--from-file=)" + SECRET_ASSIGNMENT)
    for cmd in (
        "export HF_TOKEN=value",
        "env TB_KMS_TOKEN=$token cmd",
        "sudo -E TB_SOURCE_DSN=$dsn cmd",
        "docker run --env=SMTP_PASS=value image",
        "TB_KEK_NEW_PASSPHRASE='value' cmd",
    ):
        assert assignment.search(cmd)
    pages = [
        ROOT / "docs/RUNBOOK.md",
        ROOT / "docs/SECURITY.md",
        *PAGES.rglob("*.md"),
        *(ROOT / "docs/security").rglob("*.md"),
    ]
    sources = {str(page): page.read_text() for page in pages}
    for script in ("deploy/install.sh", "deploy/box-install.sh", "deploy/bootstrap.sh"):
        sources[script] = subprocess.check_output(["bash", script, "--help"], cwd=ROOT, text=True)
    for source, content in sources.items():
        assert not assignment.search(content.replace("\\\n", " ")), source


def test_unattended_runbook_and_help_pass_only_the_exported_name() -> None:
    """H-96 (the integrator's ruling 7094934985): the passphrase goes in a file only root can read, then its name goes
    on the command line; never --preserve-env (sudo logs a kept variable with its value)."""
    help_text = subprocess.check_output(["bash", "deploy/box-install.sh", "--help"], cwd=ROOT, text=True)
    for text in (help_text, next(PAGES.glob("16-*")).read_text()):
        instructions = [
            "umask 077; IFS= read -rs TB_KEK_PASSPHRASE; printf",
            "> /root/trialbox-kek.pass",
            "deploy/box-install.sh \"$bundle\" --answers owner.json --kek-passphrase-file /root/trialbox-kek.pass",
        ]
        positions = [text.index(instruction) for instruction in instructions]
        assert positions == sorted(positions) and "--kek-passphrase-stdin" in text
        assert "--preserve-env=TB_KEK" not in text and "export TB_KEK_PASSPHRASE" not in text


def test_installers_reject_passphrase_file_input() -> None:
    for script in ("deploy/install.sh", "deploy/box-install.sh", "deploy/hardening/seal_keys.sh"):
        result = subprocess.run(
            ["bash", script, "--passphrase-file", "unused"], cwd=ROOT, capture_output=True, check=False
        )
        assert result.returncode == 2 and b"unknown option" in result.stderr


def test_restore_runbook_offers_the_public_command() -> None:
    from console.ops_pages import DRILL_CMD

    assert "trialbox restore-drill <backup file> --key <key>" in next(PAGES.glob("05-*")).read_text()
    assert DRILL_CMD.startswith("trialbox restore-drill {file} --key ")


def test_installer_cleans_its_project_before_using_the_network() -> None:
    script = (ROOT / "deploy/install.sh").read_text()
    down = script.index('"${COMPOSE[@]}" down --remove-orphans')
    assert down < script.index('"${COMPOSE[@]}" run --rm --no-deps -T adapter')
    assert down < script.index('"${COMPOSE[@]}" up -d --pull "$PULL" --wait db')
    assert script[down:].splitlines()[0].split(" ||")[0].endswith("down --remove-orphans")
    help_plan = subprocess.check_output(["bash", "deploy/install.sh", "--help"], cwd=ROOT, text=True)
    assert "down --remove-orphans" in help_plan
    assert "COMPOSE+=(--profile '*')" in script[:down]
    assert "docker compose --project-directory deploy" in script
    assert "name: trialbox" in (ROOT / "deploy/docker-compose.yml").read_text()
    assert "down --remove-orphans" in next(PAGES.glob("01-*")).read_text()


def test_restore_runbook_uses_installed_box_runtime() -> None:
    page = next(PAGES.glob("05-*")).read_text()
    drill = page.split("**Restore drill", 1)[1].split("**Restore.**", 1)[0]
    assert "trialbox restore-drill <backup file> --key <key>" in drill
    assert "pg_restore" in drill and "zstandard" in drill


def test_restore_box_entry_point_needs_no_host_python_packages(tmp_path: Path) -> None:
    import sys

    launcher = tmp_path / "trialbox"
    launcher.symlink_to(ROOT / "tools/trialbox/__main__.py")
    assert (
        'ln -sfnT "$ROOT/tools/trialbox/__main__.py" /usr/local/bin/trialbox'
        in (ROOT / "deploy/install.sh").read_text()
    )
    # -S leaves out every package installed by the product's lock, including zstandard and psycopg.
    res = subprocess.run(
        [
            sys.executable,
            "-IS",
            str(launcher),
            "restore-drill",
            "backup",
            "--key",
            "key",
            "--deploy",
            str(tmp_path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert res.returncode == 2 and "TB_DB_URL" in res.stderr
    assert "ModuleNotFoundError" not in res.stderr
    assert "zstandard==" in (ROOT / "deploy/requirements.lock").read_text()
    assert "deploy/requirements.lock" in (ROOT / "deploy/docker/python.Dockerfile").read_text()
