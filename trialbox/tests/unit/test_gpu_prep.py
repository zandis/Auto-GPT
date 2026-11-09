"""The next cloud GPU runs (D-148): the parallel complete run, the embedding comparison and the profile cost stand-in.

Everything here runs on a CPU with tiny stubs: the shard plan and its estimate, the benches on a small synthetic
hospital (a hashing encoder for the embeddings, a stub judge for the profiles), the gateway fallback, and the driver's
dry run for several VMs (no gcloud call is made)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tools import bench_embed as be
from tools import bench_profile as bp
from tools import complete_run as cr

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"


@pytest.fixture(scope="module")
def synth(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tools import feas_demo as fd
    from tools.synth_hospital import run

    out = tmp_path_factory.mktemp("bench") / "synth"
    run(out, profile="ci", sites="jp-a:JP:120,tw-a:TW:120", ref_date=fd.REF)
    return out


# ------------------------------------------------------------------------------------------------ the shard plan
def _g1_tags() -> set[str]:
    e = cr.estimate(50000)
    return {t for r in e["rows"] for t in r["tags"]}


@pytest.mark.parametrize("vms", [1, 2, 3, 4])
def test_every_part_runs_on_exactly_one_vm(vms: int) -> None:
    e = cr.estimate(50000, parts=("g1", "embed", "profile"))
    p = cr.shard_plan(e, vms)
    assert p["vms"] == vms
    tags = [t for s in p["shards"] for t in s["tags"] if t not in ("prepare", "install")]
    assert sorted(tags) == sorted(_g1_tags() | {"embed", "profile"})  # each once, none lost
    assert [s for s in p["shards"] if "install" in s["tags"]] == [p["shards"][0]]
    for s in p["shards"]:  # the shared hospital is made wherever a hospital part runs, before it
        hosp = [t for t in s["tags"] if t.startswith("hospital-")]
        assert ("prepare" in s["tags"]) == bool(hosp)
        if hosp:
            assert s["tags"].index("prepare") < s["tags"].index(hosp[0])
        assert s["cap_hours"] >= s["hours"] * 1.3 and s["cap_hours"] == int(s["cap_hours"])
    fixed = cr.BOOT_HOURS + cr.SETUP_HOURS  # every VM pays its own start and setup
    assert abs(p["hours"] - (e["hours"] + (vms - 1) * fixed)) < 0.05
    assert abs(p["usd"] - p["hours"] * cr.PRICE_PER_HOUR) < 0.05


def test_four_vms_finish_the_50000_run_in_about_three_hours() -> None:
    one = cr.shard_plan(cr.estimate(50000), 1)
    four = cr.shard_plan(cr.estimate(50000), 4)
    assert one["wall_hours"] > 8 and four["wall_hours"] <= 3.0
    assert {s["shard"] for s in four["shards"] if any(t.startswith("hospital-") for t in s["tags"])} == {1, 2}
    text = cr.print_shards(cr.estimate(50000), four)
    assert "wall about" in text and "VM-hours" in text


def test_bench_parts_only_when_asked() -> None:
    e = cr.estimate(50000, parts=("embed",))
    assert [r["tags"] for r in e["rows"] if r["tags"]] == [["embed"]]
    assert cr.shard_plan(e, 4)["vms"] == 1  # nothing to split
    a = argparse.Namespace(langs=["ja"], skip=[], only=[], scenarios=[])
    assert not {p for p, _, _ in cr.plan(a)} & set(cr.BENCH_PARTS)
    a.only = ["embed", "profile"]
    assert cr.plan(a) == [("embed", "", ""), ("profile", "", "")]


def test_estimate_cli_prints_the_vms(capsys: pytest.CaptureFixture[str]) -> None:
    assert cr.main(["--estimate", "--patients", "50000", "--vms", "3", "--parts", "g1,embed"]) == 0
    out = capsys.readouterr().out
    assert "Split over 3 VM(s)" in out and "embed" in out
    assert cr.main(["--estimate", "--json", "--vms", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["plan"]["vms"] == 2


# ------------------------------------------------------------------------------------------------ the embedding bench
def test_the_labelled_set_is_bilingual_and_points_at_real_notes(synth: Path) -> None:
    s = be.build_set(synth)
    ids = {d["id"] for d in s["docs"]}
    assert {d["lang"] for d in s["docs"]} == {"ja", "zh-TW"}
    assert all(q["relevant"] and set(q["relevant"]) <= ids for q in s["queries"])
    assert {q["kind"] for q in s["queries"]} == {"needle", "finding"}
    assert min(s["counts"]["queries"].values()) >= 10
    by_id = {d["id"]: d for d in s["docs"]}
    for q in s["queries"]:  # queries are paraphrases, never the note's own sentence; relevant notes are in its language
        assert all(by_id[r]["lang"] == q["lang"] for r in q["relevant"])
        assert not any(q["text"] in by_id[r]["text"] for r in q["relevant"]) or q["kind"] == "needle"


def test_retrieval_metrics_on_known_vectors() -> None:
    docs = np.eye(4, dtype=np.float32)
    qs = [
        {"kind": "needle", "lang": "ja", "relevant": ["d1"]},
        {"kind": "finding", "lang": "zh-TW", "relevant": ["d2", "d3"]},
    ]
    q = np.array([[0, 1, 0, 0], [0, 0, 1, 0.9]], dtype=np.float32)
    r = be.retrieval(["d0", "d1", "d2", "d3"], docs, qs, q, k=2)
    assert r["needle/ja"]["mrr@2"] == 1.0 and r["needle/ja"]["recall@2"] == 1.0
    assert r["finding/zh-TW"]["ndcg@2"] == 1.0 and r["finding/zh-TW"]["p@2"] == 1.0


def test_the_bench_runs_on_the_hash_stub(synth: Path, tmp_path: Path) -> None:
    s = be.build_set(synth)
    (tmp_path / "set.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert (
        be.main(["run", "--set", str(tmp_path / "set.json"), "--out", str(tmp_path / "r.json"), "--backend=hash"]) == 0
    )
    res = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    m = res["models"][0]
    assert m["dims"] == be.DIMS == 1024 and m["throughput"]["docs"] == s["counts"]["docs_total"]
    assert m["throughput"]["docs_per_s"] > 0 and m["throughput"]["tokens_per_s"] > 0
    assert m["storage"]["halfvec_bytes"] == 2 * 1024 + 8 and m["storage"]["vector_fp32_bytes"] == 4 * 1024 + 8
    assert set(m["retrieval"]) == {"needle/ja", "needle/zh-TW", "finding/ja", "finding/zh-TW"}
    assert "hash-stub" in be.markdown(res) and be.summary(res)["models"]["hash-stub"]["halfvec_bytes"] == 2056


def test_a_model_that_does_not_load_is_a_row_not_a_crash() -> None:
    def broken() -> Any:
        raise OSError("no weights")

    broken.name = "broken"  # type: ignore[attr-defined]
    res = be.run({"docs": [], "queries": [], "counts": {}, "source": "x"}, [broken])
    assert res["models"][0]["name"] == "broken" and "no weights" in res["models"][0]["error"]


# ------------------------------------------------------------------------------------------------ the profile bench
def test_facts_carry_no_identity(synth: Path) -> None:
    pats = bp.load_patients(synth)
    assert pats and {p["lang"] for p in pats} == {"ja", "zh-TW"}
    import csv

    with (synth / "jp-a" / "patient.csv").open(encoding="utf-8") as fh:
        people = list(csv.DictReader(fh))
    text = json.dumps([p["facts"] for p in pats], ensure_ascii=False)
    for person in people[:50]:
        assert person["phone"] not in text and person["id_no"] not in text
    assert all(f["id"] == f"F{i + 1}" for p in pats for i, f in enumerate(p["facts"]))


def test_the_stub_profile_run_measures_and_extrapolates(synth: Path) -> None:
    res = bp.run(synth, bp.Caller(stub=True), patients=40, workers=4, nightly=50000)
    m, x = res["measured"], res["extrapolation"]
    assert m["answered"] == m["patients"] == 40 and m["citations_valid"] == 1.0
    assert m["by_lang"] == {"ja": 20, "zh-TW": 20} and m["batch"]["patients"] == 40 - bp.SEQUENTIAL
    assert m["tokens_in"]["mean"] > m["tokens_out"]["mean"] > 0
    eff = m["batch"]["seconds_per_patient"]
    assert abs(x["nightly_all"]["gpu_hours"] - 50000 * eff / 3600) < 0.01
    assert x["nightly_note_stage"]["patients"] == round(50000 * bp.S3_SHARE)
    assert 0 < x["nightly_study_archetypes"]["share"] < 1
    assert set(bp.summary(res)) == {"path", "gateway_refused", "measured", "extrapolation", "errors"}


def test_citations_must_be_the_patients_own_facts() -> None:
    p = {"facts": [{"id": "F1", "text": "a"}, {"id": "F2", "text": "b"}]}
    data = {"sentences": [{"text": "x", "cites": ["F1"]}, {"text": "y", "cites": ["F9"]}, {"text": "z", "cites": []}]}
    assert bp.check_citations(p, data) == (3, 1)


def test_a_refusing_gateway_falls_back_to_the_judge_and_says_so() -> None:
    from tb_llm import GatewayRefused

    class Refuses:
        def complete(self, body: dict[str, Any], labels: Any) -> dict[str, Any]:
            assert labels.role == "abstract_field" and labels.data_class == "D3" and "model" not in body
            raise GatewayRefused("no_route", 403, "no route")

    direct_calls: list[Any] = []

    def direct(msgs: list[dict[str, str]]) -> dict[str, Any]:
        direct_calls.append(msgs)
        return bp.stub_call(msgs)

    c = bp.Caller(gateway=Refuses, direct=direct)
    p = {"pid": "x", "lang": "ja", "language": "Japanese", "facts": [{"id": "F1", "text": "sex F, age 50"}]}
    row = bp._one(c, p)
    assert row["ok"] and direct_calls and c.path.startswith("direct (the gateway refused") and "no_route" in c.refused


def test_the_profile_goes_through_the_installed_box_gateway(tmp_path: Path) -> None:

    from tools import scenarios

    up = FastAPI()
    seen: list[str] = []

    @up.post("/v1/chat/completions")
    async def cc(request: Request) -> dict[str, Any]:
        seen.append(str(request.url))
        b = await request.json()
        return bp.stub_call(b["messages"]) | {"model": b["model"]}  # vLLM answers with the served name

    saved = os.environ.pop("TB_DATA_CLASS", None)
    try:
        env = scenarios.installed_env(tmp_path / "audit", "http://judge/v1", "http://verifier/v1")
        c = bp.Caller(gateway=lambda: scenarios.gateway_client(env, TestClient(up)), direct=None)
        row = bp._one(c, {"pid": "x", "lang": "ja", "language": "Japanese", "facts": [{"id": "F1", "text": "a"}]})
    finally:
        if saved is not None:
            os.environ["TB_DATA_CLASS"] = saved
    assert row["ok"], (row.get("error"), c.refused)
    assert c.path == "gateway (installed box)" and seen == ["http://judge/v1/chat/completions"]


# ------------------------------------------------------------------------------------------------ the driver
def _dry(tmp_path: Path, *args: str) -> str:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))
    env.pop("TB_ZONES", None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", *args], cwd=ROOT, env=env, capture_output=True,
                       text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout


def test_each_vm_is_capped_before_it_starts_and_runs_only_its_parts(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "50000", "--vms", "3", "--zones", "z-a-1,z-b-1,z-c-1", "--parts", "g1,embed")
    plan = json.loads((tmp_path / "out" / "plan.json").read_text(encoding="utf-8"))["plan"]
    assert out.index("auth print-access-token") < out.index("set-scheduling")
    for s, (vm, zone) in zip(plan["shards"], [("tb-gpu-sim", "z-a-1"), ("tb-gpu-sim-2", "z-b-1"),
                                              ("tb-gpu-sim-3", "z-c-1")], strict=True):  # fmt: skip
        assert (s["vm"], s["zone"]) == (vm, zone)
        cap = out.index(f"set-scheduling {vm} --zone {zone} --max-run-duration={s['cap_hours']}h "
                        "--instance-termination-action=STOP")  # fmt: skip
        assert cap < out.index(f"instances start {vm} --zone {zone}")
        assert f"tb-only={' '.join(s['tags'])}," in out
    assert "instances create" not in out and "machine-images" not in out  # a run never makes VMs
    assert "regions describe z-b" in out and "accelerator-types list" in out  # the owner's read-only quota check
    assert "--report-only" in out and "--only walk backup update scale" in out


def test_one_vm_is_the_d141_run(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "50000")
    assert "set-scheduling tb-gpu-sim --zone asia-east1-a --max-run-duration=12h" in out
    assert "[vm" not in out and "tb-gpu-sim-2" not in out


def test_too_few_zones_is_refused(tmp_path: Path) -> None:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--vms", "3", "--zones", "a-b-1,c-d-1"], cwd=ROOT,
                       env=env, capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    assert r.returncode == 2 and "3 zones needed" in r.stderr


def test_provision_clones_power_off_at_once_and_are_capped(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--provision", "--vms", "2", "--zones", "z-a-1,z-b-1")
    assert "machine-images create tb-gpu-sim-img --source-instance=tb-gpu-sim --source-instance-zone=z-a-1" in out
    create = next(ln for ln in out.splitlines() if "instances create tb-gpu-sim-2" in ln)
    assert "--zone z-b-1" in create and "--max-run-duration=30m" in create and "--provisioning-model=SPOT" in create
    assert "startup-script=" in create and "instances start" not in out
    assert "poweroff" in (tmp_path / "out" / "poweroff.sh").read_text(encoding="utf-8")


def test_the_vm_runs_its_shard_and_the_embed_bench_in_the_vllm_image() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert "ONLY=$(md tb-only" in vm and "${ONLY:+--only $ONLY}" in vm
    assert "TB_BENCH_EMBED_CMD=/usr/local/sbin/tb-embed-py" in vm and "--entrypoint python3 $VLLM" in vm
    assert "bench-embed/result.json" in vm and "bench-profile/result.json" in vm
    assert vm.index("tb-watchdog") < vm.index("ONLY=$(md tb-only")
