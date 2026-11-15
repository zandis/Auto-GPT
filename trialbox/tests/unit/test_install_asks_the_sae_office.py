"""SAE-MAILBOX (D-736; review LIFE-007): the installer asks for the trial office's mailbox.

When a serious adverse event is entered, the console mails the trial office at ``TB_SAE_OFFICE_MAILBOX``, without
the AE term; unset, nobody is told until the investigator's next working-day mail (LIFE-007: an SAE typed on Friday
evening, its 24-hour report due Saturday, the first mail on Monday). ``install.sh`` asks for it with the TLS name;
the answer must be one mail address. A PRODUCTION install stops without one and says why in a plain line; a box
installed by ``box-install.sh`` (``TB_BOX=1``) starts on provisional answers, so there it is a warning line and the
owner's answers set it later. Other boxes say that nobody is mailed."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
MARK = "# SAE-MAILBOX (D-736): the trial office is told at once when a serious adverse event is entered (LIFE-007)"

pytestmark = pytest.mark.nodb


def _block() -> str:
    start = INSTALL.index(MARK)
    return INSTALL[start : INSTALL.index("\n# ---- end of " + MARK.removeprefix("# "), start)]


def _sh(tmp: Path, env: str, lines: str = "", box: str = "0") -> subprocess.CompletedProcess[str]:
    (tmp / "deploy").mkdir(parents=True, exist_ok=True)
    (tmp / "deploy" / ".env").write_text(lines, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nYES=1\nTB_ENV_SITE={env}\nTB_BOX={box}\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'envset() { sed -i "/^$1=/d" deploy/.env && printf \'%s=%s\\n\' "$1" "$2" >> deploy/.env; }\n'
        f"{_block()}\n"
    )
    env_vars = {k: v for k, v in os.environ.items() if k not in ("TB_SAE_OFFICE_MAILBOX", "TB_BOX")}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, env=env_vars,
                          stdin=subprocess.DEVNULL)  # fmt: skip


def test_the_question_sits_with_the_tls_name_and_is_asked_only_at_a_terminal() -> None:
    block = _block()
    assert INSTALL.index('TLS_HOST="$(envget TB_TLS_HOSTNAME)"') < INSTALL.index(MARK) < INSTALL.index("- 4. start\n")
    assert '[ "$YES" != 1 ] && [ -t 0 ]' in block and "serious adverse event" in block


def test_production_without_a_mailbox_stops_and_says_why(tmp_path: Path) -> None:
    r = _sh(tmp_path, "PRODUCTION")
    assert r.returncode == 1
    assert "TB_SAE_OFFICE_MAILBOX" in r.stderr and "serious adverse event" in r.stderr and "24 h" in r.stderr


def test_a_box_install_goes_on_with_a_warning_line(tmp_path: Path) -> None:
    r = _sh(tmp_path, "PRODUCTION", box="1")
    assert r.returncode == 0, r.stderr
    assert "nobody is mailed" in r.stderr and "TB_SAE_OFFICE_MAILBOX" in r.stderr


@pytest.mark.parametrize("env", ["DEV", "TEST", "VALIDATION"])
def test_other_boxes_go_on_and_say_nobody_is_mailed(tmp_path: Path, env: str) -> None:
    r = _sh(tmp_path, env)
    assert r.returncode == 0, r.stderr
    assert "nobody is mailed" in r.stderr


def test_a_mailbox_already_set_is_kept_and_named(tmp_path: Path) -> None:
    r = _sh(tmp_path, "PRODUCTION", "TB_SAE_OFFICE_MAILBOX=trial-office@hospital.example\n")
    assert r.returncode == 0, r.stderr
    assert "trial-office@hospital.example" in r.stdout
    assert (tmp_path / "deploy" / ".env").read_text().count("TB_SAE_OFFICE_MAILBOX=") == 1


@pytest.mark.parametrize("bad", ["trial office", "office@", "@hospital.example", "a@b", "a@b.example,c@d.example",
                                 'a"@b.example'])  # fmt: skip
def test_anything_but_one_mail_address_stops(tmp_path: Path, bad: str) -> None:
    r = _sh(tmp_path, "TEST", f"TB_SAE_OFFICE_MAILBOX={bad}\n")
    assert r.returncode == 1 and "not one mail address" in r.stderr
