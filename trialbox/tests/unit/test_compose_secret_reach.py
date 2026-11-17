"""T-212d (D-450, OPS-057): which secret reaches which container.

Every TrialBox service reads ``deploy/.env`` through ``env_file``, and the secrets overlay clears per service what it
must not hold. This renders the box's compose file sets with ``docker compose config`` (no daemon needed), every
secret the box knows set to its own marker, and fails when a marker appears in the environment of a service that is
not on that secret's list below, under any variable name (``TB_DB_URL`` carries a password too). The secrets it
checks are every name of ``.env.example``, every ``TB_*`` setting declared in ``tb_common.config`` and every
variable the compose files interpolate, named like a password, key, token or secret: a new declared secret fails
here until the overlay clears it or the list names its service.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
SECRETISH = re.compile(r"PASS|KEY|TOKEN|SECRET|_PW_|_PW$")
NOT_SECRET = {
    "ATTACH_PASSWORD_MODE",  # a mode (link or zip)
    "TB_BACKUP_PUBKEY",  # a public key's path
    "TB_OIDC_CLIENT_SECRET",  # the host path of the secret file compose mounts (docker-compose.identity.yml)
    "TB_SERVICE_TOKENS",  # the path of the registry of token hashes
    "TB_VENDOR_KEY_SM_NAME",  # the NAME of a Secret Manager secret (box run, R2): the driver's, never on a box
}
SERVICES_DB_PW = {
    "lake": "TB_DB_PW_LAKE", "criteria-compiler": "TB_DB_PW_CRITERIA_COMPILER", "adapter": "TB_DB_PW_ADAPTER",
    "orchestrator": "TB_DB_PW_ORCHESTRATOR", "mail-gateway": "TB_DB_PW_MAIL_GATEWAY", "gateway": "TB_DB_PW_GATEWAY",
    "console": "TB_DB_PW_CONSOLE", "audit-writer": "TB_DB_PW_AUDIT_WRITER",
    "fhir-store": "TB_DB_PW_FHIR_STORE",  # NEW-TRUST-1 (D-541): its own role, the owner of `hapi` only
}  # fmt: skip
#: secret -> the services that may hold it (D-450). Anything else that holds it fails the test.
ALLOWED: dict[str, set[str]] = {
    "POSTGRES_PASSWORD": {"db"},  # D-541: the server only; the FHIR store no longer holds the superuser's
    "POSTGRES_WF_PASSWORD": {"db"},
    **{pw: {"db", svc} for svc, pw in SERVICES_DB_PW.items()},
    "IMAP_PASS": {"mail-gateway"},
    "SMTP_PASS": {"mail-gateway"},
    "CLOUD_LLM_API_KEY": {"gateway"},
    "OPENROUTER_API_KEY": {"gateway"},
    "TB_LLM_API_KEY": {"llm-service", "llm-verifier"},  # as VLLM_API_KEY, from secrets/model/vllm.env only
    "TB_KEK_PASSPHRASE": {"adapter", "orchestrator"},  # they unwrap the site keys (tb_common.kek)
    "TB_KMS_TOKEN": {"adapter", "orchestrator"},
    # the acceptance mirror (docker-compose.acceptance.yml): the test mail server and the mail gateway's login to it
    "TB_ACCEPTANCE_MAIL_PASSWORD": {"acceptance-mail", "mail-gateway"},
    "TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD": {"acceptance-mail"},
    # the console receives events, signs the EDC in and calls tools; both it and the orchestrator read projects
    "TB_EDC_EVENT_SECRET": {"console"},
    "TB_EDC_OIDC_CLIENT_SECRET": {"console"},
    "TB_EDC_TOOL_TOKEN": {"console"},
    "TB_EDC_INTERNAL_TOKEN": {"console", "orchestrator"},
    "TB_REDCAP_API_TOKEN": {"console", "orchestrator"},
    "TB_REDCAP_PROJECT_TOKENS": {"console", "orchestrator"},
}
BASE = ("docker-compose.yml", "docker-compose.secrets.yml")
STACKS = [
    (BASE, ("gpu", "stub")),
    ((*BASE, "docker-compose.gb10.yml"), ("gpu",)),
    ((*BASE, "docker-compose.rtx5090.yml"), ("gpu",)),
    ((*BASE, "docker-compose.rtxpro6000.yml"), ("gpu",)),
    ((*BASE, "docker-compose.shared-quota.yml"), ("gpu",)),
    ((*BASE, "docker-compose.identity.yml"), ("stub", "oidc")),
    ((*BASE, "docker-compose.monitoring.yml"), ("stub",)),
    ((*BASE, "docker-compose.identity.yml", "docker-compose.acceptance.yml"), ("stub", "oidc")),
]


def secret_names() -> set[str]:
    from tb_common.config import DECLARED

    names = {k for k, d in DECLARED.items() if SECRETISH.search(k) and d.kind != "path"}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        k = line.split("=", 1)[0].strip()
        if k and not k.startswith("#") and SECRETISH.search(k):
            names.add(k)
    for f in DEPLOY.glob("docker-compose*.yml"):
        names |= {n for n in re.findall(r"\$\{([A-Z0-9_]+)", f.read_text(encoding="utf-8")) if SECRETISH.search(n)}
    return {n for n in names if not n.endswith(("_FILE", "_DIR")) and n not in NOT_SECRET}


def _compose() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


def render(
    tmp: Path, stack: tuple[str, ...], profiles: tuple[str, ...], names: set[str]
) -> tuple[dict[str, Any], dict[str, str]]:
    for f in DEPLOY.glob("docker-compose*.yml"):
        shutil.copy(f, tmp / f.name)
    marks = {n: f"m4rk{i:03d}q" for i, n in enumerate(sorted(names))}
    lines = [f"{n}={m}" for n, m in marks.items()]
    # the host tools' database URL (install.sh): the workflow password inside it
    lines += [f"TB_DB_URL=postgresql://trialbox:{marks.get('POSTGRES_WF_PASSWORD', 'x')}@db:5432/trialbox_wf",
              "TB_TZ=Asia/Taipei", "TB_TLS_HOSTNAME=tb.test", "TB_ENV=PRODUCTION"]  # fmt: skip
    # the shared-quota file's required sizes (docker-compose.shared-quota.yml)
    lines += [f"{k}=1" for k in ("JUDGE_GPU_MEM_UTIL", "JUDGE_MAX_LEN", "JUDGE_MAX_SEQS", "VERIFIER_GPU_MEM_UTIL",
                                 "VERIFIER_MAX_LEN", "VERIFIER_MAX_SEQS")]  # fmt: skip
    lines += ["TB_MIG_PROFILE=1g.23gb", "TB_MIG_JUDGE_DEVICE=MIG-a", "TB_MIG_VERIFIER_DEVICE=MIG-b"]
    (tmp / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp / "secrets" / "model").mkdir(parents=True, exist_ok=True)
    (tmp / "secrets" / "model" / "vllm.env").write_text(f"VLLM_API_KEY={marks['TB_LLM_API_KEY']}\n")
    argv = ["docker", "compose", *(x for f in stack for x in ("-f", f)), *(x for p in profiles for x in ("--profile", p)),
            "config", "--format", "json"]  # fmt: skip
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp)}
    out = subprocess.run(argv, cwd=tmp, capture_output=True, text=True, timeout=120, check=False, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout), marks


def reach(doc: dict[str, Any], marks: dict[str, str]) -> dict[str, set[str]]:
    """secret -> the services whose environment holds its marker, under any name."""
    found: dict[str, set[str]] = {}
    for svc, body in (doc.get("services") or {}).items():
        env = json.dumps(body.get("environment") or {})
        for name, mark in marks.items():
            if mark in env:
                found.setdefault(name, set()).add(svc)
    return found


def problems(found: dict[str, set[str]]) -> list[str]:
    return [f"{n} reaches {sorted(s - ALLOWED.get(n, set()))}" for n, s in sorted(found.items())
            if s - ALLOWED.get(n, set())]  # fmt: skip


def test_the_secret_list_covers_the_box() -> None:
    names = secret_names()
    want = {"POSTGRES_PASSWORD", "IMAP_PASS", "TB_LLM_API_KEY", "TB_SERVICE_TOKEN", "TB_KMS_TOKEN",
            *SERVICES_DB_PW.values()}  # fmt: skip
    assert want <= names
    assert not names & NOT_SECRET


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
@pytest.mark.parametrize(("stack", "profiles"), STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x)
def test_no_secret_reaches_a_service_off_its_list(
    tmp_path: Path, stack: tuple[str, ...], profiles: tuple[str, ...]
) -> None:
    doc, marks = render(tmp_path, stack, profiles, secret_names())
    found = reach(doc, marks)
    assert problems(found) == []
    if "gpu" in profiles:  # the model key: in the vLLM servers from their env file, nowhere from deploy/.env
        assert found.get("TB_LLM_API_KEY", set()) >= {"llm-service"}


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
def test_a_new_secret_is_caught(tmp_path: Path) -> None:
    """The check itself: a secret the overlay does not clear, set in deploy/.env, is reported in every service that
    reads the file (why a new secret needs its line in the overlay, or a file of its own)."""
    doc, marks = render(tmp_path, BASE, ("stub",), secret_names() | {"TB_PLANTED_TOKEN"})
    bad = [p for p in problems(reach(doc, marks)) if p.startswith("TB_PLANTED_TOKEN ")]
    assert bad and "'orchestrator'" in bad[0] and "'console'" in bad[0]
