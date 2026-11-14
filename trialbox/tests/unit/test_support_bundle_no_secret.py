"""SUPPORT-SECRETS (D-723): no secret of the box leaves in a support bundle, whatever form it takes there.

The deep review of 2026-11-12 (OPS-002) and lane G's of 2026-11-13: the bundle redacted secrets by the NAME they
stand next to, and the name list knew PASSWORD and PASSWD only, so SMTP_PASS, IMAP_PASS, every TB_DB_PW_* and
TB_KEK_PASSPHRASE left the box in env.redacted and in `docker compose config`. A name list is never complete, and a
value can turn up where no name stands next to it (a command's output, a JSON detail, a URL). So the box's own
secret values are now looked for, and replaced, in every file of the bundle; and a bundle that still holds one is
not written. This test builds a bundle on a box with every secret setting set, in every form the commands could
print it, and looks for each value in the finished archive."""

from __future__ import annotations

import gzip
import re
import secrets
import tarfile
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import support_bundle as sb

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 14, 1, 0, tzinfo=UTC)

#: every setting of the tree that holds a secret's VALUE (not a path to one); a new one is added here, or the guard
#: below fails
SECRETS = (
    "IMAP_PASS", "SMTP_PASS", "CLOUD_LLM_API_KEY", "TB_LLM_API_KEY", "TB_SERVICE_TOKEN", "POSTGRES_PASSWORD",
    "POSTGRES_WF_PASSWORD", "TB_DB_PW_ADAPTER", "TB_DB_PW_AUDIT_WRITER", "TB_DB_PW_CONSOLE",
    "TB_DB_PW_CRITERIA_COMPILER", "TB_DB_PW_FHIR_STORE", "TB_DB_PW_GATEWAY", "TB_DB_PW_LAKE", "TB_DB_PW_MAIL_GATEWAY",
    "TB_DB_PW_ORCHESTRATOR", "TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD", "TB_ACCEPTANCE_MAIL_PASSWORD",
    "TB_DEMO_PASSWORD", "TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE", "TB_KMS_TOKEN", "TB_OIDC_CLIENT_SECRET",
    "TB_RC_CASSETTE_TOKEN", "OPENROUTER_API_KEY", "SPRING_DATASOURCE_PASSWORD", "TB_BAKEOFF_API_KEY", "VLLM_API_KEY",
)  # fmt: skip
#: names the broad pattern below finds that hold a path, a mode or a list of files, never a secret's value
NOT_VALUES = re.compile(r"_(FILE|DIR|PATH|MODE)$|^TB_SERVICE_TOKENS$|_PW_$")
BROAD = re.compile(r"\b([A-Z][A-Z0-9_]*(?:PASS|_PW_|SECRET|TOKEN|PHRASE|API_KEY)[A-Z0-9_]*)\b")


