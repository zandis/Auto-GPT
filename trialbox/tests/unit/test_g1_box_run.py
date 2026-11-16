"""The box run's driver helper (tools/box_run.py): the estimate's sources, the metadata, the results reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import box_run
from tools.complete_run import HOSPITAL_MEASURED, PRICE_PER_HOUR

pytestmark = pytest.mark.nodb


def test_the_estimate_names_a_source_for_every_figure_and_prices_the_caps() -> None:
    e = box_run.estimate(["build", "start", "g6", "g9", "g10"])
    assert [x["groups"] for x in e["launches"]] == [["build"], ["start", "g6", "g9", "g10"]]
    for x in e["launches"]:
        for r in x["rows"]:
            assert r["kind"] in ("measured", "constant", "plan", "unknown")
            assert (r["seconds"] is None) == (r["kind"] == "unknown"), r
            assert r["kind"] == "unknown" or r["source"].strip(" -")
        assert x["usd_cap_spot"] == round(x["cap_hours"] * PRICE_PER_HOUR, 2)
    assert e["launches"][0]["cap_hours"] == 2 and e["launches"][1]["cap_hours"] == 15
    # with G-6 in the launch G-9 reuses its screen as the baseline: one screen fewer
    alone = box_run.estimate(["start", "g9"])["launches"][0]["rows"]
    assert sum("baseline" in r["step"] for r in alone) == 1
    with pytest.raises(ValueError):
        box_run.estimate(["g7"])


def test_the_screen_figure_is_the_measured_50k_row() -> None:
    r = next(x for x in HOSPITAL_MEASURED if x["patients"] == 50000 and x["n"] == 16)
    assert round(r["screen_calls"] / r["screen_cps"], 1) == box_run.SCREEN_50K_S


def test_metadata_needs_its_inputs_and_refuses_a_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tb-bundle-sha256"):
        box_run.metadata(["start"], {"tb-bundle": "gs://b/x.tar"}, tmp_path / "a")
    vals = {
        "tb-src": "gs://b/s",
        "tb-commit": "c",
        "tb-release-id": "r",
        "tb-release-seq": "3",
        "tb-vendor-key-version": "1",
        "tb-vendor-pub": "gs://b/p",
        "tb-out": "gs://b/o",
    }
    names = box_run.metadata(["build"], vals, tmp_path / "b")
    assert (tmp_path / "b" / "tb-vendor-key-secret").read_text() == "tb-vendor-signing-key"
    assert (tmp_path / "b" / "tb-max-minutes").read_text() == str(2 * 60 - 5) and "tb-steps" in names
    with pytest.raises(ValueError, match="a key in the metadata"):
        box_run.metadata(["build"], {**vals, "tb-out": "-----BEGIN PRIVATE " + "KEY-----"}, tmp_path / "c")


def test_the_settings_are_declared_with_their_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.config import DECLARED

    for k in ("TB_VENDOR_KEY_SM_NAME", "TB_BUNDLE_SIGNER_SA", "TB_PROVISIONING"):
        monkeypatch.delenv(k, raising=False)
    s = box_run.settings()
    assert s == {
        "KEY_SECRET": DECLARED["TB_VENDOR_KEY_SM_NAME"].default,
        "SIGNER_SA": DECLARED["TB_BUNDLE_SIGNER_SA"].default,
        "PROVISIONING": "SPOT",
    }
    monkeypatch.setenv("TB_PROVISIONING", "cheap")
    with pytest.raises(ValueError):
        box_run.settings()


def _part(d: Path, step: str, status: str = "done", **detail: object) -> None:
    p = {"step": step, "status": status, "ok": status == "done", "seconds": 1.0, "minutes": 0.02, "detail": detail}
    if "pass_" in detail:
        p["pass"] = detail.pop("pass_")
    if status == "stop":
        p["stop"] = {"reason": "the full qualification: exit 1", "log_tail": []}
    (d / "parts" / f"{step}.json").write_text(json.dumps(p))


def test_the_results_name_what_ran_and_judge_each_test(tmp_path: Path) -> None:
    (tmp_path / "parts").mkdir()
    (tmp_path / "records").mkdir()
    (tmp_path / "state.json").write_text(json.dumps({"ended": "TB-STOP 08-qualify: the full qualification: exit 1"}))
    _part(
        tmp_path,
        "01-bundle",
        refused=[],
        bundle_id="2026.11-1",
        release_seq=3,
        key_id="k1",
        signature_sha256="s" * 64,
        release={"commit": "c" * 40, "dirty": False, "rehearsal": False},
    )
    _part(tmp_path, "03-wizard", wizard="done")
    _part(tmp_path, "06-g1", pass_=True)
    _part(tmp_path, "07-canary", pass_=True)
    _part(tmp_path, "08-qualify", status="stop")
    (tmp_path / "records" / "identity.json").write_text(
        json.dumps(
            {
                "pass": True,
                "checks": {},
                "chat_template": {"served_sha256": "t" * 64},
                "images": {"llm-service": {"digests": ["sha256:" + "d" * 64]}},
                "weights": {"expected": [{"build_id": "j", "manifest_sha256": "m" * 64}]},
                "served_prompts": [{"id": "judge", "version": 5}],
            }
        )
    )
    r = box_run.results(tmp_path)
    p = r["provenance"]
    assert p["commit"] == "c" * 40 and p["bundle_id"] == "2026.11-1" and p["signature_sha256"] == "s" * 64
    assert p["chat_template_sha256"] == "t" * 64 and p["served_prompts"] == [{"id": "judge", "version": 5}]
    assert p["image_digests"] == {"llm-service": ["sha256:" + "d" * 64]} and p["weight_manifests"]
    g2 = {c["check"]: c["pass"] for c in r["tests"]["G-2 production start"]}
    assert g2["no stop in steps 01 to 12 (no shell beyond the installer)"] is False
    assert g2["the wizard answered through the console's page"] is True and g2["qualification record passed"] is False
    assert "PASS" in box_run.render_results(r) and "FAIL" in box_run.render_results(r)
