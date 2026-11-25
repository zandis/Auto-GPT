"""In-process TrialBox for integration tests: real mail-gateway intake/outbound, orchestrator, scenarios, compiler
(fake CQL translator + equivalence), stub LLM, and a lake loaded with synthetic data (CPU CI)."""

from __future__ import annotations

import hashlib
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
from tb_common.subject import is_job_mail

from tests.rulesets_guard import approve_at_site, copy_rulesets
from tests.unit.test_compiler_service import FakeGate, FakeTranslator

ROOT = Path(__file__).resolve().parents[1]
AUTH = "mx.hospa.test; spf=pass smtp.mailfrom=hospa.test; dkim=pass header.d=hospa.test; dmarc=pass"


#: who approved the example studies of a synthetic in-process box (D-640; the tag reads "... approved by <this>")
SYNTHETIC_APPROVER = "synthetic-box@hospa.test"


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

    def find_job(self, kind: str, job_id: str) -> list[Sent]:
        """The box's ``kind`` replies (received, done, failed) about ``job_id``."""
        return [s for s in self.sent if is_job_mail(s.subject, kind, job_id)]


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


def _add_list_to(seed: Path, mailboxes: tuple[str, ...]) -> None:
    """D-758: the demo's people named recipients of every study's lists and CASE sheets (synthetic data only)."""
    import yaml

    if not mailboxes:
        return
    # the approved versions' manifests, and the site profiles a new draft takes its routing from
    for manifest in [*sorted(seed.glob("*/manifest.yaml")), *sorted(seed.glob("profiles/*.yaml"))]:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        routing = doc.get("routing")
        if not isinstance(routing, dict):
            continue
        have = [str(a) for a in routing.get("list_to") or []]
        routing["list_to"] = have + [m for m in mailboxes if m not in have]
        manifest.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def make_box(
    tmp_path: Path,
    lake_dir: Path,
    secrets_dir: Path,
    today: date = date(2026, 10, 5),
    settings_update: Mapping[str, Any] | None = None,
    extra_profiles: Path | None = None,
    extra_list_to: tuple[str, ...] = (),
    extra_env: Mapping[str, str] | None = None,
) -> Box:
    """``extra_profiles``: a folder of ``<RULESET>.yaml`` site profiles added to the seed (studies that exist only for
    a test, such as the public-data studies of ``tools.public_site``). ``extra_list_to``: mailboxes added to every
    ruleset's internal ``routing.list_to`` before the repository is made (the demo's people, D-758). ``extra_env``:
    more ``TB_*`` settings of the box."""
    from tools import pglocal

    pglocal.for_work(tmp_path)  # D-126: the box's trial database (TB_DB_URL, or a local throwaway one)
    upd = settings_update or {}
    domain = str((upd.get("internal_domains") or ["hospa.test"])[0])
    env = load_env(
        dotenv=tmp_path / "none.env",
        environ={
            "MAIL_FROM_ADDR": f"trialbox@{domain}",
            "MAIL_INTAKE_ADDR": f"trialbox@{domain}",
            "TB_SECRETS_DIR": str(secrets_dir),
            "TB_CONSOLE_URL": f"https://trialbox.{domain}",  # link mode (D-369) points here
            **(extra_env or {}),  # e.g. the alliance key settings of D-1226
        },
    )
    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    if upd:
        settings = c.Settings.model_validate({**settings.model_dump(mode="json", exclude_none=True), **upd})
    cfg = Config(env=env, settings=settings)
    store = FsStore(tmp_path / "obj", secrets_dir)  # sealed when the test sealed it (T-210c)
    audit_dir = tmp_path / "audit"
    audit = AuditLog(audit_dir)
    seed = tmp_path / "seed"
    if not seed.exists():  # a box reopened on its own folder (the demo's --keep, T-505b) keeps its repo and seed
        copy_rulesets(seed, "tests")
        _add_list_to(seed, extra_list_to)
    if extra_profiles is not None:
        for f in sorted(extra_profiles.glob("*.yaml")):
            shutil.copy2(f, seed / "profiles" / f.name)
    llm = LlmClient("http://stub/v1", "stub", audit=audit)
    llm.http = TestClient(stub)
    repo = RulesetRepo(tmp_path / "repo", seed)
    # D-640: a box that is not DEV or TEST runs no study on the approval seeding left. The demo tools run this
    # synthetic box with no TB_ENV (PRODUCTION by the one rule), so the box says who approved its example studies:
    # this builder, by name, on the tag, as a site's approval is written. Never a product path: a real box is not
    # built here. A box reopened on its own folder keeps the tags it has.
    approve_at_site(tmp_path / "repo", by=SYNTHETIC_APPROVER)
    comp = Compiler(
        CompilerDeps(
            store=store,
            repo=repo,
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
        MailDB(),
        audit,
        transport,
        jobs=lambda req: holder["o"].create(req),  # noqa: PLW0108 - orchestrator is created below
        secrets_dir=tmp_path,
        authserv_id=f"mx.{domain}",  # the hospital MTA of the test mails (AUTH); D-369: no authserv-id trusts nothing
        allow_phi_zip=True,  # a synthetic box: the tests open the zip (unzip_phi); a real box refuses it (D-369)
        outputs_current=lambda job_id, files: _outputs_current(
            holder["o"], job_id, files
        ),  # D-863: the orchestrator's answer
    )
    services = Services(
        lake=LakeLocal(lake_dir, HashEmbedder()), parser=InprocParser(store), compiler=comp, mail=gw, llm=llm
    )
    orch = Orchestrator(
        cfg,
        # TB_DB_URL (pglocal.for_work above); each box its own job tables, as it had its own jobs.sqlite
        JobDB(schema="orch_" + hashlib.sha1(str(tmp_path.resolve()).encode()).hexdigest()[:10]),
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

    from tools import pglocal

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
        # the pid map's trial database: TB_DB_URL, or the run's schemas in a local throwaway one (as make_box)
        db_url=pglocal.for_work(lake_dir.parent),
        synthetic_source=True,  # M1: every in-process box is synthetic data
    )
    report = run_ingest(cfg, "csv", str(src), snapshot=snapshot, load_fhir=False, validate=False)
    if report.passed:  # D-442: the derive batch of the new snapshot, as the INGEST job runs it after a passed ingest
        from lake.client import LakeLocal
        from orchestrator import derive
        from tb_common.derived_store import mapping_version_of, run_batch

        st = derive.store(cfg.db_url)
        if st is not None:
            lake = LakeLocal(lake_dir, HashEmbedder())
            run_batch(st, lake, mapping_version=mapping_version_of(lake, report.snapshot.isoformat()),
                      snapshot=report.snapshot.isoformat())  # fmt: skip
    return report


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


def _outputs_current(orch: Any, job_id: str, keys: list[str]) -> bool:
    """D-863: what ``GET /jobs/{job_id}/outputs-current`` answers, in process (the box's own orchestrator)."""
    from orchestrator.app import outputs_name_opted_out
    from orchestrator.decision_context import register_now

    job = orch.db.get(job_id)
    if job is None:
        raise KeyError(job_id)
    return not outputs_name_opted_out(orch, job, frozenset(register_now()), keys or None)