def test_the_list_of_secret_settings_is_complete() -> None:
    found: set[str] = set()
    for path in [ROOT / ".env.example", ROOT / "libs/tb_common/config.py", ROOT / "deploy/install.sh",
                 *sorted((ROOT / "deploy").glob("docker-compose*.yml"))]:  # fmt: skip
        found |= set(BROAD.findall(path.read_text(encoding="utf-8")))
    missing = sorted(n for n in found if not NOT_VALUES.search(n) and n not in SECRETS)
    assert missing == [], "a setting that holds a secret: add it to SECRETS here, and see that the bundle hides it"


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, str]]:
    for k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR", *SECRETS):
        monkeypatch.delenv(k, raising=False)
    values = {name: f"{name.lower()[:6]}-{secrets.token_urlsafe(18)}" for name in SECRETS}
    values["IMAP_PASS"] = "p@ss/w:rd+" + secrets.token_hex(6)  # a value a URL must encode
    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    logs = tmp_path / "logs"
    lines = ["TB_TZ=Asia/Taipei", f"TB_LOG_DIR={logs}", f"TB_AUDIT_HOST_DIR={tmp_path / 'audit'}"]
    lines += [f"{name}={value}" for name, value in values.items() if name != "TB_KEK_PASSPHRASE"]
    lines.append(f'TB_KEK_NEW_PASSPHRASE_QUOTED="{values["TB_KEK_NEW_PASSPHRASE"]}"')  # quoted, under another name
    (deploy / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("TB_KEK_PASSPHRASE", values["TB_KEK_PASSPHRASE"])  # typed in front of the command
    (deploy / "settings.yaml").write_text('mrn_regex: "^\\\\d{8}$"\n', encoding="utf-8")
    day = logs / "services" / "2026-11-13"
    day.mkdir(parents=True)
    with gzip.open(day / "console.log.gz", "wb") as fh:  # a service that logged a value it should not have
        fh.write(f"2026-11-13T01:00:00Z console | smtp login failed for {values['SMTP_PASS']}\n".encode())
    return deploy, values


def _runner(values: dict[str, str]) -> sb.Runner:
    """Every command prints every value, in the forms a command could: under its own name, under a name the
    redaction does not know, inside a URL (plain and percent-encoded), and inside JSON."""

    def run(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        out = []
        for name, value in values.items():
            out += [
                f"{name}: {value}",
                f"  - {name}={value}",
                f"  detail: the login with {value} was refused",
                f"  url: smtp://mailer:{value}@relay.example:587",
                f"  dsn: postgresql://tb:{urllib.parse.quote(value, safe='')}@db:5432/tb",
                f'  {{"error": "auth", "sent": "{value}"}}',
            ]
        if argv[0] == "docker" and len(argv) > 1 and argv[1] == "inspect":
            return 0, "/trialbox-console-1 restarts=0 status=running\n" + "\n".join(out) + "\n"
        return 0, "\n".join(out) + "\n"

    return run


def _archive_text(path: Path) -> str:
    parts = []
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            fh = tar.extractfile(m)
            if fh is not None:
                parts.append(m.name + "\n" + fh.read().decode("utf-8", errors="replace"))
    return "\n".join(parts)


def test_no_secret_value_is_in_the_bundle_in_any_form(box: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    deploy, values = box
    said: list[str] = []
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(values), now=NOW, say=said.append)
    text = _archive_text(out)
    for name, value in values.items():
        for form in (value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value)):
            assert form not in text, f"{name} is in the bundle ({form[:4]}...)"
    assert "env.redacted" in text and "[redacted]" in text  # the files are there, with the values replaced
    assert "secret value(s) of the box" in " ".join(said)


def test_a_bundle_that_still_holds_a_secret_is_not_written(
    box: tuple[Path, dict[str, str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last look is on the finished archive: if any value is still in it (a pass that missed a form), nothing
    is written."""
    deploy, values = box
    monkeypatch.setattr(sb, "hide_values", lambda text, _values: (text, 0))  # as if the pass had missed them all
    with pytest.raises(sb.BundleRefused) as stop:
        sb.build(deploy, tmp_path / "usb", runner=_runner(values), now=NOW, say=lambda _: None)
    assert "secret" in str(stop.value)
    for value in values.values():
        assert value not in str(stop.value)  # the refusal names settings, never a value
    assert not list((tmp_path / "usb").glob("*.tar.gz"))


def test_the_names_the_review_named_are_redacted_by_name_too() -> None:
    text = "SMTP_PASS=abc12345\nIMAP_PASS=abc12345\nTB_DB_PW_LAKE=abc12345\nTB_KEK_PASSPHRASE=abc12345\n"
    red, n = sb.redact_secrets(text)
    assert n == 4 and "abc12345" not in red


def test_the_manifest_names_each_file_as_it_left(box: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    """The values are replaced before the manifest is written: its checksum of each file is the file in the
    archive, not the file before the replacement."""
    import hashlib
    import json

    deploy, values = box
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(values), now=NOW, say=lambda _: None)
    with tarfile.open(out, "r:gz") as tar:
        files = {m.name.removeprefix("support/"): tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    manifest = json.loads(files["MANIFEST.json"])
    for row in manifest["files"]:
        assert hashlib.sha256(files[row["name"]]).hexdigest() == row["sha256"], row["name"]
    assert any("secrets_hidden" in v for v in manifest["changed"].values())
