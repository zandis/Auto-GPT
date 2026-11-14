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

SECRETS = sb.SECRET_SETTINGS
#: names the broad pattern below finds that hold a path, a mode or a list of files, never a secret's value
NOT_VALUES = re.compile(r"_(FILE|DIR|PATH|MODE)$|^TB_SERVICE_TOKENS$|_PW_$")
BROAD = re.compile(r"\b([A-Z][A-Z0-9_]*(?:PASS|_PW_|SECRET|TOKEN|PHRASE|_KEY|DSN|CREDENTIAL)[A-Z0-9_]*)\b")


def test_the_list_of_secret_settings_is_complete() -> None:
    found: set[str] = set()
    for path in [ROOT / ".env.example", ROOT / "libs/tb_common/config.py", ROOT / "deploy/install.sh",
                 *sorted((ROOT / "deploy").glob("docker-compose*.yml"))]:  # fmt: skip
        found |= set(BROAD.findall(path.read_text(encoding="utf-8")))
    missing = sorted(n for n in found if not NOT_VALUES.search(n) and n not in SECRETS and n not in sb.NOT_SECRETS)
    assert missing == [], "a setting that holds a secret: add it to SECRET_SETTINGS (or NOT_SECRETS, with why)"


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


# --------------------------------------------------------------------------------------- found by the review
def _one_box(tmp_path: Path, env_lines: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    for k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR", *SECRETS):
        monkeypatch.delenv(k, raising=False)
    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / ".env").write_text(f"TB_TZ=Asia/Taipei\nTB_LOG_DIR={tmp_path / 'logs'}\n" + env_lines, encoding="utf-8")
    (deploy / "settings.yaml").write_text('mrn_regex: "^\\\\d{8}$"\n', encoding="utf-8")
    return deploy


def _printing(*texts: str) -> sb.Runner:
    def run(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        return 0, "\n".join(texts) + "\n"

    return run


def test_a_value_with_a_comment_after_it_is_found_as_compose_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value searched for was "smtpPW-Alpha9 # rotated", while compose (and the service, and its log) used
    "smtpPW-Alpha9"; and a quoted value kept its backslash."""
    deploy = _one_box(tmp_path, 'SMTP_PASS=smtpPW-Alpha9 # rotated 2026-11\nIMAP_PASS="imap\\"Quote7"\n', monkeypatch)
    out = sb.build(deploy, tmp_path / "usb", runner=_printing("login smtpPW-Alpha9", 'imap login imap"Quote7'),
                   now=NOW, say=lambda _: None)  # fmt: skip
    text = _archive_text(out)
    assert "smtpPW-Alpha9" not in text and 'imap"Quote7' not in text


def test_settings_that_are_not_secrets_keep_their_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Found by the review: a name that only LOOKS secret-like (AUTH, COOKIE, KEY) had its value replaced in every
    file: `true` in every JSON file, every `512m` memory limit, the auth host name, the GPU profile's name."""
    deploy = _one_box(tmp_path, "TB_CONSOLE_SECURE_COOKIE=true\nTB_MAIL_AUTHSERV_ID=mx.hospa.test\n"
                                "TB_MEM_AUTHELIA=512m\nTB_GPU_KEY=rtxpro6000\nPOSTGRES_PASSWORD=postgres-Pw-91\n",
                      monkeypatch)  # fmt: skip
    seen = '{"ok": true, "mem_limit": "512m", "authserv": "mx.hospa.test", "gpu": "rtxpro6000"}'
    out = sb.build(deploy, tmp_path / "usb", runner=_printing(seen, "pw postgres-Pw-91"), now=NOW, say=lambda _: None)
    text = _archive_text(out)
    assert seen in text and "postgres-Pw-91" not in text


def test_a_value_as_json_writes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    deploy = _one_box(tmp_path, "TB_KMS_TOKEN=kms\\tok/en-55\n", monkeypatch)
    value = "kms\\tok/en-55"
    out = sb.build(deploy, tmp_path / "usb", runner=_printing(json.dumps({"sent": value})), now=NOW,
                   say=lambda _: None)  # fmt: skip
    text = _archive_text(out)
    assert json.dumps(value)[1:-1] not in text and value not in text


def test_a_secret_that_is_only_in_a_file_is_found_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Most of a box's secrets are files (service tokens, the model key, the actor key), not settings. Their values
    are read to be looked for; the files themselves never go in a bundle."""
    deploy = _one_box(tmp_path, "", monkeypatch)
    (deploy / "secrets" / "services").mkdir()
    (deploy / "secrets" / "services" / "orchestrator.token").write_text("tok-orch-7f3a9c1e5d\n", encoding="utf-8")
    (deploy / "secrets" / "model").mkdir()
    (deploy / "secrets" / "model" / "vllm.env").write_text("VLLM_API_KEY=vllm-key-c0ffee11\n", encoding="utf-8")
    (deploy / "secrets" / "backup.pub").write_text("public\n", encoding="utf-8")  # public: never searched for
    out = sb.build(deploy, tmp_path / "usb", runner=_printing("Bearer tok-orch-7f3a9c1e5d", "key vllm-key-c0ffee11",
                                                              "a public key"),
                   now=NOW, say=lambda _: None)  # fmt: skip
    text = _archive_text(out)
    assert "tok-orch-7f3a9c1e5d" not in text and "vllm-key-c0ffee11" not in text and "a public key" in text
