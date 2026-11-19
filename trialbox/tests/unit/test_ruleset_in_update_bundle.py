"""10D-28 (D-1369; review 19-9): a rule set compiled and approved on one box, carried to another in a vendor-signed
update bundle, interim for the dry run.

* the export carries criteria and codes only (no ``tests/``), from the box's own approval tag, never a seeded or an
  arrived one;
* a bundle may carry a rule-set part alone: signed with the vendor key, verified like any bundle (no release record,
  no image, no host tree), applied through the update path, ``update.applied`` audited with the rule set named;
* the receiving box records where it came from (bundle, the compiling box's release, the content sha256) on the
  approval tag and lists it as arrived in a vendor bundle; its installed release keeps its commit;
* a part whose content does not match its recorded hash is refused and rolled back; a bundle changed after signing
  is rejected by the verifier.

The update path runs on :class:`ScreenOnlyBox`: the real verifier, the real ``Updater`` and the real rule-set import,
with no database or images (those steps are the container box's, unchanged). Synthetic data only.
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.export_part import ExportRefused, compiled_on, export
from criteria_compiler.import_ruleset import install
from criteria_compiler.repo import RulesetRepo
from tb_common.audit import AuditLog
from tb_common.ruleset import arrived_in_bundle, load_approved
from tb_common.ruleset_part import ARRIVED_MARK, ORIGIN, PartRefused, carried, content_sha256, open_part

from tests.rulesets_guard import approve_at_site, copy_rulesets
from tools import ruleset_bundle, sign_bundle
from tools.trialbox.update import Plan, UpdateFailed, Updater
from tools.verify_update import Rejected, summary, verify

HEAD_RELEASE = {"format": "trialbox-installed/1", "release_seq": 3, "bundle_id": "2026.11-1",
                "commit": "a" * 40, "state": {}}  # fmt: skip


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
            install(RulesetRepo(self.repo_dir), z.read_bytes(), f"update:{plan.bundle_id}")
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


@pytest.fixture
def site_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")  # both boxes are site boxes: a seeded approval is no approval


@pytest.fixture
def head(tmp_path: Path, site_env: None) -> RulesetRepo:
    """The head box's repository: GZQO compiled (the shipped files, ``tests/`` included) and approved at that box."""
    repo = RulesetRepo(tmp_path / "head", copy_rulesets(tmp_path / "seed"))
    approve_at_site(tmp_path / "head", by="pi@head.test")
    return repo


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, Path]:
    return sign_bundle.keygen(tmp_path / "vendor")


def make_part(head: RulesetRepo, out: Path) -> Path:
    data, _origin = export(head, "GZQO", compiled_on(HEAD_RELEASE))
    out.write_bytes(data)
    return out


def site_box(tmp_path: Path) -> tuple[ScreenOnlyBox, Path]:
    seed = copy_rulesets(tmp_path / "site-seed", "GZQO")
    RulesetRepo(tmp_path / "site", seed)
    approve_at_site(tmp_path / "site", by="pi@site.test")
    updates = tmp_path / "updates"
    updates.mkdir()
    (updates / "installed.json").write_text(json.dumps({**HEAD_RELEASE, "commit": "b" * 40}))
    return ScreenOnlyBox(tmp_path / "site", AuditLog(tmp_path / "audit")), updates


# ------------------------------------------------------------------------------------------------ the export
def test_the_part_carries_criteria_and_codes_only(head: RulesetRepo, tmp_path: Path) -> None:
    part = make_part(head, tmp_path / "GZQO.part.zip")
    names = zipfile.ZipFile(part).namelist()
    assert ORIGIN in names and not [n for n in names if "/tests/" in n]
    assert {n.split("/")[1] for n in names if n != ORIGIN} <= {"manifest.yaml", "labels.yaml", "ir", "valuesets",
                                                               "cql", "sql"}  # fmt: skip
    rid, files, manifest, origin = open_part(part.read_bytes())
    assert (rid, manifest["status"], origin["left_out"]) == ("GZQO", "approved", ["tests/"])
    assert origin["content_sha256"] == content_sha256(files) and origin["approval_tag"] == "GZQO/v1.0.0"
    assert origin["compiled_on"] == {"bundle_id": "2026.11-1", "release_seq": 3, "commit": "a" * 40}
    assert origin["pins"]["models"]["judge_prompt"] == manifest["models"]["judge_prompt"]
    at = datetime(2026, 11, 19, tzinfo=UTC)  # the same approved version and time give the same bytes
    assert (
        export(head, "GZQO", compiled_on(HEAD_RELEASE), at)[0] == export(head, "GZQO", compiled_on(HEAD_RELEASE), at)[0]
    )


def test_a_file_that_is_no_criterion_or_code_refuses_the_export() -> None:
    with pytest.raises(PartRefused, match="patients.csv"):
        carried({"manifest.yaml": b"id: X\n", "patients.csv": b"mrn\n"})
    assert carried({"manifest.yaml": b"x", "tests/patients.ndjson": b"{}"}) == {"manifest.yaml": b"x"}


