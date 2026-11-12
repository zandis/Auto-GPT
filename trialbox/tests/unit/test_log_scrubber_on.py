"""T-212d (D-450, PV-10): every service starts with every scrubber rule on: a planted chart number and a planted
token never reach its log, whichever entry point compose starts it with."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import logging as tblog

ROOT = Path(__file__).resolve().parents[2]
CHART = "12345678"  # the contract's default chart-number pattern (^\d{8}$): synthetic
TOKEN = "planted-token-Zq81xR0vK2"  # synthetic, held by the process as a mounted secret file
OTHER = "Wv93kLm0Pq7s"  # synthetic, written after a secret's name

PROBE = f"logging.getLogger('probe').error('chart {CHART} seen; token {TOKEN}; api_key={OTHER}')"
# (name, the start code as compose runs it (deploy/docker-compose.yml command))
ENTRY_POINTS = [
    ("orchestrator", "import orchestrator.app"),
    ("lake", "import lake.app"),
    ("embed-service", "import embed_service.app"),
    ("doc-parser", "import doc_parser.app"),
    ("criteria-compiler", "import criteria_compiler.app"),
    ("adapter", "import adapter.app"),
    ("mail-gateway", "import mail_gateway.app"),
    ("llm-stub", "import llm_stub.app"),
    ("gateway", "import gateway.app; gateway.app.create_app()"),
    # the console's factory reaches the trial database after it has set up logging; the probe runs either way
    ("console", "import console.app\ntry:\n    console.app.create_app()\nexcept Exception:\n    pass"),
    ("audit-writer", "import tb_common.audit_writer as w; w.main(['drain', '--once'])"),
]


@pytest.mark.parametrize(("service", "start"), ENTRY_POINTS, ids=[e[0] for e in ENTRY_POINTS])
def test_a_planted_chart_number_and_token_do_not_reach_the_log(service: str, start: str, tmp_path: Path) -> None:
    tok = tmp_path / "tb_service_token"
    tok.write_text(TOKEN + "\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_DB_URL", "TB_SERVICE_TOKEN"))}
    env.update({"TB_ENV": "DEV", "PYTHONPATH": "libs:services:.", "TB_SERVICE_TOKEN_FILE": str(tok),
                "TB_SERVICE_NAME": service, "TB_TEST_ROOT": str(tmp_path)})  # fmt: skip
    # the folders compose mounts at /data/... (the audit journal, the console's, the operations folder): here, so the
    # entry point starts as a user that cannot write /data (CI), not only as root
    env.update(
        {
            k: str(tmp_path / k.lower())
            for k in ("TB_AUDIT_DIR", "TB_CONSOLE_DIR", "TB_OPS_DIR", "TB_DATA_DIR", "TB_LAKE_DIR", "TB_RULESETS_DIR")
        }
    )
    code = f"import logging\n{start}\n{PROBE}\n"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=120, check=False)  # fmt: skip
    text = out.stdout + out.stderr
    probe = [ln for ln in text.splitlines() if '"probe"' in ln]
    assert probe, f"{service}: no JSON log line from the probe:\n{text[-2000:]}"
    assert CHART not in text and TOKEN not in text and OTHER not in text, text[-2000:]
    assert "[MRN]" in probe[0] and probe[0].count("[SECRET]") == 2, probe[0]
    assert f'"service": "{service}"' in probe[0]


def test_model_guard_request_lines_are_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    import model_guard

    g = model_guard.Guard(TOKEN, {"llm-service": ("llm-service-vllm", 8000)})
    model_guard.scrub_setup(g.key)
    handler = model_guard.make_handler(g)
    handler.log_message(None, '"%s" %s %s', f"GET /v1/models?mrn={CHART}&key={TOKEN} HTTP/1.1", "404", "-")  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert CHART not in err and TOKEN not in err and "model-guard" in err


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer "
        + ".".join(("eyJhbGciOiJSUzI1NiJ9", "e30", "c2lnbmF0dXJl")),  # built: not a literal token
        "X-TB-Service-Token: q8Zr0xKpL2",
        '{"client_secret": "s3cr3t-value"}',
        "postgresql://tb_lake:" + "pw-0123456@db:5432/trialbox_wf",  # built: not a literal credential
        "token=abcdef123456&x=1",
    ],
)
def test_secrets_after_their_name_are_scrubbed(line: str) -> None:
    out = tblog.redact(line)
    assert "[SECRET]" in out
    for secret in ("eyJhbGciOiJSUzI1NiJ9", "q8Zr0xKpL2", "s3cr3t-value", "pw-0123456", "abcdef123456"):
        assert secret not in out


def test_ordinary_words_are_kept() -> None:
    for line in ("token registry loaded", "password refused for the user", "bypass=on", "pid " + "a" * 32):
        assert tblog.redact(line) == line


def test_process_secrets_from_names_and_files(tmp_path: Path) -> None:
    f = tmp_path / "key"
    f.write_text("file-held-secret-01\n")
    n = tblog.register_process_secrets({"TB_LLM_API_KEY_FILE": str(f), "IMAP_PASS": "imap-pass-0123",
                                        "TB_SETTINGS_FILE": "/etc/x", "SHORT_KEY": "abc", "TB_ENV": "PRODUCTION"})  # fmt: skip
    assert n >= 0
    out = tblog.redact("a file-held-secret-01 b imap-pass-0123 c PRODUCTION abc")
    assert "file-held-secret-01" not in out and "imap-pass-0123" not in out and "PRODUCTION abc" in out


def test_the_chart_number_rule_follows_the_site(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import phi_guard

    monkeypatch.setattr(phi_guard, "site_mrn_regex", lambda: r"^H\d{6}$")
    assert tblog.site_rule_on() == r"^H\d{6}$"
    assert tblog.redact("chart H123456 seen") == "chart [MRN] seen"
    monkeypatch.setattr(phi_guard, "site_mrn_regex", lambda: None)
    assert tblog.site_rule_on() == r"^\d{8}$"  # no readable site configuration: the contract's default, never off
