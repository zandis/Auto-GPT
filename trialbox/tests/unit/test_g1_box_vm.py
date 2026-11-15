"""The box run's helper on the VM (deploy/gcp/box_vm.py): the bundle check as PRODUCTION reads it, the wizard's TOTP,
doctor's verdict, the memory of a stage, the G-9 comparison, G-6's top costs and the identity record."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("box_vm", ROOT / "deploy" / "gcp" / "box_vm.py")
assert _spec and _spec.loader
vm = importlib.util.module_from_spec(_spec)
sys.modules["box_vm"] = vm
_spec.loader.exec_module(vm)

COMMIT = "a" * 40
IMAGES = {"standin": {"image": "trialbox-standin:0", "digest": "sha256:" + "0" * 64}}

pytestmark = pytest.mark.nodb


def _bundle(tmp: Path, release: dict[str, Any] | None, host: bool = True) -> Path:
    from tools import sign_bundle

    key, _pub = sign_bundle.keygen(tmp / "keys")
    items = []
    if host:
        ht = tmp / "host.tar"
        with tarfile.open(ht, "w") as t:
            data = b"services: {}\n"
            info = tarfile.TarInfo("deploy/docker-compose.yml")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        items.append(("host", ht, "trialbox-host.tar"))
    rules = tmp / "rules.json"
    rules.write_text('{"synthetic": true}\n')
    items.append(("other", rules, "rulesets/rules.json"))
    out = tmp / "b.tar"
    sign_bundle.build(
        key,
        "2026.11-t",
        items,
        out,
        release_seq=3,
        release=release,
        images_lock={"format": "trialbox-images-lock/1", "images": IMAGES} if release else None,
    )
    return out


def _release(**over: Any) -> dict[str, Any]:
    return {"version": "2026.11-t", "source": {"commit": COMMIT, "dirty": False, "tag": None}, "images": IMAGES, **over}


def test_a_signed_bundle_of_the_real_format_passes_and_names_its_signature(tmp_path: Path) -> None:
    b = _bundle(tmp_path, _release())
    res = vm.bundle_check(
        b, production=True, commit=COMMIT, release_out=tmp_path / "r.json", host_out=tmp_path / "h.tar"
    )
    assert res["refused"] == [] and res["manifest_files"] == 2 and res["host_payload"] == "trialbox-host.tar"
    assert res["key_id"] and len(res["signature_sha256"]) == 64 and res["bundle_id"] == "2026.11-t"
    assert json.loads((tmp_path / "r.json").read_text())["source"]["commit"] == COMMIT
    with tarfile.open(tmp_path / "h.tar") as t:
        assert t.getnames() == ["deploy/docker-compose.yml"]


def test_production_refuses_a_rehearsal_a_dirty_and_another_commit(tmp_path: Path) -> None:
    for name, rel, commit, word in [
        ("rh", _release(rehearsal=True), COMMIT, "rehearsal bundle"),
        ("dirty", _release(source={"commit": COMMIT, "dirty": True}), COMMIT, "source.dirty"),
        ("other", _release(), "b" * 40, "the run declared"),
    ]:
        d = tmp_path / name
        d.mkdir()
        res = vm.bundle_check(_bundle(d, rel), production=True, commit=commit)
        assert any(word in r for r in res["refused"]), (name, res["refused"])
    assert vm.production_refusals(None) and "no release record" in vm.production_refusals(None)[0]


def test_a_changed_payload_and_an_extra_file_are_refused(tmp_path: Path) -> None:
    b = _bundle(tmp_path, _release())
    bad = tmp_path / "bad.tar"
    with tarfile.open(b) as src, tarfile.open(bad, "w") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()  # type: ignore[union-attr]
            if m.name == "files/rulesets/rules.json":
                data = data.replace(b"true", b"TRUE")
            dst.addfile(m, io.BytesIO(data))
        extra = tarfile.TarInfo("files/planted.sh")
        extra.size = 3
        dst.addfile(extra, io.BytesIO(b"x\n\n"))
    res = vm.bundle_check(bad)
    assert any("rulesets/rules.json: sha256" in r for r in res["refused"])
    assert any("planted.sh: in the bundle, not in its manifest" in r for r in res["refused"])


def test_a_start_needs_a_host_tree_in_the_bundle(tmp_path: Path) -> None:
    res = vm.bundle_check(_bundle(tmp_path, _release(), host=False), host_out=tmp_path / "h.tar")
    assert any("no host tree" in r for r in res["refused"])


def test_the_wizards_code_is_the_consoles_totp() -> None:
    from console import totp as console_totp

    secret = console_totp.new_secret()
    now = time.time()
    assert vm.totp(secret, now) == console_totp.totp(secret, now)
    assert console_totp.verify(secret, vm.totp(secret, now), now, None) is not None


def test_the_screen_text_gives_the_address_and_the_code(tmp_path: Path) -> None:
    issue = tmp_path / "trialbox-firstrun.issue"
    issue.write_text("\n  TrialBox set-up:  https://box1.local/login/first-run\n  One-time code:    abcd-efgh\n\n")
    assert vm.read_screen(issue) == ("https://box1.local", "abcd-efgh")
    issue.write_text("nothing yet")
    with pytest.raises(ValueError):
        vm.read_screen(issue)


def test_doctors_verdict_allows_only_the_expected_fails_and_no_rehearsal_mark() -> None:
    checks = [
        {"name": "serving", "status": "PASS", "detail": "ok"},
        {"name": "backup", "status": "FAIL", "detail": "x"},
    ]
    assert vm.doctor_verdict(checks, ["backup"])["pass"] is True
    assert vm.doctor_verdict(checks, [])["unexpected_fails"] == ["backup"]
    marked = [*checks, {"name": "env", "status": "WARN", "detail": "rehearsal box (D-726)"}]
    assert vm.doctor_verdict(marked, ["backup"])["pass"] is False
    assert vm.doctor_verdict([], [])["pass"] is False  # no checks: no verdict


def test_a_stage_memory_from_samples_and_the_cgroup_peak(tmp_path: Path) -> None:
    d = tmp_path / "system.slice" / "docker-cid1.scope"
    d.mkdir(parents=True)
    for f, v in (("memory.current", 10), ("memory.peak", 100), ("memory.max", 6 << 30)):
        (d / f).write_text(f"{v}\n")
    (d / "memory.events").write_text("oom 0\noom_kill 0\n")
    stop, out = tmp_path / "stop", tmp_path / "s.jsonl"
    import threading

    t = threading.Thread(target=vm.sample, args=(["adapter"], {"adapter": "cid1"}, out, stop, 0.05, tmp_path))
    t.start()
    time.sleep(0.15)
    (d / "memory.current").write_text("5000\n")
    (d / "memory.peak").write_text("7000\n")
    (d / "memory.events").write_text("oom 1\noom_kill 1\n")
    time.sleep(0.15)
    stop.touch()
    t.join(5)
    m = vm.stage_memory(out.read_text().splitlines())["containers"]["adapter"]
    assert (
        m["peak_bytes"] == 7000
        and m["sampled_peak_bytes"] == 5000
        and m["oom_kills"] == 1
        and m["cap_bytes"] == 6 << 30
    )


def test_the_g9_comparison_names_what_differs() -> None:
    a = {"rows": [{"pid": "p1", "tier": "A"}, {"pid": "p2", "tier": "B"}]}
    assert vm.compare_lists(a, a)["equal"] is True
    b = {"rows": [{"pid": "p1", "tier": "B"}, {"pid": "p3", "tier": "A"}]}
    c = vm.compare_lists(a, b)
    assert c == {
        **c,
        "equal": False,
        "only_in_a": ["p2"],
        "only_in_b": ["p3"],
        "tier_differs": ["p1"],
        "differences": 3,
    }


def test_g6s_top_costs(tmp_path: Path) -> None:
    for i, (step, s, peak) in enumerate(
        [("ingest", 900, 7 << 30), ("rebuild", 800, 3 << 30), ("screen", 9000, 2 << 30), ("backup", 300, 1 << 30)]
    ):
        (tmp_path / f"2{i}-g6-{step}.json").write_text(
            json.dumps(
                {
                    "step": f"2{i}-g6-{step}",
                    "seconds": s,
                    "detail": {"memory": {"containers": {"svc": {"peak_bytes": peak}}}},
                }
            )
        )
    top = vm.top_costs(tmp_path)
    assert [x["step"] for x in top["by_seconds"]] == ["22-g6-screen", "20-g6-ingest", "21-g6-rebuild"]
    assert top["by_peak_memory"][0]["step"] == "20-g6-ingest"


def test_the_identity_record_against_the_real_pins() -> None:
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text())
    import yaml

    reg = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text())
    judge = next(b for b in reg["builds"] if b["build_id"] == "gemma-4-26b-a4b-it-rtxpro6000")
    box = {
        "builds": [
            {
                "build_id": judge["build_id"],
                "chat_template_sha256": judge["chat_template"]["sha256"],
                "manifest_sha256": judge["expected"]["manifest_sha256"],
            }
        ],
        "served_prompts": [{"id": "judge", "version": 4}],
    }
    digest = lock["third_party"]["vllm"]["digest"]
    imgs = {"llm-service": {"ref": "vllm/vllm-openai:v0.32.0", "repo_digests": [f"vllm/vllm-openai@{digest}"]}}
    ok = vm.identity(box, lock, judge["chat_template"]["sha256"], imgs, 0)
    assert ok["pass"] is True and ok["served_prompts"] == [{"id": "judge", "version": 4}]
    bad = vm.identity(box, lock, "f" * 64, {"x": {"repo_digests": ["r@sha256:" + "1" * 64]}}, 1)
    assert bad["pass"] is False and not any(
        bad["checks"][k] for k in ("chat_template_served_is_pinned", "images_in_images_lock", "weights_match_pins")
    )


def test_cmd_arg_reads_the_judges_template_flag() -> None:
    cmd = ["--model", "/m", "--chat-template", "/t.jinja"]
    assert vm.cmd_arg(cmd, "--chat-template") == "/t.jinja"
    assert vm.cmd_arg(["--chat-template=/u"], "--chat-template") == "/u" and vm.cmd_arg([], "--x") == ""


def test_g1s_token_half_three_verdicts_and_what_did_not_run() -> None:
    ids = [[1, 2, 3], [4, 5]]
    hf = {"ids": ids, "ids_passed": ids, "folder_template_sha256": "a", "passed_template_sha256": "a"}
    same = vm.g1_tokens({"ids": ids, "url": "u", "keyed": True}, hf)
    assert same["pass"] is True and same["verdicts"] == {
        "server_vs_folder_token_ids": True,
        "passed_vs_folder_token_ids": True,
        "passed_vs_folder_text_sha256": True,
    }
    diff = vm.g1_tokens({"ids": [[1, 2, 9], None], "errors": ["401"]}, {**hf, "passed_template_sha256": "b"})
    assert diff["pass"] is False and diff["verdicts"]["server_vs_folder_token_ids"] is False
    assert diff["server_different"][0] == {"prompt": 0, "first_difference_at": 2, "lengths": [3, 3]}
    assert (
        diff["verdicts"]["passed_vs_folder_text_sha256"] is False and "1 of 2 prompts unanswered" in diff["not_run"][0]
    )
    none = vm.g1_tokens({}, {})
    assert (
        none["pass"] is False and none["verdicts"]["server_vs_folder_token_ids"] is None and len(none["not_run"]) == 2
    )


def test_qualifys_verdict_per_step() -> None:
    rec = {"status": "failed", "failed_steps": ["n12"], "qualifies_production": False,
           "steps": {"pin": {"status": "passed", "reason": "ok"}, "n12": {"status": "failed", "reason": "no evidence"}}}  # fmt: skip
    v = vm.qualify_verdict(rec)
    assert v["status"] == "failed" and v["failed_steps"] == ["n12"]
    assert v["steps"]["n12"] == {"status": "failed", "reason": "no evidence"}
