"""SAE-MAILBOX (D-736; review LIFE-007): the installer asks for the trial office's mailbox.

When a serious adverse event is entered, the console mails the trial office at ``TB_SAE_OFFICE_MAILBOX``, without
the AE term; unset, nobody is told until the investigator's next working-day mail (LIFE-007: an SAE typed on Friday
evening, its 24-hour report due Saturday, the first mail on Monday). ``install.sh`` asks for it with the TLS name;
the answers file gives it as ``sae_office_mailbox`` (the settings wizard writes it), and an exported value counts.
The answer must be one plain mail address. A fresh PRODUCTION install stops without one and says why in a plain line;
a box installed by ``box-install.sh`` (``TB_BOX=1``) starts on provisional answers and the first-run page does not ask
it yet, and a re-run on a site that already has its settings must not stop a running site: both warn, and ``doctor``
WARNs on a PRODUCTION box without it. Other boxes say that nobody is mailed."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
MARK = "# SAE-MAILBOX (D-736): the trial office is told at once when a serious adverse event is entered (LIFE-007)"

pytestmark = pytest.mark.nodb


def _block() -> str:
    start = INSTALL.index(MARK)
    return INSTALL[start : INSTALL.index("\n# ---- end of " + MARK.removeprefix("# "), start)]


def _sh(
    tmp: Path, env: str, lines: str = "", box: str = "0", fresh: str = "1", exported: str | None = None
) -> subprocess.CompletedProcess[str]:
    (tmp / "deploy").mkdir(parents=True, exist_ok=True)
    (tmp / "deploy" / ".env").write_text(lines, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nYES=1\nTB_ENV_SITE={env}\nSETTINGS_NEW={fresh}\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'envset() { sed -i "/^$1=/d" deploy/.env && printf \'%s=%s\\n\' "$1" "$2" >> deploy/.env; }\n'
        f"{_block()}\n"
    )
    env_vars = {k: v for k, v in os.environ.items() if k not in ("TB_SAE_OFFICE_MAILBOX", "TB_BOX")}
    env_vars["TB_BOX"] = box  # as box-install.sh hands it on: in the environment
    if exported is not None:
        env_vars["TB_SAE_OFFICE_MAILBOX"] = exported
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
    assert (tmp_path / "deploy" / ".env").read_text().splitlines() == [
        "TB_SAE_OFFICE_MAILBOX=trial-office@hospital.example"
    ]


@pytest.mark.parametrize("bad", ["trial office", "office@", "@hospital.example", "a@b", "a@b.example,c@d.example",
                                 'a"@b.example', "a$b@x.tw", "a`id`@x.tw", "'x@y.tw", "a\\b@x.tw", "a@.x.tw",
                                 "a@b..tw", "a@b.tw.", "a@-b.tw"])  # fmt: skip
def test_anything_but_one_mail_address_stops(tmp_path: Path, bad: str) -> None:
    r = _sh(tmp_path, "TEST", f"TB_SAE_OFFICE_MAILBOX={bad}\n")
    assert r.returncode == 1 and "not one mail address" in r.stderr


@pytest.mark.parametrize("written", ['"trial-office@hospital.example"', "'trial-office@hospital.example'",
                                     " trial-office@hospital.example "])  # fmt: skip
def test_a_quoted_value_is_read_as_compose_reads_it_and_written_plain(tmp_path: Path, written: str) -> None:
    r = _sh(tmp_path, "PRODUCTION", f"TB_SAE_OFFICE_MAILBOX={written}\n")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "deploy" / ".env").read_text().splitlines() == [
        "TB_SAE_OFFICE_MAILBOX=trial-office@hospital.example"
    ]


def test_an_exported_value_counts_when_the_env_file_has_none(tmp_path: Path) -> None:
    r = _sh(tmp_path, "PRODUCTION", exported="trial-office@hospital.example")
    assert r.returncode == 0, r.stderr
    assert "TB_SAE_OFFICE_MAILBOX=trial-office@hospital.example" in (tmp_path / "deploy" / ".env").read_text()


def test_a_rerun_on_a_site_with_its_settings_warns_and_never_stops_it(tmp_path: Path) -> None:
    r = _sh(tmp_path, "PRODUCTION", fresh="0")
    assert r.returncode == 0, r.stderr
    assert "nobody is mailed" in r.stderr


def test_the_stop_names_the_answers_file_and_checks_the_wizard_s_pattern() -> None:
    from tools import settings_wizard as sw

    assert "sae_office_mailbox" in _block() and f'"{sw.MAILBOX_RE}"' in _block()


def test_the_settings_wizard_writes_the_answer(tmp_path: Path) -> None:
    from tools import settings_wizard as sw

    assert "sae_office_mailbox" in [f[0] for f in sw.QUESTIONS]
    base = yaml.safe_load((ROOT / "tools/rehearse_box/site_answers.yaml").read_text(encoding="utf-8"))
    maps = [ROOT / "tools/rehearse_box/mapping"]
    _, env, _ = sw.build({**base, "sae_office_mailbox": "trial-office@hospital.example"}, maps)
    assert env["TB_SAE_OFFICE_MAILBOX"] == "trial-office@hospital.example"
    _, env, warnings = sw.build({**base, "sae_office_mailbox": ""}, maps)
    assert "TB_SAE_OFFICE_MAILBOX" not in env and any("sae_office_mailbox" in w for w in warnings)
    with pytest.raises(sw.WizardError, match="sae_office_mailbox"):
        sw.build({**base, "sae_office_mailbox": "a$b@x.tw"}, maps)


def test_doctor_warns_on_a_production_box_without_the_mailbox() -> None:
    from tools.trialbox import doctor

    def one(env: dict[str, str]) -> doctor.Check:
        inp = doctor.DoctorInputs(env=env, host_tz="Asia/Taipei")
        return next(c for c in doctor.run(inp, (doctor.check_sae_mailbox,)) if c.name == "sae_mailbox")

    assert doctor.check_sae_mailbox in doctor.CHECKS
    c = one({"TB_ENV": "PRODUCTION"})
    assert c.status == "WARN" and "nobody is mailed" in c.detail
    assert one({"TB_ENV": "PRODUCTION", "TB_SAE_OFFICE_MAILBOX": "trial-office@hospital.example"}).status == "PASS"
    assert one({"TB_ENV": "PRODUCTION", "TB_SAE_OFFICE_MAILBOX": "a$b@x.tw"}).status == "WARN"
    assert one({"TB_ENV": "DEV"}).status == "PASS"
