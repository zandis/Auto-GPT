"""Gate 4's cross-path test (review 2026-11-22, sections 3.2 and 3.5): "can a list run on inputs the site did not
accept, by any road into the box?"

Synthetic studies and versions go through every entrance that can start a screening run: approved at the night,
approved during the day (through the compiler and through an approval re-run after a restart), approved with no
published generation, a tampered record, a stale record (a newer night that published nothing), scopes narrowed by
practitioner, window or department, and a restore whose audited hold could not be written. The invariants are read
from what is published and recorded (the record files, the clearance, the audit logs, the jobs, their outputs and
the candidate pool), never from a function's return:

- **admitted**: no run lists without an admission audit naming a record file that is accepted, issued and read;
- **same-decision**: the same inputs give the same decision on every entrance;
- **decision**: the decision is the one the gate exists for (each case says which);
- **nothing-published**: a refusal publishes no output, no stored file and no pool row;
- **audited**: every refusal and every issued record is in the audit log;
- **one-writer**: every record file was issued by gate 4's one function (its issue audit names its hash);
- **own-generation**: every record holds exactly the published rows of its own generation.

``tools/gate4_planted.py`` applies planted mistakes one at a time and checks that each turns this test red.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FEED = ROOT / "tests/fixtures/synthetic_patients/site-a"
SENDER = "crc1@hospa.test"
NIGHTS = ("2026-10-02", "2026-10-03", "2026-10-04")

#: every place in the product that makes a job, by the road this test drives for it. A new place fails the
#: enumeration test until it has a road here.
JOB_MAKERS = {
    "services/mail_gateway/intake.py": "mail",
    "services/orchestrator/core.py": "api",  # Orchestrator.retry_scheduled: through Orchestrator._admit, as create
    "services/orchestrator/scheduler.py": "api",  # the scheduler's jobs: Orchestrator.create (SCREEN is not scheduled)
    "services/orchestrator/night.py": "api",  # the night's chain: Orchestrator.create
    "services/console/step4.py": "api",  # the console posts to the orchestrator's POST /jobs: Orchestrator.create
    "services/console/proposals.py": "api",  # the console's proposed command line: POST /jobs
}
#: roads that run a SCREEN again without making a job
RUNS_AGAIN = {"restart": "a job interrupted after its admission runs again with its pinned options", "rerun": "rerun"}
ENTRANCES = ("mail", "api", "restart", "rerun")
#: every job type, by what gate 4 says of it. The patient-listing types other than SCREEN are still on the ratchet
#: (tools/screening_inputs_ratchet.json) and are not driven here.
JOB_TYPES = {
    "SCREEN": "admitted",
    "MICROBATCH": "ratchet",
    "COHORT": "ratchet",
    "NAV": "ratchet",
    "CASE": "ratchet",
    **dict.fromkeys(
        ("FEAS", "FEEDBACK", "CALIBRATION", "APPROVE", "STATUS", "CANCEL", "INGEST", "RETENTION", "SUBMIT"),
        "no patient list",
    ),
    **dict.fromkeys(("CONSENT", "RELEASE"), "no patient list"),
}


def _job_makers() -> set[str]:
    found = set()
    for top in ("services", "libs"):
        for path in sorted((ROOT / top).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                    if name == "JobCreate":
                        found.add(str(path.relative_to(ROOT)))
    return found


def test_every_entrance_has_a_road() -> None:
    from orchestrator.rerun import RERUNNABLE
    from orchestrator.scenarios import registry

    assert _job_makers() == set(JOB_MAKERS), "a place that makes jobs needs a road in this test (JOB_MAKERS)"
    assert set(JOB_MAKERS.values()) | set(RUNS_AGAIN) == set(ENTRANCES)
    assert "SCREEN" in RERUNNABLE
    assert set(registry()) == set(JOB_TYPES), "a new job type: say what gate 4 does with it (JOB_TYPES)"
    ratchet = json.loads((ROOT / "tools/screening_inputs_ratchet.json").read_text(encoding="utf-8"))
    files = {e["file"] for e in (ratchet if isinstance(ratchet, list) else ratchet.get("entries", []))}
    for kind, what in JOB_TYPES.items():
        if what == "ratchet":
            assert f"services/orchestrator/scenarios/{kind.lower()}.py" in files, f"{kind} lists patients ungated"


# --------------------------------------------------------------------------------------------------- the site


class Site:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from adapter import cli
        from console.sitestore import SiteStore
        from tb_common.flags import Flags

        from tests.inproc_box import make_box

        settings = yaml.safe_load((ROOT / "deploy/settings.example.yaml").read_bytes())
        settings["data_source"]["path"] = str(FEED)
        settings["registry_source"]["path"] = str(FEED / "registry.csv")
        path = tmp_path / "settings.yaml"
        path.write_text(yaml.safe_dump(settings))
        sec = tmp_path / "sec"
        env = {
            "TB_SETTINGS": str(path),
            "TB_SETTINGS_FILE": str(path),
            "TB_DATA_DIR": str(tmp_path),
            "TB_LAKE_DIR": str(tmp_path / "lake"),
            "TB_RULESETS_DIR": str(tmp_path / "box/repo"),
            "TB_SECRETS_DIR": str(sec),
            "TB_ADAPTER_LAKE": "local",
            "TB_LAKE_EMBEDDER": "hash",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        assert cli.main(["keys-init"]) == 0
        self.root = tmp_path
        self.env = env
        self.box = make_box(tmp_path / "box", tmp_path / "lake", sec, settings_update=settings, extra_env=env)
        Flags(url=self.box.orch.db.url, audit=self.box.orch.audit).seed()
        SiteStore(self.box.orch.db.url).close()
        self.cfg, _, _ = cli.build_config()
        self.audit_dirs = [self.box.audit_dir, Path(self.cfg.audit_dir)]

    def night(self, snapshot: str, publish: bool = True) -> str:
        from adapter.pipeline import run_ingest

        site = self.cfg.screening_site
        if not publish:
            self.cfg.screening_site = None  # a passed night that publishes no screening inputs
        try:
            report = run_ingest(self.cfg, "csv", str(FEED), snapshot=snapshot, validate=False, load_fhir=False)
        finally:
            self.cfg.screening_site = site
        assert report.passed, report.errors
        generation = self.box.orch.services.lake.generation()
        assert generation and generation.startswith(snapshot)
        return str(generation)

    # ------------------------------------------------------------------ what is recorded
    def events(self, name: str | None = None) -> list[dict[str, Any]]:
        out = []
        for folder in self.audit_dirs:
            for day in sorted(Path(folder).glob("*.jsonl")):
                for line in day.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        event = json.loads(line)
                        if name is None or event.get("event") == name:
                            out.append(event)
        return out

    def records(self) -> dict[Path, bytes]:
        base = self.root / "screening-inputs"
        return {p: p.read_bytes() for p in sorted(base.glob("*/*/*.json"))}

    def clearance(self) -> dict[str, Any]:
        from tb_common.screening_inputs import clearance_path

        path = clearance_path(self.root)
        return json.loads(path.read_bytes()) if path.exists() else {}

    # ------------------------------------------------------------------ the day approval
    def approve(self, study: str, version: str, road: str) -> Any:
        """A version approved during the day. ``compiler``: the APPROVE job with stand-ins for the reviewer's workbook
        and the compiler (the stand-in writes, tags and promotes as the compiler does); ``restarted``: the compiler had
        tagged the version and the APPROVE job is run again (the scenario's "already approved" road)."""
        from criteria_compiler.repo import RulesetRepo
        from orchestrator.scenarios import approve as scenario
        from tb_contracts import ApproveResult, JobCreate, JobFile

        box = self.box
        repo = RulesetRepo(box.orch.rulesets_dir)

        def tag() -> Any:
            prefix = f"{study}/"
            files = {p.removeprefix(prefix): b for p, b in repo.files("main", prefix).items()}
            manifest = yaml.safe_load(files["manifest.yaml"])
            manifest["version"] = version
            files["manifest.yaml"] = yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode()
            branch = f"draft/{study}/{version}"
            repo.write_dir(branch, "main", prefix, files, f"approve {study} v{version}", "pi@hospa.test")
            repo.tag(f"{study}/v{version}", branch, f"{study} v{version} approved by pi@hospa.test", "pi@hospa.test")
            repo.promote(study, f"{study}/v{version}", f"release {study}/v{version}", "pi@hospa.test")
            from tb_common.ruleset import Ruleset

            return Ruleset.load(Path(box.orch.rulesets_dir) / study).manifest

        if road == "restarted":
            tag()
        saved_parse = getattr(__import__("criteria_compiler.review", fromlist=["x"]), "parse_review_xlsx")
        saved_approve = box.orch.services.compiler.approve

        def stand_in(req: Any) -> Any:
            return ApproveResult(ruleset=req.ruleset, version=req.version, status="approved",
                                 tag=f"{req.ruleset}/v{req.version}", round=1, manifest=tag())  # fmt: skip

        import criteria_compiler.review as review

        review.parse_review_xlsx = lambda *_a, **_k: ({"ruleset": study, "version": version}, [])
        box.orch.services.compiler.approve = stand_in
        try:
            wb = box.store.put(f"inputs/review-{study}-{version}.xlsx", b"stand-in", "application/octet-stream")
            files = [JobFile(filename="review.xlsx", minio_key=str(wb or f"inputs/review-{study}-{version}.xlsx"),
                             sha256=hashlib.sha256(b"stand-in").hexdigest(), size=8)]  # fmt: skip
            job = box.orch.create(
                JobCreate(type="APPROVE", requested_by="pi@hospa.test", ruleset=study, options={"version": version},
                          inputs=files)  # fmt: skip
            )
            box.orch.drain()
        finally:
            review.parse_review_xlsx = saved_parse
            box.orch.services.compiler.approve = saved_approve
        del scenario
        done = box.orch.db.get(job.job_id)
        assert done is not None and done.state == "done", done.error if done else None
        return done

    # ------------------------------------------------------------------ a restore
    def restore_without_hold(self) -> str:
        """The trial database put back from a backup of this very night (the restore re-creates every table with
        the same rows), and the restore's audited hold could not be written (no audit folder)."""
        from tb_common.db import Database

        from tools.trialbox import backup

        with Database.connect(self.box.orch.db.url, "app") as db:
            s = f'"{db.schema}"'
            seq = db.fetchval("SELECT pg_get_serial_sequence(?, 'id')", (f"{s}.flag_event",))
            with db.transaction() as tx:
                tx.execute(f"ALTER TABLE {s}.flag_event RENAME TO flag_event_backup")
                tx.execute(f"CREATE TABLE {s}.flag_event (LIKE {s}.flag_event_backup INCLUDING ALL)")
                tx.execute(f"INSERT INTO {s}.flag_event SELECT * FROM {s}.flag_event_backup")
                tx.execute(f"ALTER SEQUENCE {seq} OWNED BY {s}.flag_event.id")
                tx.execute(f"DROP TABLE {s}.flag_event_backup")
        env = {"TB_DB_URL": self.box.orch.db.url, "TB_TZ": "Asia/Taipei"}
        return backup.hold_screening(env, None, "synthetic restore of the night's own backup")


# --------------------------------------------------------------------------------------------------- one run


class Walk:
    def __init__(self, site: Site) -> None:
        self.site = site
        self.findings: list[str] = []
        self.reference: dict[str, Any] = {}  # study -> a job that listed before the case (restart, rerun)

    def find(self, invariant: str, case: str, entrance: str, detail: str) -> None:
        self.findings.append(f"finding: {invariant} case={case} entrance={entrance}: {detail}")

    def _new_screen(self, entrance: str, study: str, options: dict[str, str]) -> Any:
        from tb_contracts import JobCreate

        box = self.site.box
        before = {j.job_id for j in box.orch.db.find(type_="SCREEN", limit=500)}
        if entrance == "mail":
            box.mail(" ".join([f"SCREEN {study}", *(f"{k}={v}" for k, v in options.items())]), sender=SENDER)
        else:
            job = box.orch.create(JobCreate(type="SCREEN", requested_by=SENDER, ruleset=study, options=options))
            if entrance == "restart":
                ref = self.reference[study]
                pinned = {**(job.options or {}), **{k: v for k, v in (ref.options or {}).items() if k != "lang"}}
                box.orch.db.put(job.model_copy(update={"snapshot_date": ref.snapshot_date,
                                                       "ruleset_version": ref.ruleset_version, "options": pinned}))  # fmt: skip
        box.orch.drain()
        (job_id,) = {j.job_id for j in box.orch.db.find(type_="SCREEN", limit=500)} - before
        return box.orch.db.get(job_id)

    def run(self, case: str, entrance: str, study: str, options: dict[str, str]) -> str:
        from orchestrator.i18n import t
        from orchestrator.rerun import rerun
        from tb_common.screening_inputs import REFUSAL

        site, box = self.site, self.site.box
        pool = box.orch.db.pool(study)
        if entrance in ("restart", "rerun") and study not in self.reference:
            return "n/a"
        if entrance == "rerun":
            refused_before = len(site.events(REFUSAL))
            admitted_before = len(site.events("screen.inputs_admitted"))
            res = rerun(box.orch, self.reference[study].job_id)
            if res.error is None:
                if len(site.events("screen.inputs_admitted")) == admitted_before:
                    self.find("admitted", case, entrance, "the replay listed with no admission audit")
                return "listed"
            if t("en", REFUSAL) not in res.error:
                return f"other: {res.error[:80]}"
            if len(site.events(REFUSAL)) == refused_before:
                self.find("audited", case, entrance, "the replay's refusal is not in the audit log")
            return "refused"
        job = self._new_screen(entrance, study, options)
        outputs = list(box.store.list(f"outputs/{job.job_id}/"))
        if job.state == "done":
            self._check_admitted(case, entrance, job)
            return "listed"
        if job.error is None or job.error.detail != REFUSAL:
            return f"other: {job.state} {job.error.step if job.error else ''}"
        if job.outputs or outputs or box.orch.db.pool(study) != pool:
            self.find("nothing-published", case, entrance, f"{len(job.outputs or [])} outputs, {len(outputs)} files")
        states = [e for e in site.events("job.state") if e.get("job_id") == job.job_id]
        if not any(((e.get("detail") or {}).get("error") or {}).get("detail") == REFUSAL for e in states):
            self.find("audited", case, entrance, "the refusal is not in the audit log")
        if not [e for e in site.events(REFUSAL) if e.get("job_id") == job.job_id]:
            self.find("audited", case, entrance, "the gate's refusal event is missing")
        return "refused"

    def _check_admitted(self, case: str, entrance: str, job: Any) -> None:
        site = self.site
        admitted = [e for e in site.events("screen.inputs_admitted") if e.get("job_id") == job.job_id]
        if not admitted:
            self.find("admitted", case, entrance, "a list with no admission audit")
            return
        sha = admitted[-1].get("input_sha")
        generation = (job.options or {}).get("lake_generation", "")
        path = site.root / "screening-inputs" / generation / str(job.ruleset) / f"{job.ruleset_version}.json"
        body = path.read_bytes() if path.is_file() else b""
        if hashlib.sha256(body).hexdigest() != sha:
            self.find("admitted", case, entrance, "the admitted hash is not the record file's")
        if sha not in site.clearance().get("accepted_records", []):
            self.find("admitted", case, entrance, "the admitted record is not accepted by the clearance")
        if not any(e.get("input_sha") == sha for e in site.events("screen.inputs_issued")):
            self.find("admitted", case, entrance, "the admitted record has no issue audit")

    def case(self, case: str, expect: str, study: str, options: dict[str, str] | None = None) -> dict[str, str]:
        got = {e: self.run(case, e, study, options or {}) for e in ENTRANCES}
        seen = {d for d in got.values() if d != "n/a"}
        if len(seen) > 1:
            self.find("same-decision", case, "all", ", ".join(f"{e}={d}" for e, d in got.items()))
        for entrance, decision in got.items():
            if decision not in ("n/a", expect):
                self.find("decision", case, entrance, f"{decision}, the gate exists for {expect}")
        self.check_records(case)
        return got

    def check_records(self, case: str) -> None:
        """What is on disk: every record issued by the one writer, holding its own generation's published rows."""
        from tb_common.screening_inputs import published_path

        site = self.site
        issued = {e.get("input_sha") for e in site.events("screen.inputs_issued")}
        accepted = set(site.clearance().get("accepted_records", []))
        for path, body in site.records().items():
            if path.name == "published-rows.json":
                continue
            where = f"{path.parent.parent.name}/{path.parent.name}/{path.stem}"
            sha = hashlib.sha256(body).hexdigest()
            if sha in accepted and sha not in issued:
                self.find("one-writer", case, "records", f"{where} is accepted and was not issued by gate 4")
            record = json.loads(body)
            generation = path.parent.parent.name
            rows_file = published_path(site.root, generation)
            published = json.loads(rows_file.read_bytes()) if rows_file.is_file() else {}
            if sha in accepted and (
                record["use"]["generation"] != generation
                or record["rows"] != published.get("rows")
                or record["inventory"] != published.get("inventory")
            ):
                self.find("own-generation", case, "records", f"{where} does not hold its generation's published rows")


def _restore_after(site: Site, saved: dict[Path, bytes]) -> None:
    for path, body in saved.items():
        path.write_bytes(body)


@pytest.fixture
def walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_url: str) -> Iterator[Walk]:
    monkeypatch.setenv("TB_DB_URL", db_url)
    yield Walk(Site(tmp_path, monkeypatch))


