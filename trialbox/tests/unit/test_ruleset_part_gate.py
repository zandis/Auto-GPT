"""10D-28 (D-1369), the integrator's review of #1174 at edb77053: eight findings, each reproduced at the real call.

1-3 are one fault by three roads: a signed rule set reached screening without the site's acceptance of that version
(a plain zip with no ``ORIGIN.json``; a part whose minimum release is zero on an older site; the standalone import
command with no evidence of a verified signature). The gate is one function (``import_ruleset.install_outcome``):
nothing from outside is written unless the update path verified its bundle in this run (``Verified``, which only the
update step builds) and the site accepted that id and version (and hash). :func:`test_every_road_with_every_bypass`
walks every road. 4: a manifest-listed criterion missing from the part. 5: the accepted department restriction at the
screening entry point. 6: a repeat applies the site's current routing. 7: value-set scalars are scalars. 8: no byte of
a part's zip outside its members. Synthetic data only.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from criteria_compiler.export_part import ExportRefused, compiled_on, export
from criteria_compiler.repo import RulesetRepo
from tb_common.ruleset import load_approved
from tb_common.ruleset_part import PartRefused, check_valueset, open_part

from tests.rulesets_guard import approve_at_site, copy_rulesets
from tests.unit.test_ruleset_in_update_bundle import (
    HEAD_RELEASE,
    PLANTED,
    SITE_PROFILE,
    ScreenOnlyBox,
    _cli,
    _head_with,
    _plain_zip,
    _plant,
    _reseal,
    accept,
    apply_bundle,
    make_part,
    members,
    site_box,
)
from tools import ruleset_bundle, sign_bundle
from tools.trialbox.update import UpdateFailed


@pytest.fixture
def site_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")  # both boxes are site boxes: a seeded approval is no approval


@pytest.fixture
def head(tmp_path: Path, site_env: None) -> RulesetRepo:
    """The head box's repository, GZQO approved there (as the card's own test makes it)."""
    seed = copy_rulesets(tmp_path / "seed")
    _plant(seed)
    repo = RulesetRepo(tmp_path / "head", seed)
    approve_at_site(tmp_path / "head", by=PLANTED[0])
    return repo


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, Path]:
    return sign_bundle.keygen(tmp_path / "vendor")


def _signed(priv: Path, zips: list[Path], out: Path, seq: int, min_installed: int = 0) -> Path:
    """A bundle the vendor signs around the given zips as they are (``make_bundle.sh --rulesets`` signs any zip of
    its folder this way): the receiving box alone must refuse what it must."""
    sign_bundle.build(priv, out.stem, [("ruleset", z, z.name) for z in zips], out, release_seq=seq,
                      min_installed_version=min_installed, valid_days=30,
                      compat=sign_bundle.permissive_compat(out.stem))  # fmt: skip
    return out


def _refused(bundle: Path, pub: Path, box: ScreenOnlyBox, updates: Path, stage: Path) -> str:
    """The update of ``bundle`` fails and is rolled back (the test box checks no tag was written); its failure."""
    with pytest.raises(UpdateFailed) as e:
        apply_bundle(bundle, pub, box, updates, stage)
    return str(e.value)


def _tags(box: ScreenOnlyBox) -> list[str]:
    return RulesetRepo(box.repo_dir).tags("GZQO/")


def _plain(version: str, out: Path) -> Path:
    """The vendor's plain GZQO zip (no ``ORIGIN.json``), at ``version``, with its own routing and scopes."""
    files = members(_plain_zip())
    m = yaml.safe_load(files["GZQO/manifest.yaml"])
    m["version"] = version
    files["GZQO/manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode()
    with zipfile.ZipFile(out, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return out


def _part_at(head: RulesetRepo, out: Path, on: dict[str, Any]) -> Path:
    data, _o = export(head, "GZQO", on)
    out.write_bytes(data)
    return out


# ------------------------------------------------------------------------------------------- 1: a plain zip
def test_1_a_plain_zip_of_a_version_the_site_did_not_accept_never_installs(
    keys: tuple[Path, Path], tmp_path: Path, site_env: None
) -> None:
    priv, pub = keys
    box, updates = site_box(tmp_path, version="1.0.0")
    zipped = _plain("1.0.1", tmp_path / "GZQO-1.0.1.zip")
    why = _refused(_signed(priv, [zipped], tmp_path / "plain.tar", 4), pub, box, updates, tmp_path / "stage")
    assert _tags(box) == [] and "not the version this site accepted" in why


# ------------------------------------------------------------------------------- 2: a minimum release of zero
def test_2_a_part_names_the_release_that_compiled_it_and_an_older_box_refuses_it(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    priv, pub = keys
    with pytest.raises(ExportRefused, match="release_seq"):
        compiled_on(release="2026.11-1")  # no release_seq: refused, never a floor of zero
    with pytest.raises(ExportRefused, match="release_seq"):
        compiled_on({**HEAD_RELEASE, "release_seq": 0})
    with pytest.raises(ExportRefused, match="release_seq"):
        _part_at(head, tmp_path / "x.zip", {"bundle_id": "2026.11-1"})
    data = make_part(head, tmp_path / "seq.zip").read_bytes()
    files = {k.split("/", 1)[1]: v for k, v in members(data).items() if k != "ORIGIN.json"}
    no_seq = tmp_path / "noseq.zip"  # what the export of edb77053 wrote without --release_seq: a floor of zero
    no_seq.write_bytes(_reseal(data, files, {**open_part(data)[3], "compiled_on": {"bundle_id": "2026.11-1"}}))
    with pytest.raises(PartRefused, match="release_seq"):
        open_part(no_seq.read_bytes())
    with pytest.raises(SystemExit, match="release_seq"):
        ruleset_bundle.build(priv, "rs-noseq", [no_seq], tmp_path / "noseq.tar", release_seq=4)
    # a part compiled on release 3, signed around as it is with no floor, reaches a box on release 2: refused there
    box, updates = site_box(tmp_path)
    (updates / "installed.json").write_text(json.dumps({**HEAD_RELEASE, "release_seq": 2}))
    part = make_part(head, tmp_path / "GZQO.part.zip")
    why = _refused(_signed(priv, [part], tmp_path / "old.tar", 4), pub, box, updates, tmp_path / "stage")
    assert _tags(box) == [] and "release_seq 3" in why


# ------------------------------------------------------------------------------ 3: the standalone command
def test_3_the_standalone_command_never_installs_a_raw_part(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box, _updates = site_box(tmp_path)  # the site accepted GZQO v1.0.0 by version alone
    part = make_part(head, tmp_path / "GZQO.part.zip")
    imp = _cli(monkeypatch, box.repo_dir, tmp_path / "cli-audit")
    assert imp.main([str(part), "--by", "someone"]) != 0
    assert _tags(box) == []
    err = capsys.readouterr().err
    assert "not from a bundle the update verified" in err and "ja:" in err and "zh-TW:" in err
    assert imp.main([str(part), "--check"]) == 0 and _tags(box) == []  # a dry check is all it does


# ------------------------------------------------------------------------- the gate: every road, every bypass
def test_every_road_with_every_bypass(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from criteria_compiler import import_ruleset
    from criteria_compiler.import_ruleset import ImportRefused, Verified, install_outcome

    priv, pub = keys
    box, updates = site_box(tmp_path)  # accepts GZQO v1.0.0
    repo = RulesetRepo(box.repo_dir)
    part = make_part(head, tmp_path / "GZQO.part.zip")
    data = part.read_bytes()
    good = Verified.of(data, "GZQO.part.zip", bundle_id="rs1", release_seq=4, box_release_seq=3, stage=str(tmp_path))

    # (a) the in-process call with no evidence, with evidence of other bytes, with evidence of an older box
    def ev_of(b: bytes, box_release_seq: int | None) -> Verified:
        return Verified.of(b, "GZQO.part.zip", bundle_id="rs1", release_seq=4, box_release_seq=box_release_seq,
                           stage=str(tmp_path))  # fmt: skip

    for ev in (None, ev_of(b"other", 3), ev_of(data, 2), ev_of(data, None)):
        with pytest.raises(ImportRefused):
            install_outcome(repo, data, "update:rs1", verified=ev)
        assert _tags(box) == []
    # (b) the plain zip: no evidence; evidence but a version not accepted
    plain = _plain("1.0.1", tmp_path / "p.zip").read_bytes()
    for ev in (None, Verified.of(plain, "p.zip", bundle_id="rs1", release_seq=4, box_release_seq=3, stage="s")):
        with pytest.raises(ImportRefused):
            install_outcome(repo, plain, "update:rs1", verified=ev)
    assert _tags(box) == []
    # (c) the standalone command: no --verified; a forged evidence file this account wrote
    imp = _cli(monkeypatch, box.repo_dir, tmp_path / "cli-audit")
    forged = tmp_path / "verified.json"
    forged.write_text(json.dumps(good.record()))
    assert imp.main([str(part), "--by", "x"]) != 0
    if os.getuid() != 0:  # a file the compiler's service account wrote is no evidence
        assert imp.main([str(part), "--by", "x", "--verified", str(forged)]) != 0
    monkeypatch.setattr(import_ruleset, "EVIDENCE_OWNER", os.getuid())
    os.chmod(forged, 0o666)  # writable by others: no evidence
    assert imp.main([str(part), "--by", "x", "--verified", str(forged)]) != 0
    assert _tags(box) == []
    # (d) the update road: a version not accepted, then the same bundle again after its rollback (a retry)
    accept(box.repo_dir, "1.0.1")
    bundle = _signed(priv, [part], tmp_path / "rs.tar", 4, 3)
    for stage in ("stage1", "stage2"):
        _refused(bundle, pub, box, updates, tmp_path / stage)
        assert _tags(box) == []
    # the road that installs: the update path's own evidence and the site's acceptance of that version
    accept(box.repo_dir, "1.0.0")
    assert apply_bundle(bundle, pub, box, updates, tmp_path / "stage3")["ok"] and _tags(box) == ["GZQO/v1.0.0"]


# -------------------------------------------------------------------------------- 4: a criterion goes missing
def test_4_a_criterion_the_manifest_lists_is_in_the_part(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    gone = _head_with(tmp_path, lambda d: (d / "ir" / "GZQO-EXC-11.json").unlink())
    with pytest.raises(ExportRefused, match="GZQO-EXC-11"):
        export(gone, "GZQO", compiled_on(HEAD_RELEASE))
    priv, pub = keys
    box, updates = site_box(tmp_path)
    data = make_part(head, tmp_path / "GZQO.part.zip").read_bytes()
    files = {k.split("/", 1)[1]: v for k, v in members(data).items() if k != "ORIGIN.json"}
    del files["ir/GZQO-EXC-11.json"]
    cut = tmp_path / "cut.zip"
    cut.write_bytes(_reseal(data, files))
    why = _refused(_signed(priv, [cut], tmp_path / "cut.tar", 4, 3), pub, box, updates, tmp_path / "stage")
    assert _tags(box) == [] and "GZQO-EXC-11" in why


# ------------------------------------------------------------------- 5: the department restriction screens
def test_5_an_arrived_rule_set_screens_only_inside_its_accepted_restriction(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator.scenarios import screen

    priv, pub = keys
    box, updates = site_box(tmp_path, profile=False)
    prof = {"routing": SITE_PROFILE["routing"],
            "scopes": {"screen": {"practitioners": ["P1"], "departments": ["RHEU"]}}}  # fmt: skip
    from criteria_compiler.import_ruleset import put_site_profile
    from tb_common.audit import AuditLog

    put_site_profile(RulesetRepo(box.repo_dir), "GZQO", yaml.safe_dump(prof).encode(), "op", version="1.0.0",
                     audit=AuditLog(tmp_path / "pa"))  # fmt: skip
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(priv, "rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert apply_bundle(tmp_path / "rs.tar", pub, box, updates, tmp_path / "stage")["ok"]
    rs = load_approved(box.repo_dir, "GZQO")
    rows = [{"pid": "A", "next_appt": None, "practitioner_id": "P1", "dept": "RHEU"},
            {"pid": "B", "next_appt": None, "practitioner_id": "P1", "dept": "META"},
            {"pid": "C", "next_appt": None, "practitioner_id": "P2", "dept": "RHEU"}]  # fmt: skip

    def query(_sql: str, params: list[Any], snapshot: str | None = None) -> Any:
        whole, pract = params[4], params[0]
        return SimpleNamespace(to_pylist=lambda: [r for r in rows if whole or r["practitioner_id"] in pract])

    def ctx(options: dict[str, str]) -> Any:
        return SimpleNamespace(job=SimpleNamespace(options=options), rulesets_dir=box.repo_dir,
                               services=SimpleNamespace(lake=SimpleNamespace(query=query)),
                               cfg=SimpleNamespace(env=SimpleNamespace(tz="UTC")))  # fmt: skip

    monkeypatch.setattr(screen, "drop_opted_out", lambda _c, s: s)
    monkeypatch.setattr(screen, "study_scope", lambda _c, _r: None)
    from datetime import date

    def pids(options: dict[str, str]) -> list[str]:
        return [s.pid for s in screen.screen_scope_read(ctx(options), rs, date(2026, 11, 20), "s")[0]]

    assert pids({}) == ["A"]
    assert pids({"scope": "hospital"}) == ["A"]  # the job's options never widen an arrived rule set's scope
    assert pids({"pract": "P1,P2"}) == ["A"]
    monkeypatch.setattr(screen, "study_scope", lambda _c, _r: {"mode": "hospital"})
    assert pids({}) == ["A"]  # nor does the study's set-up page
    with pytest.raises(screen.StepFailed):
        pids({"dept": "META"})


# ----------------------------------------------------------------------- 6: a repeat takes the site's routing
def test_6_a_repeat_applies_the_sites_current_routing(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    priv, pub = keys
    box, updates = site_box(tmp_path)
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(priv, "rs1", [part], tmp_path / "rs1.tar", release_seq=4)
    assert apply_bundle(tmp_path / "rs1.tar", pub, box, updates, tmp_path / "s1")["ok"]
    from criteria_compiler.import_ruleset import put_site_profile
    from tb_common.audit import AuditLog

    new = {**SITE_PROFILE, "routing": {"list_to": ["corrected@site.test"]}}
    put_site_profile(RulesetRepo(box.repo_dir), "GZQO", yaml.safe_dump(new).encode(), "op", version="1.0.0",
                     audit=AuditLog(tmp_path / "pa"))  # fmt: skip
    ruleset_bundle.build(priv, "rs2", [part], tmp_path / "rs2.tar", release_seq=5)
    assert apply_bundle(tmp_path / "rs2.tar", pub, box, updates, tmp_path / "s2")["ok"]
    rs = load_approved(box.repo_dir, "GZQO")
    assert rs.manifest.routing.list_to == ["corrected@site.test"]  # type: ignore[union-attr]


# ------------------------------------------------------------------------------ 7: value-set scalar fields
@pytest.mark.parametrize("field,value", [("title", {"mrn": "TEST-42", "diagnosis": "gout"}), ("version", ["x"]),
                                         ("status", {"a": 1}), ("url", None)])  # fmt: skip
def test_7_a_value_set_scalar_is_a_string(field: str, value: Any) -> None:
    vs = {"resourceType": "ValueSet", "name": "VS_X", "title": "t", "url": "u", "version": "1", "status": "active",
          "compose": {"include": [{"system": "s", "concept": [{"code": "1", "display": "d"}]}]}}  # fmt: skip
    check_valueset(json.dumps(vs).encode(), "valuesets/VS_X.json")
    with pytest.raises(PartRefused, match=field):
        check_valueset(json.dumps({**vs, field: value}).encode(), "valuesets/VS_X.json")
    nested = {**vs, "compose": {"include": [{"system": {"mrn": "TEST-42"}, "concept": []}]}}
    with pytest.raises(PartRefused, match="system"):
        check_valueset(json.dumps(nested).encode(), "valuesets/VS_X.json")
    deep = {**vs, "compose": {"include": [{"system": "s", "concept": [{"code": "1", "display": {"m": "1"}}]}]}}
    with pytest.raises(PartRefused, match="display"):
        check_valueset(json.dumps(deep).encode(), "valuesets/VS_X.json")


# --------------------------------------------------------------------------- 8: a byte outside the members
@pytest.mark.parametrize("how", ["archive comment", "member comment", "appended", "prepended", "extra field"])
def test_8_a_part_holds_no_byte_outside_its_members(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path, how: str
) -> None:
    data = make_part(head, tmp_path / "GZQO.part.zip").read_bytes()
    if how == "archive comment":
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf, "a") as z:
            z.comment = b"MRN TEST-42"
        bad = buf.getvalue()
    elif how in ("member comment", "extra field"):
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                if how == "member comment":
                    info.comment = b"MRN TEST-42"
                else:
                    info.extra = b"\xfe\xca\x0b\x00MRN TEST-42"
                dst.writestr(info, src.read(info.filename))
        bad = buf.getvalue()
    elif how == "appended":
        bad = data + b"MRN TEST-42"
    else:
        bad = b"MRN TEST-42" + data
    with pytest.raises(PartRefused):
        open_part(bad)
    (tmp_path / "bad.zip").write_bytes(bad)
    with pytest.raises(SystemExit):
        ruleset_bundle.build(keys[0], "rs-bad", [tmp_path / "bad.zip"], tmp_path / "bad.tar", release_seq=4)
