"""10D-28 (D-1369; review 19-9): a rule set compiled and approved on one box, carried to another in a vendor-signed
update bundle, interim for the dry run.

* the export carries criteria and codes only: no routing, scope, approver, reviewer, comment, IRB record, effective
  date or site code table leaves the head box, in no byte of the part or of the bundle; ``tests/`` stays; it is the
  box's own approval only (never a seeded one or one that arrived in any update) and is audited;
* a bundle may carry a rule-set part alone: signed with the vendor key, verified like any bundle, applied through the
  update path, ``update.applied`` audited with the rule set named; it expires after 30 days by default;
* the receiving box takes its own routing and scope (refused without them), records where the part came from on the
  approval tag and lists every version that arrived in an update as not approved here; its release keeps its commit;
* refused: a part whose files or record do not match its hash, a record of the wrong form, a stray member, a part
  older than the box's newest version, the same version with other content; a bundle changed after signing.

The update path runs on :class:`ScreenOnlyBox`: the real verifier, the real ``Updater`` and the real rule-set import,
with no database or images (those steps are the container box's, unchanged). Synthetic data only.
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from criteria_compiler.export_part import ExportRefused, compiled_on, export
from criteria_compiler.import_ruleset import (
    ImportRefused,
    accept_command,
    box_pins_problem,
    install,
    install_outcome,
    put_site_profile,
)
from criteria_compiler.repo import RulesetRepo
from tb_common.audit import AuditLog
from tb_common.ruleset import arrived_in_bundle, load_approved
from tb_common.ruleset_part import ARRIVED_MARK, ORIGIN, PartRefused, build_part, neutral_files, open_part, part_sha256

from tests.rulesets_guard import approve_at_site, copy_rulesets
from tools import ruleset_bundle, sign_bundle
from tools.trialbox.update import Plan, UpdateFailed, Updater, ruleset_line
from tools.verify_update import Rejected, summary, verify

HEAD_RELEASE = {"format": "trialbox-installed/1", "release_seq": 3, "bundle_id": "2026.11-1",
                "commit": "a" * 40, "state": {}}  # fmt: skip
SITE_PROFILE = {"routing": {"list_to": ["pi@site.test"], "aggregate_to": ["crc@site.test"]},
                "scopes": {"screen": {"practitioners": ["S-001"], "appointment_window_days": 90}}}  # fmt: skip
#: planted on the head box: none of these may leave it
PLANTED = ("planted.pi@head.test", "Dr Planted Approver", "planted.reviewer@head.test", "PLANTED REVIEWER COMMENT",
           "IRB-PLANTED-77", "P-PLANTED-9", "DEPT-PLANTED", "site_planted_codes", "planted.drafter",
           "planted.crc@head.test", "2031-07-07")  # fmt: skip


class ScreenOnlyBox:
    """The steps of a site box that matter to a rule-set-only bundle: the rule-set import into its repository (the
    command ``ComposeBox.rulesets`` runs in the compiler's container) and the audit; nothing else to back up."""

    name = "screen-only test box"

    def __init__(self, repo_dir: Path, audit: AuditLog) -> None:
        self.repo_dir = repo_dir
        self.audit_log = audit

    def environment(self) -> str:
        return "PRODUCTION"  # the strict side: a PRODUCTION box takes a rule-set-only bundle

    def running(self) -> bool:
        return True

    def backup(self, plan: Plan, rb: Path) -> str:
        return "test box: nothing but the rule-set repository, which the rollback point names"

    def snapshot(self, plan: Plan, rb: Path, point: Any) -> None:
        point.extra["tags"] = RulesetRepo(self.repo_dir).tags()

    def apply(self, plan: Plan, rb: Path, point: Any) -> list[str]:
        return []

    def restart(self, plan: Plan) -> None:
        return None

    def rulesets(self, plan: Plan) -> list[str]:
        done = []
        rs = plan.kind("ruleset")
        for z in sorted(rs.rglob("*.zip")) if rs.is_dir() else []:
            res = install_outcome(
                RulesetRepo(self.repo_dir), z.read_bytes(), f"update:{plan.bundle_id}", pins_problem=box_pins_problem
            )
            done.append(ruleset_line(z.name, res))  # as ComposeBox.rulesets reads the import's output line
        return done

    def post_apply(self, plan: Plan) -> list[str]:
        return self.rulesets(plan)

    def check(self, plan: Plan) -> str:
        return "the test box is up"

    def rollback(self, plan: Plan, rb: Path, point: Any) -> None:
        assert RulesetRepo(self.repo_dir).tags() == point.extra["tags"]  # a refused import wrote no tag

    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None:
        self.audit_log.append(event, actor="apply_update.sh", input_sha=plan.manifest_sha256, detail=detail)


def apply_bundle(bundle: Path, pub: Path, box: ScreenOnlyBox, updates: Path, stage: Path) -> dict[str, Any]:
    """What ``tools/apply_update.sh`` does with the bundle: verify and stage, then the update path."""
    m = verify(bundle, pub, stage, trust_file=updates / "trust.json", installed_file=updates / "installed.json")
    return Updater(box, updates, say=lambda _s: None).run(Plan.load(stage, summary(m)))


def audit_events(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for f in sorted(directory.glob("*.jsonl")) for ln in f.read_text().splitlines() if ln]


def _plant(seed: Path) -> None:
    """Every staff and site field a real head box's GZQO may hold, with values that must never leave it."""
    mf = seed / "GZQO" / "manifest.yaml"
    m = yaml.safe_load(mf.read_text(encoding="utf-8"))
    m["routing"] = {"list_to": [PLANTED[0]], "aggregate_to": [PLANTED[9]], "referral_to": {"META": PLANTED[0]}}
    m["scopes"]["screen"]["practitioners"] = [PLANTED[5]]
    m["scopes"]["screen"]["departments"] = [PLANTED[6]]
    m["review"]["approved_by"] = PLANTED[1]
    m["review"]["approved_via"] = f"web console ({PLANTED[0]})"
    m["irb_reference"], m["irb_approved_on"], m["effective_from"] = PLANTED[4], "2026-10-01", PLANTED[10]
    m["terminology_tables"] = [{"table": PLANTED[7], "system": "site", "version": "1", "sha256": "0" * 64}]
    mf.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for f in sorted((seed / "GZQO" / "ir").glob("*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        c["review"] = {"status": "approved", "by": PLANTED[2], "at": "2026-10-04T16:42:05+08:00", "comment": PLANTED[3]}
        c["provenance"] = {"calls": [PLANTED[8]]}
        f.write_text(json.dumps(c, indent=1), encoding="utf-8")


@pytest.fixture
def site_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")  # both boxes are site boxes: a seeded approval is no approval


@pytest.fixture
def head(tmp_path: Path, site_env: None) -> RulesetRepo:
    """The head box's repository: GZQO compiled (the shipped files, ``tests/`` included, with planted site and staff
    fields) and approved at that box."""
    seed = copy_rulesets(tmp_path / "seed")
    _plant(seed)
    repo = RulesetRepo(tmp_path / "head", seed)
    approve_at_site(tmp_path / "head", by=PLANTED[0])
    return repo


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, Path]:
    return sign_bundle.keygen(tmp_path / "vendor")


def make_part(head: RulesetRepo, out: Path) -> Path:
    data, _origin = export(head, "GZQO", compiled_on(HEAD_RELEASE))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def accept(repo_dir: Path, version: str, part_sha256: str | None = None, by: str = "operator") -> str:
    """The site's act (``--site-profile``): its own routing and scope for GZQO, accepting ``version`` (and the part's
    hash when given)."""
    return put_site_profile(RulesetRepo(repo_dir), "GZQO", yaml.safe_dump(SITE_PROFILE).encode(), by,
                            version=version, part_sha256=part_sha256,
                            audit=AuditLog(repo_dir.parent / "site-audit"))  # fmt: skip


def site_box(tmp_path: Path, profile: bool = True, keep: tuple[str, ...] = (),
             version: str = "1.0.0") -> tuple[ScreenOnlyBox, Path]:  # fmt: skip
    """A site box without GZQO (unless ``keep`` names it), with its own routing and scope for it, accepting
    ``version``, when ``profile``."""
    seed = copy_rulesets(tmp_path / "site-seed", *(() if "GZQO" in keep else ("GZQO",)), "GZQO.yaml")
    RulesetRepo(tmp_path / "site", seed)
    approve_at_site(tmp_path / "site", by="pi@site.test")
    if profile:
        accept(tmp_path / "site", version)
    updates = tmp_path / "updates"
    updates.mkdir()
    (updates / "installed.json").write_text(json.dumps({**HEAD_RELEASE, "commit": "b" * 40}))
    return ScreenOnlyBox(tmp_path / "site", AuditLog(tmp_path / "audit")), updates


def head_installed(tmp_path: Path) -> Path:
    """A box on the release that compiled the part (release_seq 3): the bundle asks for at least that."""
    f = tmp_path / "head-release-installed.json"
    f.write_text(json.dumps(HEAD_RELEASE))
    return f


def members(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {n: z.read(n) for n in z.namelist()}


def repart(part: Path, out: Path, change: Any) -> Path:
    """The part's members after ``change(name, bytes) -> bytes | None`` (None drops the member)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as dst:
        for n, b in members(part.read_bytes()).items():
            new = change(n, b)
            if new is not None:
                dst.writestr(n, new)
    return out


# ------------------------------------------------------------------------------------------------ the export
def test_no_site_or_staff_field_leaves_the_head_box(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    """B1: every byte of the part (each member decompressed) and of the bundle (and the part inside it)."""
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(keys[0], "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    texts = [part.read_bytes(), (tmp_path / "rs.tar").read_bytes(), *members(part.read_bytes()).values()]
    with tarfile.open(tmp_path / "rs.tar") as tf:
        for m in tf.getmembers():
            data = tf.extractfile(m).read()  # type: ignore[union-attr]
            texts += [data, *(members(data).values() if m.name.endswith(".zip") else [])]
    for planted in PLANTED:
        assert not [t for t in texts if planted.encode() in t], planted
    seeded = copy_rulesets(tmp_path / "check")
    _plant(seeded)
    assert PLANTED[3].encode() in (seeded / "GZQO" / "ir" / "GZQO-INC-01.json").read_bytes()  # the plant is real
    m = yaml.safe_load(members(part.read_bytes())["GZQO/manifest.yaml"])
    assert m["routing"] == {} and m["scopes"] == {} and "review" not in m and "irb_reference" not in m
    assert m["models"] == {"judge_prompt": "judge_v4"} and m["equivalence"]["overall_pct"] == 100.0
    assert m["thresholds"] and m["criteria"]  # the protocol's fields stay


def test_the_part_carries_criteria_and_codes_only(head: RulesetRepo, tmp_path: Path) -> None:
    part = make_part(head, tmp_path / "GZQO.part.zip")
    names = zipfile.ZipFile(part).namelist()
    assert ORIGIN in names and not [n for n in names if "/tests/" in n]
    assert {n.split("/")[1] for n in names if n != ORIGIN} <= {"manifest.yaml", "labels.yaml", "ir", "valuesets",
                                                               "cql", "sql"}  # fmt: skip
    rid, files, manifest, origin = open_part(part.read_bytes())
    assert (rid, manifest["status"], origin["left_out"]) == ("GZQO", "approved", ["tests/"])
    assert origin["part_sha256"] == part_sha256(files, origin) and origin["approval_tag"] == "GZQO/v1.0.0"
    assert origin["compiled_on"] == {"bundle_id": "2026.11-1", "release_seq": 3, "commit": "a" * 40}
    assert origin["pins"]["judge_prompt"] == "judge_v4"
    ir = json.loads(files["ir/GZQO-INC-01.json"])
    assert ir["review"] == {"status": "approved"} and "provenance" not in ir
    # S5: the part holds no time: the same approved version exported again is the same part, byte for byte
    assert export(head, "GZQO", compiled_on(HEAD_RELEASE))[0] == part.read_bytes()
    assert "exported_at" not in origin


def test_a_file_or_field_nobody_placed_refuses_the_export(head: RulesetRepo) -> None:
    files = _head_files(head)
    with pytest.raises(PartRefused, match="patients.csv"):
        neutral_files({**files, "patients.csv": b"mrn\n"})
    with pytest.raises(PartRefused, match="not placed"):
        neutral_files({**files, "manifest.yaml": files["manifest.yaml"] + b"new_site_field: 1\n"})
    out = neutral_files({**files, "tests/patients.ndjson": b"{}"})
    assert "manifest.yaml" in out and not [p for p in out if p.startswith("tests/")]


def _head_files(head: RulesetRepo) -> dict[str, bytes]:
    return {p[len("GZQO/") :]: b for p, b in head.files("refs/tags/GZQO/v1.0.0", "GZQO/").items()}


def test_only_the_boxs_own_approval_is_exported_and_it_is_audited(tmp_path: Path, site_env: None) -> None:
    repo = RulesetRepo(tmp_path / "seeded", copy_rulesets(tmp_path / "seed"))  # seeded: approved by nobody here
    with pytest.raises(Exception, match="not approved at this site|names nobody"):
        export(repo, "GZQO", compiled_on(HEAD_RELEASE))
    for message in ("GZQO/v1.0.0 (offline update, update:x)",  # S1: any update, with or without a part's record
                    f"GZQO/v1.0.0 (offline update, update:x); {ARRIVED_MARK}: update:x"):  # fmt: skip
        repo.retag("GZQO/v1.0.0", message)
        with pytest.raises(ExportRefused, match="arrived in an update"):
            export(repo, "GZQO", compiled_on(HEAD_RELEASE))
    with pytest.raises(ExportRefused, match="name the release"):
        compiled_on(None, " ")
    repo.retag("GZQO/v1.0.0", "GZQO v1.0.0 approved by pi@head.test", "pi@head.test")
    audit = AuditLog(tmp_path / "head-audit")
    _data, origin = export(repo, "GZQO", compiled_on(HEAD_RELEASE), audit=audit, by="host:operator")
    (ev,) = [e for e in audit_events(tmp_path / "head-audit") if e["event"] == "approve.part_exported"]
    assert (ev["actor"], ev["ruleset"], ev["ruleset_version"]) == ("host:operator", "GZQO", "1.0.0")
    assert ev["output_sha"] == origin["part_sha256"] and ev["detail"]["files"] == len(origin["files"])


# ------------------------------------------------------------------------------------------------ the bundle
def test_a_bundle_may_carry_a_rule_set_alone(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    priv, pub = keys
    part = make_part(head, tmp_path / "GZQO.part.zip")
    m = ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert [f["kind"] for f in m["files"]] == ["ruleset"] and "release_sha256" not in m
    life = datetime.fromisoformat(m["not_after"]) - datetime.fromisoformat(m["created_at"])
    assert life == timedelta(days=30)  # S6: a dry-run bundle expires after a month
    with pytest.raises(SystemExit, match="1 to 90 days"):
        ruleset_bundle.build(priv, "x2", [part], tmp_path / "x.tar", release_seq=4, valid_days=365)
    v = verify(tmp_path / "rs.tar", pub, tmp_path / "stage", installed_file=head_installed(tmp_path))
    assert v["release"] is None and (tmp_path / "stage" / "ruleset" / "GZQO.part.zip").read_bytes() == part.read_bytes()


def test_the_vendor_command_line(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path,
                                 capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    part = make_part(head, tmp_path / "GZQO.part.zip")
    argv = ["--key", str(keys[0]), "--id", "rs1", "--release-seq", "4", "--out", str(tmp_path / "rs.tar"), str(part)]
    assert ruleset_bundle.main(argv) == 0
    out = capsys.readouterr().out
    assert "1 rule-set part(s), bundle rs1, release_seq 4" in out
    h = open_part(part.read_bytes())[3]["part_sha256"]  # the fifth review: the full hash the site accepts the part by
    assert f"part GZQO v1.0.0 part_sha256 {h} (send it to the site with the bundle" in out
    assert verify(tmp_path / "rs.tar", keys[1], installed_file=head_installed(tmp_path))["bundle_id"] == "rs1"


def test_the_vendor_tool_refuses_a_zip_that_is_no_part(keys: tuple[Path, Path], tmp_path: Path) -> None:
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("GZQO/manifest.yaml", "id: GZQO\nstatus: approved\n")
    with pytest.raises(SystemExit, match="not a rule-set part"):
        ruleset_bundle.build(keys[0], "x1", [plain], tmp_path / "x.tar", release_seq=4)


# ------------------------------------------------------------------------------------------------ the receiving box
def test_the_site_box_installs_it_as_approved_elsewhere(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    priv, pub = keys
    box, updates = site_box(tmp_path)
    site = tmp_path / "site"
    with pytest.raises(Exception, match="no approved version"):
        load_approved(site, "GZQO")
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    res = apply_bundle(tmp_path / "rs.tar", pub, box, updates, tmp_path / "stage")
    assert res["ok"]
    rs = load_approved(site, "GZQO")  # D-77: an installed update stands as the approval; no local step today
    assert rs.version == "1.0.0" and arrived_in_bundle(site, "GZQO", "1.0.0")
    assert not arrived_in_bundle(site, "RA-JAK", "1.0.0")  # approved at the site itself
    routing = rs.manifest.routing.model_dump(exclude_none=True)
    assert routing == SITE_PROFILE["routing"]  # the site's own people, never the head box's
    assert rs.manifest.scopes.screen.practitioners == ["S-001"]  # type: ignore[union-attr]
    msg = RulesetRepo(site).tag_message("GZQO/v1.0.0")
    origin = open_part(part.read_bytes())[3]
    for words in (ARRIVED_MARK, "update:2026.11-1-rs1", "2026.11-1 (release_seq 3, commit aaaaaaaaaaaa)",
                  origin["part_sha256"], "its tag GZQO/v1.0.0"):  # fmt: skip
        assert words in msg, words
    assert PLANTED[0] not in msg
    applied = [e for e in audit_events(tmp_path / "audit") if e["event"] == "update.applied"]
    assert len(applied) == 1 and applied[0]["detail"]["rulesets"] == ["GZQO v1.0.0: imported (GZQO.part.zip)"]
    assert applied[0]["detail"]["files"][0]["kind"] == "ruleset"
    inst = json.loads((updates / "installed.json").read_text())
    assert inst["release_seq"] == 4 and inst["bundle_id"] == "2026.11-1-rs1"
    assert inst["commit"] == "b" * 40 and inst["release_bundle_id"] == "2026.11-1"  # the box's code is unchanged
    # the same part again (a re-applied bundle): nothing to do
    assert install(RulesetRepo(site), part.read_bytes(), "update:again") == "GZQO/v1.0.0"

    from console.backend import ruleset_infos

    infos = {i.id: i for i in ruleset_infos(site)}
    assert infos["GZQO"].origin == "vendor_bundle" and infos["RA-JAK"].origin == ""


def test_without_the_sites_own_routing_and_scope_it_is_refused(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    priv, pub = keys
    box, updates = site_box(tmp_path, profile=False)
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    with pytest.raises(UpdateFailed, match="no routing .* of its own for GZQO.*--site-profile GZQO - --version 1.0.0"):
        apply_bundle(tmp_path / "rs.tar", pub, box, updates, tmp_path / "stage")
    assert "GZQO/v1.0.0" not in RulesetRepo(tmp_path / "site").tags()


def test_a_rule_set_zip_without_a_record_is_marked_too(tmp_path: Path, site_env: None) -> None:
    """S1: ORIGIN.json removed, or a plain rule set of any update: installed as before, listed as not approved here."""
    box, _updates = site_box(tmp_path)
    install(RulesetRepo(box.repo_dir), _plain_zip(), "update:plain")
    assert arrived_in_bundle(box.repo_dir, "GZQO", "1.0.0")

    from console.backend import ruleset_infos

    assert {i.id: i.origin for i in ruleset_infos(box.repo_dir)}["GZQO"] == "vendor_bundle"


def _plain_zip() -> bytes:
    root = Path(__file__).resolve().parents[2] / "rulesets" / "GZQO"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f"GZQO/{f.relative_to(root).as_posix()}")
    return buf.getvalue()


def _versioned(head: RulesetRepo, version: str, out: Path, terminology: str | None = None) -> Path:
    """A part of GZQO as the head box would export version ``version`` (same files, the version moved; with
    ``terminology``, compiled against that terminology release)."""
    files = {p[len("GZQO/") :]: b for p, b in head.files("refs/tags/GZQO/v1.0.0", "GZQO/").items()}
    m = yaml.safe_load(files["manifest.yaml"])
    m["version"] = version
    if terminology:
        m["terminology_release"] = terminology
    pins = {"judge_prompt": m["models"]["judge_prompt"], "terminology_release": m.get("terminology_release")}
    files["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode()
    files["sql/GZQO.sql"] = files["sql/GZQO.sql"].replace(b"-- GZQO v1.0.0 ", f"-- GZQO v{version} ".encode(), 1)
    origin = {"format": "trialbox-ruleset-part/1", "ruleset": "GZQO", "version": version, "left_out": ["tests/"],
              "approval_tag": f"GZQO/v{version}", "compiled_on": {"bundle_id": "2026.11-1", "release_seq": 3},
              "pins": pins}  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_part("GZQO", files, origin))
    return out


def test_the_bundle_carries_the_parts_pins_and_the_verifier_refuses_a_mismatch(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    """Review 2, item 2: compat.json from the part's terminology release, min_installed from the compiling release."""
    priv, pub = keys
    part = _versioned(head, "1.0.1", tmp_path / "p" / "GZQO.part.zip", terminology="TR-0123456789ab")
    m = ruleset_bundle.build(priv, "rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert m["min_installed_version"] == 3
    for installed, why in (
        ({"format": "trialbox-installed/1", "release_seq": 3, "state": {"vocabulary_release": "TR-ba9876543210"}},
         "vocabulary_release 'TR-ba9876543210' is not one of"),
        ({"format": "trialbox-installed/1", "release_seq": 2, "state": {}}, "needs at least 3 installed"),
    ):  # fmt: skip
        f = tmp_path / "installed.json"
        f.write_text(json.dumps(installed))
        with pytest.raises(Rejected, match=why):
            verify(tmp_path / "rs.tar", pub, installed_file=f)
    f.write_text(json.dumps({"format": "trialbox-installed/1", "release_seq": 3,
                             "state": {"vocabulary_release": "TR-0123456789ab"}}))  # fmt: skip
    assert verify(tmp_path / "rs.tar", pub, installed_file=f)["bundle_id"] == "rs1"


def test_the_import_refuses_a_part_whose_pins_do_not_stand_on_the_box(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 2, item 2: a box that records no vocabulary release still refuses at import, before anything is written."""
    from criteria_compiler.terminology import resolver

    box, _updates = site_box(tmp_path, version="1.0.1")
    part = _versioned(head, "1.0.1", tmp_path / "p.zip", terminology="TR-0123456789ab").read_bytes()
    monkeypatch.setattr(resolver, "current_release", lambda: "TR-ba9876543210")
    with pytest.raises(ImportRefused, match="compiled against terminology release TR-0123456789ab; this box resolves "
                                            "through TR-ba9876543210"):  # fmt: skip
        install(RulesetRepo(box.repo_dir), part, "update:x", pins_problem=box_pins_problem)
    assert "GZQO/v1.0.1" not in RulesetRepo(box.repo_dir).tags()
    monkeypatch.setattr(resolver, "current_release", lambda: "TR-0123456789ab")
    assert install(RulesetRepo(box.repo_dir), part, "update:x", pins_problem=box_pins_problem) == "GZQO/v1.0.1"


def test_a_part_never_goes_back_or_replaces_other_content(head: RulesetRepo, tmp_path: Path) -> None:
    """S3, and the reviewer's note: a box holding the shipped GZQO v1.0.0 refuses a part of v1.0.0."""
    box, _updates = site_box(tmp_path, version="1.1.0")
    repo = RulesetRepo(box.repo_dir)
    assert install(repo, _versioned(head, "1.1.0", tmp_path / "p11.zip").read_bytes(), "update:a") == "GZQO/v1.1.0"
    with pytest.raises(ImportRefused, match="older than the approved GZQO v1.1.0"):
        install(repo, make_part(head, tmp_path / "p10.zip").read_bytes(), "update:b")
    shipped, _ = site_box(tmp_path / "with-shipped", keep=("GZQO",))
    with pytest.raises(ImportRefused, match="already exists on this box with other content"):
        install(RulesetRepo(shipped.repo_dir), make_part(head, tmp_path / "p10b.zip").read_bytes(), "update:c")


def test_the_same_version_with_another_hash_is_refused(head: RulesetRepo, tmp_path: Path) -> None:
    box, _updates = site_box(tmp_path)
    repo = RulesetRepo(box.repo_dir)
    install(repo, make_part(head, tmp_path / "a.zip").read_bytes(), "update:a")
    # S5: exported again later from the same release: the same part, a repeat (not "other content")
    again = export(head, "GZQO", compiled_on(HEAD_RELEASE))[0]
    assert install(repo, again, "update:again") == "GZQO/v1.0.0"
    other = export(head, "GZQO", {"bundle_id": "2026.12-1", "release_seq": 5})[0]  # another record: another hash
    with pytest.raises(ImportRefused, match="already exists on this box with other content"):
        install(repo, other, "update:b")


@pytest.mark.parametrize(
    "field, value",
    [("approval_tag", "GZQO/v1.0.0\nGZQO/v1.0.0 (vendor-shipped, approved)"),
     ("compiled_on", {"release": "x\n(vendor-shipped, approved)"}),
     ("compiled_on", {"bundle_id": "a b"}),
     ("pins", {"judge_prompt": "judge v4; rm"}),
     ("exported_at", "yesterday"),
     ("extra", "anything")],
)  # fmt: skip
def test_a_record_of_the_wrong_form_is_refused(head: RulesetRepo, tmp_path: Path, field: str, value: Any) -> None:
    """S4: each field checked, re-hashed so only the form can refuse it; and a field changed without the hash."""
    part = make_part(head, tmp_path / "p.zip")
    _rid, files, _m, origin = open_part(part.read_bytes())
    forged = {**origin, field: value}
    forged["part_sha256"] = part_sha256(files, forged)
    bad = repart(part, tmp_path / "bad.zip", lambda n, b: json.dumps(forged).encode() if n == ORIGIN else b)
    with pytest.raises(PartRefused, match="ORIGIN.json refused"):
        open_part(bad.read_bytes())


def test_a_record_changed_without_its_hash_is_refused(head: RulesetRepo, tmp_path: Path) -> None:
    part = make_part(head, tmp_path / "p.zip")
    origin = json.loads(members(part.read_bytes())[ORIGIN])
    origin["compiled_on"] = {"bundle_id": "2026.12-9", "release_seq": 9}  # a valid form, not what was hashed
    bad = repart(part, tmp_path / "bad.zip", lambda n, b: json.dumps(origin).encode() if n == ORIGIN else b)
    with pytest.raises(PartRefused, match="part sha256 .* refused"):
        open_part(bad.read_bytes())


def test_a_stray_member_or_a_site_field_is_refused(head: RulesetRepo, tmp_path: Path) -> None:
    """S5: a member outside the folder; and a part whose manifest holds routing again (not made by the export)."""
    part = make_part(head, tmp_path / "p.zip")
    with zipfile.ZipFile(part, "a") as z:
        z.writestr("STRAY/patients.csv", "mrn\n12345678\n")
    box, _updates = site_box(tmp_path)
    with pytest.raises(ImportRefused, match="outside its folder"):
        install(RulesetRepo(box.repo_dir), part.read_bytes(), "update:x")
    clean = make_part(head, tmp_path / "c.zip")
    _rid, files, _m, origin = open_part(clean.read_bytes())
    m = yaml.safe_load(files["manifest.yaml"])
    m["routing"] = {"list_to": [PLANTED[0]]}
    files["manifest.yaml"] = yaml.safe_dump(m, sort_keys=False).encode()
    origin = {**origin, "files": sorted(files)}
    origin["part_sha256"] = part_sha256(files, origin)
    with_site = repart(
        clean,
        tmp_path / "s.zip",
        lambda n, b: (
            json.dumps(origin).encode() if n == ORIGIN else files["manifest.yaml"] if n == "GZQO/manifest.yaml" else b
        ),
    )
    with pytest.raises(PartRefused, match="site or staff fields"):
        open_part(with_site.read_bytes())


def _tampered(part: Path, out: Path) -> Path:
    """The part with one criterion's bytes changed and its ORIGIN.json (and recorded hash) kept."""
    changed = [False]

    def change(n: str, b: bytes) -> bytes:
        if not changed[0] and n.startswith("GZQO/ir/") and b'"inclusion"' in b:
            changed[0] = True
            return b.replace(b'"inclusion"', b'"exclusion"', 1)
        return b

    repart(part, out, change)
    assert changed[0]
    return out


def test_a_part_whose_hash_does_not_match_is_refused(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    priv, pub = keys
    box, updates = site_box(tmp_path)
    bad = _tampered(make_part(head, tmp_path / "GZQO.part.zip"), tmp_path / "bad" / "GZQO.part.zip")
    with pytest.raises(SystemExit, match="part sha256"):  # the vendor's tool reads it first
        ruleset_bundle.build(priv, "x1", [bad], tmp_path / "x.tar", release_seq=4)
    # signed past the tool (sign_bundle directly): the receiving box refuses it and rolls back
    sign_bundle.build(priv, "2026.11-1-rs2", [("ruleset", bad, bad.name)], tmp_path / "bad.tar", release_seq=4)
    with pytest.raises(UpdateFailed, match="part sha256 .* refused.*rolled back"):
        apply_bundle(tmp_path / "bad.tar", pub, box, updates, tmp_path / "stage")
    assert "GZQO/v1.0.0" not in RulesetRepo(tmp_path / "site").tags()
    events = [e["event"] for e in audit_events(tmp_path / "audit")]
    assert "update.rolled_back" in events and "update.applied" not in events
    assert json.loads((updates / "installed.json").read_text())["release_seq"] == 3


def test_a_bundle_changed_after_signing_is_rejected(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    priv, pub = keys
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    bad = _tampered(part, tmp_path / "t.zip").read_bytes()
    with tarfile.open(tmp_path / "rs.tar") as src, tarfile.open(tmp_path / "swapped.tar", "w") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()  # type: ignore[union-attr]
            if m.name == "files/GZQO.part.zip":
                data = bad[: len(data)].ljust(len(data), b"\0")  # same size: only the hash can tell
            m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    stage = tmp_path / "stage"
    with pytest.raises(Rejected, match="sha256 mismatch"):
        verify(tmp_path / "swapped.tar", pub, stage, installed_file=head_installed(tmp_path))
    assert not stage.exists() or not [p for p in stage.rglob("*") if p.is_file()]  # nothing staged


# ------------------------------------------------------------------------------------------------ other pages (S2)
def test_the_sponsor_pack_says_it_arrived_instead_of_an_approver() -> None:
    from types import SimpleNamespace

    from console.app import build_sponsor_pack

    job = SimpleNamespace(ruleset="GZQO", ruleset_version="1.0.0", job_id="J1", snapshot_date=None, run_date=None,
                          requested_by="crc@site.test")  # fmt: skip
    detail: dict[str, Any] = {"title": "t", "review": None, "arrived_in_vendor_bundle": True}
    readme = members(build_sponsor_pack(job, [], detail, None))["README.txt"].decode()  # type: ignore[arg-type]
    assert "arrived in a vendor bundle (interim)" in readme and "Approved by:" not in readme
    detail = {"title": "t", "review": {"approved_by": "pi@site.test"}}
    assert "Approved by: pi@site.test" in members(build_sponsor_pack(job, [], detail, None))["README.txt"].decode()  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ the third review
def _head_with(tmp_path: Path, change: Any) -> RulesetRepo:
    """A head box whose GZQO folder ``change(folder)`` altered before it was approved at that box."""
    seed = copy_rulesets(tmp_path / "seed3")
    _plant(seed)
    change(seed / "GZQO")
    repo = RulesetRepo(tmp_path / "head3", seed)
    approve_at_site(tmp_path / "head3", by=PLANTED[0])
    return repo


def _reseal(part: bytes, files: dict[str, bytes], origin: dict[str, Any] | None = None) -> bytes:
    """A part's members with ``files`` as its folder and its record re-hashed (only the content can refuse it)."""
    rid, _f, _m, o = open_part(part)
    o = {**(origin or o), "files": sorted(files)}
    o["part_sha256"] = part_sha256(files, o)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p, b in files.items():
            z.writestr(f"{rid}/{p}", b)
        z.writestr(ORIGIN, json.dumps(o))
    return buf.getvalue()


@pytest.mark.parametrize("name", ["sql/patients.csv", "cql/notes.md", "valuesets/README.txt", "ir/x.txt",
                                  "cql/elm/sub/TB_Common.json", "labels.yml"])  # fmt: skip
def test_b2_a_file_off_the_list_refuses_the_export(tmp_path: Path, site_env: None, name: str) -> None:
    """B2: the list is per file (master's PROTOCOL_FILES), not per folder: any other file refuses the export."""

    def plant(d: Path) -> None:
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text("mrn,name\nCNRY-B2,Planted Person\n", encoding="utf-8")

    with pytest.raises(ExportRefused, match=f"{name}: not a file a rule-set part carries.*any other file refuses"):
        export(_head_with(tmp_path, plant), "GZQO", compiled_on(HEAD_RELEASE))


@pytest.mark.parametrize("name", ["sql/patients.csv", "cql/notes.md", "tests/patients.ndjson"])
def test_b2_the_import_refuses_a_member_off_the_list(head: RulesetRepo, tmp_path: Path, name: str) -> None:
    """B2: resealed with a right record and hash, a member off the list is still refused; nothing is installed."""
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    files = {**open_part(part)[1], name: b"mrn\n12345678\n"}
    box, _updates = site_box(tmp_path)
    with pytest.raises(ImportRefused, match="files a part does not carry"):
        install(RulesetRepo(box.repo_dir), _reseal(part, files), "update:x")
    assert "GZQO/v1.0.0" not in RulesetRepo(box.repo_dir).tags()


@pytest.mark.parametrize(
    "path, text, line",
    [("cql/TB_GZQO_v1_0.cql", "// CNRY-CQL reviewer note\n", 1),
     ("cql/TB_GZQO_v1_0.cql", "/* CNRY-CQL-BLOCK */\n", 1),
     ("cql/TB_Common.cql", "\n\n/* CNRY-COMMON */\n", 3),
     ("sql/GZQO.sql", "-- CNRY-SQL 审阅\n", 1)],
)  # fmt: skip
def test_b2_a_comment_the_compiler_does_not_write_refuses_the_export(
    tmp_path: Path, site_env: None, path: str, text: str, line: int
) -> None:
    """B2: a comment in code is never stripped (it could change what the code means): the export is refused, with the
    file and the line."""

    def plant(d: Path) -> None:
        (d / path).write_text(text + (d / path).read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ExportRefused, match=f"a comment the compiler does not write, at {path} line {line}"):
        export(_head_with(tmp_path, plant), "GZQO", compiled_on(HEAD_RELEASE))


def test_b2_the_compilers_own_comments_travel_and_a_planted_one_never_does(head: RulesetRepo, tmp_path: Path) -> None:
    """The generated headers and criterion lines pass (the shipped GZQO exports); a comment hidden in a part made past
    the export is refused at the receiving box."""
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    files = open_part(part)[1]
    assert b"-- GZQO-INC-01 (inclusion): " in files["sql/GZQO.sql"]
    sql = files["sql/GZQO.sql"].replace(b"\nSELECT", b"\n-- CNRY-HIDDEN\nSELECT", 1)
    assert sql != files["sql/GZQO.sql"]
    box, _updates = site_box(tmp_path)
    with pytest.raises(ImportRefused, match="a comment the compiler does not write, at sql/GZQO.sql line"):
        install(RulesetRepo(box.repo_dir), _reseal(part, {**files, "sql/GZQO.sql": sql}), "update:x")


def test_b2_yaml_comments_annotations_and_unknown_keys_never_travel(tmp_path: Path, site_env: None) -> None:
    """B2: YAML is written again (its comments go); ELM loses its annotations (the translator's copy of the source);
    an ELM identifier key, a value-set key or a nested one nobody placed refuses the export."""

    def plant(d: Path) -> None:
        lab = d / "labels.yaml"
        lab.write_text("# CNRY-LABEL reviewed by someone\n" + lab.read_text(encoding="utf-8"), encoding="utf-8")
        mf = d / "manifest.yaml"
        mf.write_text("# CNRY-MANIFEST comment\n" + mf.read_text(encoding="utf-8"), encoding="utf-8")
        elm = d / "cql" / "elm" / "TB_GZQO_v1_0.json"
        e = json.loads(elm.read_text(encoding="utf-8"))
        e["library"]["annotation"].append({"type": "Annotation", "s": {"value": ["/* CNRY-ELM */"]}})
        elm.write_text(json.dumps(e), encoding="utf-8")

    data, _origin = export(_head_with(tmp_path, plant), "GZQO", compiled_on(HEAD_RELEASE))
    blobs = [data, *members(data).values()]
    for canary in (b"CNRY-LABEL", b"CNRY-MANIFEST", b"CNRY-ELM", b"CqlToElmInfo", b"translatorOptions"):
        assert not [b for b in blobs if canary in b], canary
    elm = json.loads(members(data)["GZQO/cql/elm/TB_GZQO_v1_0.json"])
    assert "annotation" not in elm["library"] and elm["library"]["statements"]  # what runs is kept
    assert yaml.safe_load(members(data)["GZQO/labels.yaml"])["criteria"]["GZQO-INC-01"]["source"]

    for i, (where, change) in enumerate(
        (
            ("library.identifier holds keys", lambda e: e["library"]["identifier"].update(system="CNRY-LIBID")),
            ("VS_GOUT.json holds keys", "publisher"),
            ("concept\\[0\\] holds keys", "designation"),
        )
    ):

        def plant2(d: Path, change: Any = change) -> None:
            if callable(change):
                elm = d / "cql" / "elm" / "TB_GZQO_v1_0.json"
                e = json.loads(elm.read_text(encoding="utf-8"))
                change(e)
                elm.write_text(json.dumps(e), encoding="utf-8")
                return
            vs = d / "valuesets" / "VS_GOUT.json"
            v = json.loads(vs.read_text(encoding="utf-8"))
            if change == "publisher":
                v["publisher"] = "CNRY-PUBLISHER"
            else:
                v["compose"]["include"][0]["concept"][0]["designation"] = [{"value": "CNRY-NESTED"}]
            vs.write_text(json.dumps(v), encoding="utf-8")

        with pytest.raises(ExportRefused, match=where):
            export(_head_with(tmp_path / str(i), plant2), "GZQO", compiled_on(HEAD_RELEASE))


def test_b2_a_file_name_is_a_library_criterion_or_value_set_name(tmp_path: Path, site_env: None) -> None:
    """A file named with free words never travels: an ELM without its CQL, a criterion file not named by its id."""

    def elm(d: Path) -> None:
        (d / "cql" / "elm" / "CNRYfilename.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ExportRefused, match="CNRYfilename.json: no cql/CNRYfilename.cql beside it"):
        export(_head_with(tmp_path / "a", elm), "GZQO", compiled_on(HEAD_RELEASE))

    def ir(d: Path) -> None:
        (d / "ir" / "GZQO-INC-01.json").rename(d / "ir" / "CNRYname.json")

    with pytest.raises(ExportRefused, match="ir/CNRYname.json: its id and rule set are not CNRYname"):
        export(_head_with(tmp_path / "b", ir), "GZQO", compiled_on(HEAD_RELEASE))


def test_s1_the_criterion_stripper_is_an_allow_list(head: RulesetRepo, tmp_path: Path) -> None:
    """S1: an unknown key is dropped by the export's stripper, and a part that still holds one is refused."""
    from tb_common.ruleset_part import IR_KEYS, neutral_ir
    from tb_contracts import CriterionIR

    assert set(IR_KEYS) == {f.alias or n for n, f in CriterionIR.model_fields.items()} - {"provenance"}
    c = {"id": "GZQO-INC-01", "reviewer_note": "CNRY-NOTE", "review": {"status": "approved", "by": "x"}}
    assert neutral_ir(c) == {"id": "GZQO-INC-01", "review": {"status": "approved"}}
    with pytest.raises(PartRefused, match="a flag is not one word"):
        neutral_ir({"id": "GZQO-INC-01", "flags": ["needs_review", "CNRY flag item"]})
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    files = open_part(part)[1]
    ir = json.loads(files["ir/GZQO-INC-01.json"])
    ir["reviewer_note"] = "CNRY-NOTE"
    files["ir/GZQO-INC-01.json"] = json.dumps(ir, ensure_ascii=False, indent=1, sort_keys=True).encode() + b"\n"
    with pytest.raises(PartRefused, match="ir/GZQO-INC-01.json holds a reviewer's record, provenance, a key nobody"):
        open_part(_reseal(part, files))


def test_s2_a_part_without_its_record_never_installs(head: RulesetRepo, tmp_path: Path) -> None:
    """S2: the export's part with ORIGIN.json removed (routing and scope empty), or moved into the folder: refused,
    on a box without a site profile too; nothing installed."""
    part = make_part(head, tmp_path / "p.zip")
    box, _updates = site_box(tmp_path, profile=False)
    repo = RulesetRepo(box.repo_dir)
    removed = repart(part, tmp_path / "r.zip", lambda n, b: None if n == ORIGIN else b).read_bytes()
    with pytest.raises(ImportRefused, match="no routing or no screening scope .*without its ORIGIN.json"):
        install(repo, removed, "update:r")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in members(part.read_bytes()).items():
            z.writestr("GZQO/ORIGIN.json" if n == ORIGIN else n, b)
    with pytest.raises(ImportRefused, match="GZQO/ORIGIN.json: a part's ORIGIN.json stands at the root"):
        install(repo, buf.getvalue(), "update:m")
    assert "GZQO/v1.0.0" not in repo.tags()


def test_s3_the_shipped_example_profile_is_no_site_profile(head: RulesetRepo, tmp_path: Path) -> None:
    """S3: a box seeded with the shipped profiles/GZQO.yaml, or whose profile was edited by hand after --site-profile
    wrote it, refuses the part: only the profile the site set (and the audit recorded) counts."""
    seed = copy_rulesets(tmp_path / "s-seed", "GZQO")  # profiles/GZQO.yaml (the example's people) kept
    repo = RulesetRepo(tmp_path / "s", seed)
    approve_at_site(tmp_path / "s", by="pi@site.test")
    assert repo.read("main", "profiles/GZQO.yaml")
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    with pytest.raises(ImportRefused, match="an example profile shipped with the box does not count"):
        install(repo, part, "update:e")
    accept(tmp_path / "s", "1.0.0")
    edited = {p[len("profiles/") :]: b for p, b in repo.files("main", "profiles/").items()}
    edited["GZQO.yaml"] = edited["GZQO.yaml"].replace(b"pi@site.test", b"someone@else.test")
    repo.write_dir("main", "main", "profiles/", edited, "hand edit")
    with pytest.raises(ImportRefused, match="no routing .* of its own"):
        install(repo, part, "update:h")
    assert "GZQO/v1.0.0" not in repo.tags()


def test_s4_the_site_profile_is_audited_first(tmp_path: Path, site_env: None) -> None:
    """S4: ``approve.site_profile_set`` (who, when, the profile's sha256) is written before the profile; when it cannot
    be written nothing is; a profile with any key but routing and scopes is refused."""
    seed = copy_rulesets(tmp_path / "seed", "GZQO", "GZQO.yaml")
    repo = RulesetRepo(tmp_path / "s", seed)
    body = yaml.safe_dump(SITE_PROFILE).encode()

    class Broken:
        def append(self, *_a: Any, **_k: Any) -> None:
            raise OSError("the audit cannot be written")

    with pytest.raises(OSError, match="cannot be written"):
        put_site_profile(repo, "GZQO", body, "operator", version="1.0.0", audit=Broken())
    assert repo.read("main", "profiles/GZQO.yaml") is None and repo.read("main", "profiles/GZQO.site-set.json") is None
    audit = AuditLog(tmp_path / "audit")
    sha = put_site_profile(repo, "GZQO", body, "operator", version="1.0.0", audit=audit)
    (ev,) = [e for e in audit_events(tmp_path / "audit") if e["event"] == "approve.site_profile_set"]
    assert (ev["actor"], ev["ruleset"], ev["input_sha"]) == ("operator", "GZQO", sha) and ev["ts"]
    assert ev["detail"]["version"] == "1.0.0" and ev["detail"]["part_sha256"] is None
    import hashlib

    assert hashlib.sha256(repo.read("main", "profiles/GZQO.yaml") or b"").hexdigest() == sha
    with pytest.raises(ImportRefused, match="holds thresholds, title: it sets routing and scopes only"):
        put_site_profile(repo, "GZQO", yaml.safe_dump({**SITE_PROFILE, "thresholds": {}, "title": "x"}).encode(),
                         "operator", version="1.0.0", audit=audit)  # fmt: skip


def test_the_seeded_tag_is_refused_even_where_a_seeded_approval_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third review's M15: on a DEV box the seeded approval loads, and the export still refuses it."""
    monkeypatch.setenv("TB_ENV", "DEV")
    repo = RulesetRepo(tmp_path / "seeded", copy_rulesets(tmp_path / "seed"))
    assert load_approved(repo.path, "GZQO").version == "1.0.0"
    with pytest.raises(ExportRefused, match="names nobody at this box"):
        export(repo, "GZQO", compiled_on(HEAD_RELEASE))


def test_the_record_pins_what_the_manifest_pins(head: RulesetRepo, tmp_path: Path) -> None:
    """Note 2: a record whose pins are not its manifest's is refused (the bundle's compat.json is built from them)."""
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    _rid, files, _m, origin = open_part(part)
    forged = {**origin, "pins": {"judge_prompt": "judge_v4", "terminology_release": "TR-ffffffffffff"}}
    with pytest.raises(PartRefused, match="pins.terminology_release is not the manifest's"):
        open_part(_reseal(part, files, forged))


def test_deep_json_or_yaml_is_refused_not_a_recursion_error(head: RulesetRepo, tmp_path: Path) -> None:
    """Note 3: nesting is counted before parsing."""
    part = make_part(head, tmp_path / "p.zip")
    deep = repart(part, tmp_path / "d.zip", lambda n, b: b"[" * 200000 + b"]" * 200000 if n == ORIGIN else b)
    with pytest.raises(PartRefused, match="ORIGIN.json nests deeper than 256"):
        open_part(deep.read_bytes())
    files = open_part(part.read_bytes())[1]
    files["manifest.yaml"] = b"a: " + b"[" * 50000 + b"]" * 50000 + b"\n"
    box, _updates = site_box(tmp_path)
    with pytest.raises(ImportRefused, match="manifest.yaml nests deeper than 256"):
        install(RulesetRepo(box.repo_dir), _reseal(part.read_bytes(), files), "update:y")


def test_no_free_words_of_the_operator_travel(head: RulesetRepo) -> None:
    """Notes: ``--release`` takes a bundle id (and release_seq) only; the protocol's file names stay at the head box."""
    assert compiled_on(None, "2026.11-1 (release_seq 3)") == {"bundle_id": "2026.11-1", "release_seq": 3}
    with pytest.raises(ExportRefused, match="--release takes a bundle id"):
        compiled_on(None, "2026.11-1 built by Dr Planted")
    data, _origin = export(head, "GZQO", compiled_on(None, "2026.11-1"))
    m = yaml.safe_load(members(data)["GZQO/manifest.yaml"])
    assert "source_documents" not in m and b"GZQO_protocol_v3.pdf" not in data


def test_free_notes_stay_and_a_date_field_holds_a_date(tmp_path: Path, site_env: None) -> None:
    """Notes: ``population.notes`` stays at the head box (the population's stage and arm travel);
    ``source_last_update`` is a date or the export is refused."""

    def plant(d: Path, last: str) -> None:
        mf = d / "manifest.yaml"
        m = yaml.safe_load(mf.read_text(encoding="utf-8"))
        m["population"] = {"disease_stage": "gout", "notes": "CNRY-POPNOTES レビュー担当コメント"}
        m["source_last_update"] = last
        mf.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")

    data, _o = export(_head_with(tmp_path / "a", lambda d: plant(d, "2026-10-01")), "GZQO", compiled_on(HEAD_RELEASE))
    m = yaml.safe_load(members(data)["GZQO/manifest.yaml"])
    assert m["population"] == {"disease_stage": "gout"} and str(m["source_last_update"]) == "2026-10-01"
    assert b"CNRY-POPNOTES" not in data and not [b for b in members(data).values() if b"CNRY-POPNOTES" in b]
    with pytest.raises(ExportRefused, match="source_last_update is not a date"):
        export(_head_with(tmp_path / "b", lambda d: plant(d, "CNRY last update by x")), "GZQO",
               compiled_on(HEAD_RELEASE))  # fmt: skip


# ------------------------------------------------------------------------------------------ the re-check of #1174
ELM_GZQO = "cql/elm/TB_GZQO_v1_0.json"


def _plant_elm(change: Any) -> Any:
    def plant(d: Path) -> None:
        f = d / ELM_GZQO
        e = json.loads(f.read_text(encoding="utf-8"))
        change(e)
        f.write_text(json.dumps(e), encoding="utf-8")

    return plant


@pytest.mark.parametrize(
    "change, where",
    [(lambda e: e["library"].update(x_patients=["CNRY-ELMLIB synthetic person"]), "library.<a key of length 10>"),
     (lambda e: e["library"]["statements"]["def"][0].update(x_note="CNRY-ELMDEF"),
      r"library.statements.def\[0\].<a key of length 6>"),
     (lambda e: e.update(x_top="CNRY-ELMTOP"), "<a key of length 5>: ELM holds the key library only at its top")],
)  # fmt: skip
def test_recheck_an_elm_key_off_the_allow_list_refuses_the_export(
    tmp_path: Path, site_env: None, change: Any, where: str
) -> None:
    """Blocker 1: ELM travels by allow-lists (top ``library``; the library's keys; the compiler's node keys), never by
    removing ``annotation`` alone: an extra library key, a key on a statement definition or an extra top-level key
    refuses the export, naming the key's path; nothing is written."""
    with pytest.raises(ExportRefused, match=f"{ELM_GZQO} {where}"):
        export(_head_with(tmp_path, _plant_elm(change)), "GZQO", compiled_on(HEAD_RELEASE))


@pytest.mark.parametrize(
    "change, where",
    [(lambda e: e["library"].update(x_patients=["CNRY-IMP"]), "library.<a key of length 10>"),
     (lambda e: e["library"]["statements"]["def"][0].update(x_note="CNRY-IMP"),
      r"library.statements.def\[0\].<a key of length 6>"),
     (lambda e: e.update(x="CNRY-IMP"), "<a key of length 1>: ELM holds the key library only at its top"),
     (lambda e: e["library"].update(annotation=[{"s": "CNRY-IMP"}]), "library.<a key of length 10>"),
     (lambda e: e["library"]["statements"]["def"][0].update(annotation=[{"s": "CNRY-IMP"}]),
      r"library.statements.def\[0\].<a key of length 10>")],
)  # fmt: skip
def test_recheck_a_resealed_part_with_an_elm_key_off_the_list_is_refused(
    head: RulesetRepo, tmp_path: Path, change: Any, where: str
) -> None:
    """Blocker 1, the receiving box: a part resealed with a right record and hash whose ELM holds a key off the lists
    (an annotation too) is refused naming the key's path, never installed with the key dropped."""
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    files = open_part(part)[1]
    e = json.loads(files[ELM_GZQO])
    change(e)
    files = {**files, ELM_GZQO: json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8")}
    box, _updates = site_box(tmp_path)
    with pytest.raises(ImportRefused, match=f"rule-set part refused: {ELM_GZQO} {where}"):
        install(RulesetRepo(box.repo_dir), _reseal(part, files), "update:x")
    assert "GZQO/v1.0.0" not in RulesetRepo(box.repo_dir).tags()


def test_recheck_every_shipped_elm_passes_the_allow_lists_and_the_part_holds_only_them() -> None:
    """The node keys were derived from the compiled fixtures and the translator's output: every shipped ELM file
    passes the export's lists, and what the export writes passes the receiving box's lists unchanged."""
    from tb_common.ruleset_part import ELM_LIBRARY_KEYS, elm_allowed, neutral_elm

    root = Path(__file__).resolve().parents[2] / "rulesets"
    shipped = sorted(root.glob("*/cql/elm/*.json"))
    assert len(shipped) >= 16
    for f in shipped:
        out = json.loads(neutral_elm(f.read_bytes(), f"cql/elm/{f.name}"))
        assert set(out) == {"library"} and set(out["library"]) <= ELM_LIBRARY_KEYS and out["library"]["statements"]
        assert elm_allowed(out, f.name, strip=False) == out


def test_recheck_the_site_profile_names_the_person_who_ran_it(
    tmp_path: Path, site_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3, as the fifth review corrected it: ``--site-profile`` without ``--by`` is refused (en, ja, zh-TW) and
    writes nothing; with it, ``approve.site_profile_set`` names the account (``host:<user>``, inside the container the
    service's) and, as ``by_claimed``, the name typed, which the box cannot verify."""
    import getpass
    from types import SimpleNamespace

    import tb_common.audit_writer
    import tb_common.config
    from criteria_compiler import import_ruleset

    seed = copy_rulesets(tmp_path / "seed", "GZQO", "GZQO.yaml")
    RulesetRepo(tmp_path / "s", seed)
    cfg = SimpleNamespace(env=SimpleNamespace(rulesets_path=tmp_path / "s", audit_path=tmp_path / "audit", tz="UTC"))
    monkeypatch.setattr(tb_common.config, "load", lambda: cfg)
    monkeypatch.setattr(tb_common.audit_writer, "open_audit", lambda path, _tz: AuditLog(path))
    monkeypatch.setattr(getpass, "getuser", lambda: "opsuser")
    prof = tmp_path / "profile.yaml"
    prof.write_text(yaml.safe_dump(SITE_PROFILE), encoding="utf-8")
    for by in ([], ["--by", " "]):
        assert import_ruleset.main(["--site-profile", "GZQO", str(prof), "--version", "1.0.0", *by]) == 2
    assert not audit_events(tmp_path / "audit")
    assert RulesetRepo(tmp_path / "s").read("main", "profiles/GZQO.site-set.json") is None
    assert import_ruleset.main(["--site-profile", "GZQO", str(prof), "--version", "1.0.0", "--by", "A. Named"]) == 0
    (ev,) = [e for e in audit_events(tmp_path / "audit") if e["event"] == "approve.site_profile_set"]
    assert (ev["actor"], ev["detail"]["by_claimed"]) == ("host:opsuser", "A. Named")
    assert import_ruleset.main(["--site-profile", "GZQO", str(prof), "--version", "1.0.0", "--by", "x\ny"]) == 2

    def _no_user() -> str:
        raise KeyError("getpwuid(): uid not found: 4242")

    monkeypatch.setattr(getpass, "getuser", _no_user)  # no user variable, no passwd entry: no crash
    assert import_ruleset.main(["--site-profile", "GZQO", str(prof), "--version", "1.0.0", "--by", "A. Named"]) == 0
    assert [e["actor"] for e in audit_events(tmp_path / "audit") if e["event"] == "approve.site_profile_set"][-1] == (
        "host:unknown"
    )


def test_recheck_a_repeat_is_the_tags_own_hash_field_only(head: RulesetRepo, tmp_path: Path) -> None:
    """Finding 4: the same part again is a no-op only when the tag's last field is ``part sha256 <its hash>``; the
    hash written anywhere else in the tag's message (a person's or a bundle's words) does not make it a repeat."""
    from tb_common.ruleset_part import part_sha_on_tag

    part = make_part(head, tmp_path / "p.zip").read_bytes()
    h = open_part(part)[3]["part_sha256"]
    assert part_sha_on_tag(f"GZQO/v1.0.0 (offline update, x); stuff; part sha256 {h}\n") == h
    assert part_sha_on_tag(f"GZQO/v1.0.0 (offline update, part sha256 {h}); approved here") is None
    box, _updates = site_box(tmp_path)
    repo = RulesetRepo(box.repo_dir)
    repo.tag("GZQO/v1.0.0", "main", f"GZQO/v1.0.0 (offline update, part sha256 {h} by someone); approved here")
    with pytest.raises(ImportRefused, match="already exists on this box with other content"):
        install(repo, part, "update:x")


# ------------------------------------------------------------------------------------------------ the fourth review
def _bundle(priv: Path, part: Path, out: Path, seq: int) -> Path:
    ruleset_bundle.build(priv, out.stem, [part], out, release_seq=seq)
    return out


def test_s2_a_second_version_without_a_new_site_act_is_refused_and_rolled_back(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    """S2: the site accepted v1.0.0; v1.0.1 of the same id, in a later bundle, is refused (en, ja, zh-TW, with the
    command that accepts it), the update rolls back and v1.0.0 stays what screens; once the site accepts v1.0.1 the
    same bundle installs it."""
    priv, pub = keys
    box, updates = site_box(tmp_path)
    first = _bundle(priv, make_part(head, tmp_path / "p1" / "GZQO.part.zip"), tmp_path / "rs1.tar", 4)
    assert apply_bundle(first, pub, box, updates, tmp_path / "stage1")["ok"]
    part = _versioned(head, "1.0.1", tmp_path / "p2" / "GZQO.part.zip")
    h = open_part(part.read_bytes())[3]["part_sha256"]
    second = _bundle(priv, part, tmp_path / "rs2.tar", 5)
    with pytest.raises(UpdateFailed) as exc:
        apply_bundle(second, pub, box, updates, tmp_path / "stage2")
    text = str(exc.value)
    assert "GZQO v1.0.1 is not the version this site accepted (its site profile accepts v1.0.0)" in text
    cmd = (f"docker compose exec -T criteria-compiler python -m criteria_compiler.import_ruleset --site-profile GZQO - "
           f'--version 1.0.1 --part-sha256 {h} --by "<your name>" < <profile.yaml>')  # fmt: skip
    assert cmd in text and "rolled back" in text
    assert (
        "ja: GZQO v1.0.1 は、この施設が受け入れた版ではありません" in text
        and "zh-TW: GZQO v1.0.1 不是本院接受的版本" in text
    )
    site = RulesetRepo(tmp_path / "site")
    assert "GZQO/v1.0.1" not in site.tags() and load_approved(tmp_path / "site", "GZQO").version == "1.0.0"
    (rolled,) = [e for e in audit_events(tmp_path / "audit") if e["event"] == "update.rolled_back"]
    assert "GZQO v1.0.1 is not the version this site accepted" in rolled["detail"]["error"]
    assert json.loads((updates / "installed.json").read_text())["release_seq"] == 4

    accept(tmp_path / "site", "1.0.1", h)  # the site's act for this version
    assert apply_bundle(second, pub, box, updates, tmp_path / "stage3")["ok"]
    assert load_approved(tmp_path / "site", "GZQO").version == "1.0.1"
    sets = [e for e in audit_events(tmp_path / "site-audit") if e["event"] == "approve.site_profile_set"]
    assert [(e["actor"], e["ruleset"], e["detail"]["version"], e["detail"]["part_sha256"]) for e in sets] == [
        ("operator", "GZQO", "1.0.0", None), ("operator", "GZQO", "1.0.1", h)]  # fmt: skip


def test_s2_a_hash_the_site_did_not_accept_is_refused(head: RulesetRepo, tmp_path: Path) -> None:
    """S2: the site named the part's sha256 with the version: another part of that version is refused; the one it
    named installs."""
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    h = open_part(part)[3]["part_sha256"]
    box, _updates = site_box(tmp_path, profile=False)
    accept(box.repo_dir, "1.0.0", "0" * 64)
    with pytest.raises(ImportRefused, match=f"GZQO v1.0.0 has part sha256 {h}, not the one this site accepted "
                                            f"\\({'0' * 64}\\); nothing was installed"):  # fmt: skip
        install(RulesetRepo(box.repo_dir), part, "update:x")
    assert "GZQO/v1.0.0" not in RulesetRepo(box.repo_dir).tags()
    accept(box.repo_dir, "1.0.0", h)
    assert install(RulesetRepo(box.repo_dir), part, "update:x") == "GZQO/v1.0.0"


def test_s2_a_profile_of_the_first_form_accepts_no_version(head: RulesetRepo, tmp_path: Path) -> None:
    """S2: a profile written by the first form of ``--site-profile`` (a mark without a version) accepts nothing: the
    part is refused, saying so and how to accept it."""
    box, _updates = site_box(tmp_path, profile=False)
    repo = RulesetRepo(box.repo_dir)
    body = yaml.safe_dump(SITE_PROFILE, allow_unicode=True, sort_keys=False).encode()
    import hashlib

    current = {p[len("profiles/") :]: b for p, b in repo.files("main", "profiles/").items()}
    current["GZQO.yaml"] = body
    current["GZQO.site-set.json"] = json.dumps({"format": "trialbox-site-profile/1", "ruleset": "GZQO",
                                                "sha256": hashlib.sha256(body).hexdigest()}).encode()  # fmt: skip
    repo.write_dir("main", "main", "profiles/", current, "site profile GZQO (first form)")
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    with pytest.raises(ImportRefused, match="the site profile for GZQO was written before a site profile named the "
                                            "version it accepts, so it accepts no version of GZQO; nothing was "
                                            "installed. To accept it.*--site-profile GZQO - --version 1.0.0"):  # fmt: skip
        install(repo, part, "update:x")
    assert "GZQO/v1.0.0" not in repo.tags()


def test_s2_the_command_line_needs_the_version_and_reads_standard_input(
    tmp_path: Path, site_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from types import SimpleNamespace

    import tb_common.audit_writer
    import tb_common.config
    from criteria_compiler import import_ruleset

    seed = copy_rulesets(tmp_path / "seed", "GZQO", "GZQO.yaml")
    repo = RulesetRepo(tmp_path / "s", seed)
    cfg = SimpleNamespace(env=SimpleNamespace(rulesets_path=tmp_path / "s", audit_path=tmp_path / "audit", tz="UTC"))
    monkeypatch.setattr(tb_common.config, "load", lambda: cfg)
    monkeypatch.setattr(tb_common.audit_writer, "open_audit", lambda path, _tz: AuditLog(path))
    with pytest.raises(SystemExit) as exc:
        import_ruleset.main(["--site-profile", "GZQO", "-"])
    assert exc.value.code == 2 and "--site-profile needs --version" in capsys.readouterr().err
    prof = tmp_path / "profile.yaml"
    prof.write_text(yaml.safe_dump(SITE_PROFILE), encoding="utf-8")
    assert import_ruleset.main(["--site-profile", "GZQO", str(prof), "--version", "1.0", "--by", "op"]) == 1
    assert "is not a rule set version" in capsys.readouterr().err
    assert import_ruleset.main(["--site-profile", "GZQO", str(prof), "--version", "1.0.1", "--part-sha256", "ABC",
                                "--by", "op"]) == 1  # fmt: skip
    assert "64 lowercase hexadecimal" in capsys.readouterr().err
    assert repo.read("main", "profiles/GZQO.site-set.json") is None and not audit_events(tmp_path / "audit")
    stdin = SimpleNamespace(buffer=io.BytesIO(yaml.safe_dump(SITE_PROFILE).encode()))
    monkeypatch.setattr("sys.stdin", stdin)
    assert import_ruleset.main(["--site-profile", "GZQO", "-", "--version", "1.0.1", "--by", "op"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "1.0.1"
    mark = json.loads(repo.read("main", "profiles/GZQO.site-set.json") or b"")
    assert (mark["format"], mark["version"], mark["part_sha256"]) == ("trialbox-site-profile/2", "1.0.1", None)


def test_n2_a_repeat_is_said_and_recorded_as_already_present(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    """N2: the same part in a later bundle changes nothing; the step and ``update.applied`` say "already present",
    with the id and version, not "imported"."""
    priv, pub = keys
    box, updates = site_box(tmp_path)
    part = make_part(head, tmp_path / "p" / "GZQO.part.zip")
    assert apply_bundle(_bundle(priv, part, tmp_path / "rs1.tar", 4), pub, box, updates, tmp_path / "s1")["ok"]
    said: list[str] = []
    m = verify(_bundle(priv, part, tmp_path / "rs2.tar", 5), pub, tmp_path / "s2", trust_file=updates / "trust.json",
               installed_file=updates / "installed.json")  # fmt: skip
    assert Updater(box, updates, say=said.append).run(Plan.load(tmp_path / "s2", summary(m)))["ok"]
    assert any("0 imported, 1 already present: GZQO v1.0.0: already present, nothing changed (GZQO.part.zip)" in s
               for s in said), said  # fmt: skip
    applied = [e["detail"]["rulesets"] for e in audit_events(tmp_path / "audit") if e["event"] == "update.applied"]
    assert applied == [["GZQO v1.0.0: imported (GZQO.part.zip)"],
                       ["GZQO v1.0.0: already present, nothing changed (GZQO.part.zip)"]]  # fmt: skip


def test_n2_the_container_box_reads_the_imports_result_line(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N2: ``ComposeBox.rulesets`` reads the import's last output line: the line ``main`` prints for a part imported
    and for the same part again."""
    from types import SimpleNamespace

    import tb_common.config
    from criteria_compiler import import_ruleset

    box, _updates = site_box(tmp_path)
    part = make_part(head, tmp_path / "GZQO.part.zip")
    cfg = SimpleNamespace(env=SimpleNamespace(rulesets_path=box.repo_dir), settings=SimpleNamespace(thresholds=None))
    monkeypatch.setattr(tb_common.config, "load", lambda: cfg)
    monkeypatch.setattr(import_ruleset, "box_pins_problem", lambda _m: None)
    assert import_ruleset.main([str(part), "--by", "update:x"]) == 0
    assert ruleset_line("GZQO.part.zip", capsys.readouterr().out) == "GZQO v1.0.0: imported (GZQO.part.zip)"
    assert import_ruleset.main([str(part), "--by", "update:y"]) == 0
    out = capsys.readouterr().out
    lines = [json.loads(ln) for ln in out.splitlines()]
    assert lines[0]["already_present"] is True and lines[-1] == {"installed": "GZQO/v1.0.0", "rule_set_part": True}
    assert ruleset_line("GZQO.part.zip", out) == "GZQO v1.0.0: already present, nothing changed (GZQO.part.zip)"
    assert ruleset_line("x.zip", "") == "x.zip: imported (no result line read)"


def test_n1_the_bundle_holds_the_bytes_that_were_checked(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N1: the part file swapped on disk right after its check: the bundle holds (and its manifest records) the bytes
    that were checked, not the swapped file."""
    import hashlib

    import tb_common.ruleset_part as rp

    priv, pub = keys
    part = make_part(head, tmp_path / "GZQO.part.zip")
    checked = part.read_bytes()
    real = rp.open_part

    def open_then_swap(data: bytes) -> Any:
        out = real(data)
        part.write_bytes(b"PK swapped after the check")
        return out

    monkeypatch.setattr(rp, "open_part", open_then_swap)
    m = ruleset_bundle.build(priv, "rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert m["files"][0]["sha256"] == hashlib.sha256(checked).hexdigest()
    with tarfile.open(tmp_path / "rs.tar") as tf:
        fh = tf.extractfile("files/GZQO.part.zip")
        assert fh is not None and fh.read() == checked
    assert verify(tmp_path / "rs.tar", pub, installed_file=head_installed(tmp_path))["bundle_id"] == "rs1"


def test_n1_a_part_changed_between_its_check_and_the_signature_is_refused(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N1: whatever reaches ``sign_bundle.build`` is compared after the build with the checked bytes: a file changed
    in between refuses the build and leaves no bundle."""
    priv, _pub = keys
    part = make_part(head, tmp_path / "GZQO.part.zip")
    real = sign_bundle.build

    def build_a_changed_file(key: Path, bundle_id: str, items: list[tuple[str, Path, str]], out: Path,
                             **kw: Any) -> dict[str, Any]:  # fmt: skip
        for _kind, src, _dest in items:
            src.write_bytes(src.read_bytes() + b"\0")
        return real(key, bundle_id, items, out, **kw)

    monkeypatch.setattr(sign_bundle, "build", build_a_changed_file)
    with pytest.raises(SystemExit, match="GZQO.part.zip changed between its check and the signature"):
        ruleset_bundle.build(priv, "rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert not (tmp_path / "rs.tar").exists()


# ------------------------------------------------------------------------------------------------ the fifth review
def _cli(monkeypatch: pytest.MonkeyPatch, rulesets: Path, audit: Path) -> Any:
    from types import SimpleNamespace

    import tb_common.audit_writer
    import tb_common.config
    from criteria_compiler import import_ruleset

    cfg = SimpleNamespace(env=SimpleNamespace(rulesets_path=rulesets, audit_path=audit, tz="UTC"),
                          settings=SimpleNamespace(thresholds=None))  # fmt: skip
    monkeypatch.setattr(tb_common.config, "load", lambda: cfg)
    monkeypatch.setattr(tb_common.audit_writer, "open_audit", lambda path, _tz: AuditLog(path))
    monkeypatch.setattr(import_ruleset, "box_pins_problem", lambda _m: None)
    return import_ruleset


def test_r5_the_export_and_the_accept_command_name_the_person_beside_the_account(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 1: the documented accept command carries ``--by``; ``export_part`` refuses without it (en, ja, zh-TW) and
    writes nothing; with it, ``approve.part_exported`` names the account and, as ``by_claimed``, the name typed."""
    import getpass

    from criteria_compiler import export_part

    assert accept_command("GZQO", "1.0.1").endswith('--version 1.0.1 --by "<your name>" < <profile.yaml>')
    _cli(monkeypatch, tmp_path / "head", tmp_path / "head-audit")
    monkeypatch.setattr(getpass, "getuser", lambda: "tbsvc")
    out = tmp_path / "GZQO.part.zip"
    argv = ["GZQO", "--out", str(out), "--release", "2026.11-1 (release_seq 3)"]
    assert export_part.main(argv) == 2
    err = capsys.readouterr().err
    assert 'export_part needs --by "<your name>"' in err and "ja: export_part には --by" in err and "zh-TW:" in err
    assert not out.exists() and not audit_events(tmp_path / "head-audit")
    assert export_part.main([*argv, "--by", "A. Named"]) == 0
    printed = json.loads(capsys.readouterr().out)
    (ev,) = [e for e in audit_events(tmp_path / "head-audit") if e["event"] == "approve.part_exported"]
    assert (ev["actor"], ev["detail"]["by_claimed"]) == ("host:tbsvc", "A. Named")
    assert printed["part_sha256"] == ev["output_sha"] == open_part(out.read_bytes())[3]["part_sha256"]


def test_r5_a_refused_part_reaches_the_operator_whole(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 2: the command line's refusal of a part the site has not accepted: exit 2, no traceback; its first line a
    short English sentence with the id and version, its last line the exact accepting command (under 400
    characters). The update keeps the import's first line and the last 600 characters of its standard error
    (``run_cmd``), and ``update.rolled_back`` the first 500 characters of the failure: both hold what is needed."""
    import sys

    from criteria_compiler.import_ruleset import ACCEPT_LINE_MAX, NotAccepted, refusal_lines

    from tools.trialbox.update import run_cmd

    box, _updates = site_box(tmp_path)  # accepts v1.0.0
    part = _versioned(head, "1.0.1", tmp_path / "p" / "GZQO.part.zip")
    h = open_part(part.read_bytes())[3]["part_sha256"]
    cli = _cli(monkeypatch, box.repo_dir, tmp_path / "a")
    assert cli.main([str(part), "--by", "update:x"]) == 2
    err = capsys.readouterr().err
    cmd = accept_command("GZQO", "1.0.1", h)
    lines = err.splitlines()
    assert lines[-1] == f"to accept GZQO v1.0.1, in deploy/ on the box's host: {cmd}" and len(lines[-1]) < 400
    assert lines[-1].isascii() and cmd in err[-600:]
    assert lines[0].isascii() and lines[0].startswith("rule set zip REFUSED: the rule-set part GZQO v1.0.1 is not ")
    assert "GZQO v1.0.1" in err[:500] and "the command that accepts it follows on the last line" in err[:500]
    assert "ja: GZQO v1.0.1" in err and "zh-TW: GZQO v1.0.1" in err and len(err) > 1300 and "Traceback" not in err
    assert "GZQO/v1.0.1" not in RulesetRepo(box.repo_dir).tags()

    # the container box: the update's own command runner, then the failure as the update records it
    script = tmp_path / "say.py"
    script.write_text(f"import sys\nsys.stderr.write({err!r})\nsys.exit(2)\n", encoding="utf-8")
    with pytest.raises(UpdateFailed) as exc:
        run_cmd([sys.executable, str(script)])
    failed = f"UpdateFailed: {exc.value}"
    assert cmd in failed  # the terminal's step line and the final message hold the failure whole
    assert "GZQO v1.0.1 is not accepted at this site" in failed[:500]  # update.rolled_back keeps these 500

    # the longest id and version still fit one line; a longer command goes alone on its own line, said so
    long = accept_command("A" * 32, "9999.9999.9999", "f" * 64)
    (short,) = [ln for ln in refusal_lines(NotAccepted("x", "A" * 32, "9999.9999.9999", long)) if long in ln]
    assert len(short) <= ACCEPT_LINE_MAX
    over = refusal_lines(NotAccepted("x", "GZQO", "1.0.1", "c" * 400))
    assert over[-1] == "c" * 400 and "it follows alone" in over[-2]


def test_r5_any_other_refusal_of_a_hand_run_zip_ends_without_a_traceback(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box, _updates = site_box(tmp_path)
    bad = _tampered(make_part(head, tmp_path / "p.zip"), tmp_path / "bad.zip")
    assert _cli(monkeypatch, box.repo_dir, tmp_path / "a").main([str(bad), "--by", "update:x"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("rule set zip REFUSED: rule-set part refused") and "Traceback" not in err


def test_r5_patterns_are_held_whole_and_in_ascii(tmp_path: Path, site_env: None) -> None:
    """Item 4: "1.0.1" plus a line break, other scripts' digits, an id with a line break are no version or id."""
    from tb_common.ruleset_part import RULESET_ID, SHA256, VERSION

    assert VERSION.fullmatch("1.0.1") and RULESET_ID.fullmatch("GZQO") and SHA256.fullmatch("a" * 64)
    for v in ("1.0.1\n", "\uff11.0.1", "\u0661.\u0660.\u0661", "\u0967.0.1"):
        assert not VERSION.fullmatch(v), v
    assert not RULESET_ID.fullmatch("GZQO\n") and not SHA256.fullmatch("a" * 64 + "\n")
    repo = RulesetRepo(tmp_path / "s", copy_rulesets(tmp_path / "seed", "GZQO", "GZQO.yaml"))
    for v in ("1.0.1\n", "\u0661.\u0660.\u0661"):
        with pytest.raises(ImportRefused, match="is not a rule set version"):
            put_site_profile(repo, "GZQO", yaml.safe_dump(SITE_PROFILE).encode(), "op", version=v,
                             audit=AuditLog(tmp_path / "audit"))  # fmt: skip
    with pytest.raises(ImportRefused, match="is not a rule set id"):
        put_site_profile(repo, "GZQO\n", yaml.safe_dump(SITE_PROFILE).encode(), "op", version="1.0.1",
                         audit=AuditLog(tmp_path / "audit"))  # fmt: skip
    assert not audit_events(tmp_path / "audit")


def test_r5_the_site_profile_is_capped_and_strict(
    tmp_path: Path, site_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 4: at most 64 KiB (also on standard input, read no further); an unknown field at any depth is refused
    with a sentence (not a traceback); nothing is audited or written."""
    import io
    from types import SimpleNamespace

    repo = RulesetRepo(tmp_path / "s", copy_rulesets(tmp_path / "seed", "GZQO", "GZQO.yaml"))
    cli = _cli(monkeypatch, tmp_path / "s", tmp_path / "audit")
    big = yaml.safe_dump(SITE_PROFILE).encode() + b"#" + b"x" * (64 * 1024)
    stdin = io.BytesIO(big + b"y" * 100000)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=stdin))
    assert cli.main(["--site-profile", "GZQO", "-", "--version", "1.0.1", "--by", "A. Named"]) == 1
    assert "larger than 64 KiB" in capsys.readouterr().err and stdin.tell() == 64 * 1024 + 1
    for prof in ({**SITE_PROFILE, "scopes": {"screen": {**SITE_PROFILE["scopes"]["screen"], "zzz": 1}}},
                 {**SITE_PROFILE, "routing": {**SITE_PROFILE["routing"], "bcc": ["x@y.test"]}}):  # fmt: skip
        with pytest.raises(ImportRefused, match="does not hold the routing and scopes a rule set takes"):
            put_site_profile(repo, "GZQO", yaml.safe_dump(prof).encode(), "op", version="1.0.1",
                             audit=AuditLog(tmp_path / "audit"))  # fmt: skip
    assert not audit_events(tmp_path / "audit") and repo.read("main", "profiles/GZQO.site-set.json") is None


def test_r5_a_mark_for_another_id_does_not_count(head: RulesetRepo, tmp_path: Path) -> None:
    """Item 4: a site-set mark whose ``ruleset`` is another id (copied beside this id's profile) accepts nothing."""
    import hashlib

    box, _updates = site_box(tmp_path, profile=False)
    repo = RulesetRepo(box.repo_dir)
    body = yaml.safe_dump(SITE_PROFILE, allow_unicode=True, sort_keys=False).encode()
    current = {p[len("profiles/") :]: b for p, b in repo.files("main", "profiles/").items()}
    current["GZQO.yaml"] = body
    current["GZQO.site-set.json"] = json.dumps({"format": "trialbox-site-profile/2", "ruleset": "OTHER",
                                                "sha256": hashlib.sha256(body).hexdigest(), "version": "1.0.0",
                                                "part_sha256": None}).encode()  # fmt: skip
    repo.write_dir("main", "main", "profiles/", current, "a mark of another id")
    part = make_part(head, tmp_path / "p.zip").read_bytes()
    with pytest.raises(ImportRefused, match="no routing .* of its own for GZQO"):
        install(repo, part, "update:x")
    assert "GZQO/v1.0.0" not in repo.tags()


def test_r5_a_bundle_without_a_rule_set_says_0_imported_0_already_present(
    keys: tuple[Path, Path], tmp_path: Path
) -> None:
    """Item 5 (c): the step's text for a bundle with no rule-set zip, and ``update.applied`` with no entry."""
    priv, pub = keys
    box, updates = site_box(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("synthetic\n", encoding="utf-8")
    sign_bundle.build(priv, "2026.11-1-o1", [("other", note, "note.txt")], tmp_path / "o.tar", release_seq=4)
    said: list[str] = []
    m = verify(tmp_path / "o.tar", pub, tmp_path / "st", trust_file=updates / "trust.json",
               installed_file=updates / "installed.json")  # fmt: skip
    assert Updater(box, updates, say=said.append).run(Plan.load(tmp_path / "st", summary(m)))["ok"]
    assert any("rulesets: 0 imported, 0 already present" in s for s in said), said
    (applied,) = [e for e in audit_events(tmp_path / "audit") if e["event"] == "update.applied"]
    assert applied["detail"]["rulesets"] == []