def test_every_entrance_takes_the_same_decision(walk: Walk) -> None:
    from tb_common.screening_inputs import clearance_path

    site, box = walk.site, walk.site.box
    log: list[str] = []

    def case(name: str, expect: str, study: str, options: dict[str, str] | None = None) -> None:
        got = walk.case(name, expect, study, options)
        log.append(f"{name}: " + ", ".join(f"{e}={d}" for e, d in got.items()))

    # 1. the night publishes N1 and issues every study approved then
    site.night(NIGHTS[0])
    reference = walk._new_screen("api", "GZQO", {})
    assert reference.state == "done", reference.error
    walk.reference["GZQO"] = reference
    case("night-approved", "listed", "GZQO")

    # 2. versions approved during the day, through the compiler and through an approval run again after a restart
    walk.reference.pop("RA-JAK", None)
    site.approve("RA-JAK", "1.0.1", "compiler")
    case("day-approved", "listed", "RA-JAK")
    walk.reference["RA-JAK"] = walk._new_screen("api", "RA-JAK", {})
    site.approve("AD-MAB", "1.1.1", "restarted")
    case("day-approved-restarted", "listed", "AD-MAB")

    # 3. a record changed after its issue
    saved = site.records()
    grant = clearance_path(site.root).read_bytes()
    record = next(p for p in saved if p.parent.name == "GZQO" and p.name != "published-rows.json")
    data = json.loads(saved[record])
    data["rows"][0]["owner_rule_stamp"] = "edited-after-issue"
    record.write_text(json.dumps(data))
    case("tampered", "refused", "GZQO")
    _restore_after(site, saved)
    clearance_path(site.root).write_bytes(grant)

    # 4. scopes the site did not approve for this use
    case("narrowed-window", "refused", "GZQO", {"window": "30"})
    case("narrowed-department", "refused", "GZQO", {"dept": "RHEUM"})
    case("narrowed-practitioners", "refused", "GZQO", {"pract": "P12345"})

    # 5. a newer night that published nothing: the records of N1 are stale; a version approved now has no rows
    site.night(NIGHTS[1], publish=False)
    case("stale", "refused", "GZQO")
    site.approve("RA-BIO", "1.0.1", "compiler")
    refused = [e for e in site.events("screen.inputs_refused") if e.get("ruleset") == "RA-BIO"]
    if not refused:
        walk.find("audited", "approved-no-published-generation", "approval", "the refused issue is not audited")
    case("approved-no-published-generation", "refused", "RA-BIO")

    # 6. a night publishes N3 (listed again), then a restore whose audited hold could not be written
    site.night(NIGHTS[2])
    walk.reference["GZQO"] = walk._new_screen("api", "GZQO", {})
    case("control-before-restore", "listed", "GZQO")
    hold = site.restore_without_hold()
    assert hold.startswith("NOT set"), hold
    case("restore", "refused", "GZQO")

    print("\n".join(log))
    assert not walk.findings, f"gate 4: {len(walk.findings)} findings\n" + "\n".join(walk.findings)


def _unused(_: Callable[..., Any]) -> None:  # pragma: no cover - keeps the imports a reader expects
    return None