def test_only_the_boxs_own_approval_is_exported(tmp_path: Path, site_env: None) -> None:
    repo = RulesetRepo(tmp_path / "seeded", copy_rulesets(tmp_path / "seed"))  # seeded: approved by nobody here
    with pytest.raises(Exception, match="not approved at this site|names nobody"):
        export(repo, "GZQO", compiled_on(HEAD_RELEASE))
    repo.retag("GZQO/v1.0.0", f"GZQO/v1.0.0 (offline update, update:x); {ARRIVED_MARK}: update:x")
    with pytest.raises(ExportRefused, match="arrived in a vendor bundle itself"):
        export(repo, "GZQO", compiled_on(HEAD_RELEASE))
    with pytest.raises(ExportRefused, match="name the release"):
        compiled_on(None, " ")


# ------------------------------------------------------------------------------------------------ the bundle
def test_a_bundle_may_carry_a_rule_set_alone(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    priv, pub = keys
    part = make_part(head, tmp_path / "GZQO.part.zip")
    m = ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert [f["kind"] for f in m["files"]] == ["ruleset"] and "release_sha256" not in m
    v = verify(tmp_path / "rs.tar", pub, tmp_path / "stage", installed_file=None)
    assert v["release"] is None and (tmp_path / "stage" / "ruleset" / "GZQO.part.zip").read_bytes() == part.read_bytes()


def test_the_vendor_command_line(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path,
                                 capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    part = make_part(head, tmp_path / "GZQO.part.zip")
    argv = ["--key", str(keys[0]), "--id", "rs1", "--release-seq", "4", "--out", str(tmp_path / "rs.tar"), str(part)]
    assert ruleset_bundle.main(argv) == 0
    assert "1 rule-set part(s), bundle rs1, release_seq 4" in capsys.readouterr().out
    assert verify(tmp_path / "rs.tar", keys[1])["bundle_id"] == "rs1"


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
    msg = RulesetRepo(site).tag_message("GZQO/v1.0.0")
    origin = open_part(part.read_bytes())[3]
    for words in (ARRIVED_MARK, "update:2026.11-1-rs1", "2026.11-1 (release_seq 3, commit aaaaaaaaaaaa)",
                  origin["content_sha256"], "its tag GZQO/v1.0.0"):  # fmt: skip
        assert words in msg, words
    assert "pi@head.test" not in msg  # who approved at the head box is not carried
    applied = [e for e in audit_events(tmp_path / "audit") if e["event"] == "update.applied"]
    assert len(applied) == 1 and applied[0]["detail"]["rulesets"] == ["GZQO.part.zip"]
    assert applied[0]["detail"]["files"][0]["kind"] == "ruleset"
    inst = json.loads((updates / "installed.json").read_text())
    assert inst["release_seq"] == 4 and inst["bundle_id"] == "2026.11-1-rs1"
    assert inst["commit"] == "b" * 40 and inst["release_bundle_id"] == "2026.11-1"  # the box's code is unchanged

    from console.backend import ruleset_infos

    infos = {i.id: i for i in ruleset_infos(site)}
    assert infos["GZQO"].origin == "vendor_bundle" and infos["RA-JAK"].origin == ""


def _tampered(part: Path, out: Path) -> Path:
    """The part with one criterion's bytes changed and its ORIGIN.json (and recorded hash) kept."""
    out.parent.mkdir(parents=True, exist_ok=True)
    changed = False
    with zipfile.ZipFile(part) as src, zipfile.ZipFile(out, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            if not changed and n.startswith("GZQO/ir/") and b'"inclusion"' in data:
                data = data.replace(b'"inclusion"', b'"exclusion"', 1)
                changed = True
            dst.writestr(n, data)
    assert changed
    return out


def test_a_part_whose_hash_does_not_match_is_refused(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    priv, pub = keys
    box, updates = site_box(tmp_path)
    bad = _tampered(make_part(head, tmp_path / "GZQO.part.zip"), tmp_path / "bad" / "GZQO.part.zip")
    with pytest.raises(SystemExit, match="content sha256"):  # the vendor's tool reads it first
        ruleset_bundle.build(priv, "x1", [bad], tmp_path / "x.tar", release_seq=4)
    # signed past the tool (sign_bundle directly): the receiving box refuses it and rolls back
    sign_bundle.build(priv, "2026.11-1-rs2", [("ruleset", bad, bad.name)], tmp_path / "bad.tar", release_seq=4)
    with pytest.raises(UpdateFailed, match="content sha256 .* refused.*rolled back"):
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
        verify(tmp_path / "swapped.tar", pub, stage)
    assert not stage.exists() or not [p for p in stage.rglob("*") if p.is_file()]  # nothing staged
