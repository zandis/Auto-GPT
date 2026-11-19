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
from criteria_compiler.import_ruleset import ImportRefused, box_pins_problem, install, put_site_profile
from criteria_compiler.repo import RulesetRepo
from tb_common.audit import AuditLog
from tb_common.ruleset import arrived_in_bundle, load_approved
from tb_common.ruleset_part import ARRIVED_MARK, ORIGIN, PartRefused, build_part, neutral_files, open_part, part_sha256

from tests.rulesets_guard import approve_at_site, copy_rulesets
from tools import ruleset_bundle, sign_bundle
from tools.trialbox.update import Plan, UpdateFailed, Updater
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
            install(
                RulesetRepo(self.repo_dir), z.read_bytes(), f"update:{plan.bundle_id}", pins_problem=box_pins_problem
            )
            done.append(z.name)
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
    m = verify(bundle, pub, stage, installed_file=updates / "installed.json")
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


def site_box(tmp_path: Path, profile: bool = True, keep: tuple[str, ...] = ()) -> tuple[ScreenOnlyBox, Path]:
    """A site box without GZQO (unless ``keep`` names it), with its own routing and scope for it when ``profile``."""
    seed = copy_rulesets(tmp_path / "site-seed", *(() if "GZQO" in keep else ("GZQO",)), "GZQO.yaml")
    repo = RulesetRepo(tmp_path / "site", seed)
    approve_at_site(tmp_path / "site", by="pi@site.test")
    if profile:
        put_site_profile(repo, "GZQO", yaml.safe_dump(SITE_PROFILE).encode(), "operator",
                         audit=AuditLog(tmp_path / "site-audit"))  # fmt: skip
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
    assert "1 rule-set part(s), bundle rs1, release_seq 4" in capsys.readouterr().out
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
    assert len(applied) == 1 and applied[0]["detail"]["rulesets"] == ["GZQO.part.zip"]
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
    with pytest.raises(UpdateFailed, match="no routing .* of its own for GZQO.*--site-profile GZQO"):
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

    box, _updates = site_box(tmp_path)
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
    box, _updates = site_box(tmp_path)
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
    put_site_profile(repo, "GZQO", yaml.safe_dump(SITE_PROFILE).encode(), "operator", audit=AuditLog(tmp_path / "a"))
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
        put_site_profile(repo, "GZQO", body, "operator", audit=Broken())
    assert repo.read("main", "profiles/GZQO.yaml") is None and repo.read("main", "profiles/GZQO.site-set.json") is None
    audit = AuditLog(tmp_path / "audit")
    sha = put_site_profile(repo, "GZQO", body, "operator", audit=audit)
    (ev,) = [e for e in audit_events(tmp_path / "audit") if e["event"] == "approve.site_profile_set"]
    assert (ev["actor"], ev["ruleset"], ev["input_sha"]) == ("operator", "GZQO", sha) and ev["ts"]
    import hashlib

    assert hashlib.sha256(repo.read("main", "profiles/GZQO.yaml") or b"").hexdigest() == sha
    with pytest.raises(ImportRefused, match="holds thresholds, title: it sets routing and scopes only"):
        put_site_profile(repo, "GZQO", yaml.safe_dump({**SITE_PROFILE, "thresholds": {}, "title": "x"}).encode(),
                         "operator", audit=audit)  # fmt: skip


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
