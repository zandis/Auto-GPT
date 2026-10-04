"""In-process TrialBox for integration tests: real mail-gateway intake/outbound, orchestrator, scenarios, compiler
(fake CQL translator + equivalence), stub LLM, and a lake loaded with synthetic data (CPU CI)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import tb_contracts as c
from criteria_compiler.ctgov import CtGov
from criteria_compiler.repo import RulesetRepo
from criteria_compiler.service import Compiler, CompilerDeps
from criteria_compiler.terminology.mapper import Terminology
from doc_parser.parser import parse
from embed_service.embedder import HashEmbedder
from fastapi.testclient import TestClient
from lake.client import LakeLocal
from llm_stub.app import app as stub
from mail_gateway.gateway import Gateway
from mail_gateway.store import MailDB
from orchestrator.core import Orchestrator, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import registry
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.llm import LlmClient
from tb_common.objstore import FsStore

from tests.unit.test_compiler_service import FakeGate, FakeTranslator

ROOT = Path(__file__).resolve().parents[1]
AUTH = "mx.hospa.test; spf=pass smtp.mailfrom=hospa.test; dkim=pass header.d=hospa.test; dmarc=pass"


@dataclass
class Sent:
    to: list[str]
    msg: EmailMessage

    @property
    def subject(self) -> str:
        return str(self.msg["Subject"])

    def attachments(self) -> dict[str, bytes]:
        out = {}
        for part in self.msg.iter_attachments():
            data = part.get_payload(decode=True)
            assert isinstance(data, bytes)
            out[str(part.get_filename())] = data
        return out

    def text(self) -> str:
        body = self.msg.get_body(("plain",))
        return str(body.get_content()) if body is not None else ""


@dataclass
class Box:
    gw: Gateway
    orch: Orchestrator
    store: FsStore
    audit_dir: Path
    sent: list[Sent] = field(default_factory=list)
    today: list[date] = field(default_factory=lambda: [date(2026, 10, 5)])

    def mail(
        self,
        subject: str,
        attachments: tuple[tuple[str, bytes], ...] = (),
        sender: str = "crc1@hospa.test",
        in_reply_to: str | None = None,
        auth: str = AUTH,
    ) -> str:
        m = EmailMessage()
        m["From"] = f"CRC <{sender}>"
        m["To"] = "trialbox@hospa.test"
        m["Subject"] = subject
        m["Message-ID"] = make_msgid(domain="hospa.test")
        if auth:
            m["Authentication-Results"] = auth
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
        m.set_content("Request from the CRC office.")
        for name, data in attachments:
            m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
        folder = self.gw.handle(m.as_bytes(policy=policy.SMTP))
        assert folder is not None
        return folder

    def find(self, prefix: str) -> list[Sent]:
        return [s for s in self.sent if s.subject.startswith(prefix)]


class InprocParser:
    def __init__(self, store: FsStore) -> None:
        self.store = store

    def parse(self, req: c.ParseRequest) -> c.ParsedDoc:
        return parse(self.store.get(req.minio_key), req.minio_key.rsplit("/", 1)[-1])


SITE_B: dict[str, Any] = {  # the alliance member box (synthetic hospital B) for COHORT MERGE tests
    "site": {"id": "DEMO-B", "name": "示範醫院B (synthetic)", "tz": "Asia/Taipei", "contact": "crc1@hospb.test"},
    "internal_domains": ["hospb.test"],
    "allowlist": {"senders": ["crc1@hospb.test"], "physicians": [], "alliance_sites": []},
    "reviewers": ["crc1@hospb.test"],
    "cohort": {"alliance_root": False, "root_address": "trialbox@hospa.test", "rulesets": ["GOUT-COH"]},
}


def make_box(
    tmp_path: Path,
    lake_dir: Path,
    secrets_dir: Path,
    today: date = date(2026, 10, 5),
    settings_update: Mapping[str, Any] | None = None,
) -> Box:
    upd = settings_update or {}
    domain = str((upd.get("internal_domains") or ["hospa.test"])[0])
    env = load_env(
        dotenv=tmp_path / "none.env",
        environ={
            "MAIL_FROM_ADDR": f"trialbox@{domain}",
            "MAIL_INTAKE_ADDR": f"trialbox@{domain}",
            "TB_SECRETS_DIR": str(secrets_dir),
        },
    )
    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    if upd:
        settings = c.Settings.model_validate({**settings.model_dump(mode="json", exclude_none=True), **upd})
    cfg = Config(env=env, settings=settings)
    store = FsStore(tmp_path / "obj")
    audit_dir = tmp_path / "audit"
    audit = AuditLog(audit_dir)
    seed = tmp_path / "seed"
    shutil.copytree(ROOT / "rulesets", seed, ignore=shutil.ignore_patterns("tests"))
    llm = LlmClient("http://stub/v1", "stub", audit=audit)
    llm.http = TestClient(stub)
    comp = Compiler(
        CompilerDeps(
            store=store,
            repo=RulesetRepo(tmp_path / "repo", seed),
            llm=llm,
            term=Terminology(),
            settings_thresholds={"equivalence_min_pct": 98.0},
            translator=FakeTranslator(),  # type: ignore[arg-type]
            audit=audit,
            equivalence=FakeGate(),
            mrn_regex=r"^\d{8}$",
            ctgov=CtGov(mode="cassette"),
        )
    )
    holder: dict[str, Orchestrator] = {}
    box_today = [today]
    sent: list[Sent] = []

    def transport(_frm: str, to: list[str], data: bytes) -> None:
        msg = message_from_bytes(data, policy=policy.default)
        assert isinstance(msg, EmailMessage)
        sent.append(Sent(to, msg))

    gw = Gateway(
        cfg,
        store,
        MailDB(tmp_path / "mail.sqlite"),
        audit,
        transport,
        jobs=lambda req: holder["o"].create(req),  # noqa: PLW0108 - orchestrator is created below
        secrets_dir=tmp_path,
    )
    services = Services(
        lake=LakeLocal(lake_dir, HashEmbedder()), parser=InprocParser(store), compiler=comp, mail=gw, llm=llm
    )
    orch = Orchestrator(
        cfg,
        JobDB(tmp_path / "jobs.sqlite"),
        store,
        audit,
        services,
        registry(),
        tmp_path / "repo",
        tmp_path / "orch",
        today=lambda: box_today[0],
        workers=0,
        async_notify=False,
    )
    holder["o"] = orch
    return Box(gw, orch, store, audit_dir, sent, box_today)


def ingest_site(src: Path, lake_dir: Path, secrets_dir: Path, snapshot: str, site_id: str = "DEMO-A") -> c.IngestReport:
    """CSV source -> NDJSON -> lake snapshot (hash embedder), as the nightly adapter run does (no fhir-store)."""
    from adapter.pipeline import AdapterConfig, run_ingest
    from lake.store import Lake

    def rebuild(snap: str, nd: Path) -> c.RebuildResult:
        st = Lake(lake_dir).rebuild(snap, HashEmbedder(), nd)
        return c.RebuildResult(
            snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new, seconds=st.seconds
        )

    cfg = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=secrets_dir,
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id=site_id,
        audit_dir=lake_dir / "audit",
        rebuild=rebuild,
    )
    return run_ingest(cfg, "csv", str(src), snapshot=snapshot, load_fhir=False, validate=False)


def unzip_phi(box: Box, mail: Sent) -> dict[str, bytes]:
    """Decrypt a 7z PHI attachment with the password mailed separately to the same recipient."""
    import io

    import py7zr

    ((name, data),) = mail.attachments().items()
    assert name.endswith(".7z")
    pw_mail = next(
        s
        for s in box.sent
        if s.subject.startswith("Password") and str(mail.msg["Subject"]) in s.subject and s.to == mail.to[:1]
    )
    password = next(ln.strip() for ln in pw_mail.text().splitlines() if ln.startswith("    "))
    import tempfile

    with tempfile.TemporaryDirectory() as td, py7zr.SevenZipFile(io.BytesIO(data), password=password) as z:
        z.extractall(td)
        return {p.name: p.read_bytes() for p in Path(td).rglob("*") if p.is_file()}
