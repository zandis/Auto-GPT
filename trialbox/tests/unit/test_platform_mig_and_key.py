"""T-113b (D-409; LLM-011, LLM-027, LLM-028, OPS-067): the shared-quota profile on two MIG instances, its pins, and
the model key on the platform.

Acceptance: with one slice ``doctor --platform`` fails with a clear reason; with two it passes. There is no kind
cluster or GPU here, so the cluster is a stand-in: the rendered overlay, a Node that advertises one or two MIG
instances the way the device plugin and GPU feature discovery label it, and the pods' scheduling state; the model
guard is the real ``services/model_guard`` on a local port. The run on kind (``deploy/platform/kind-check.sh`` with
``SLICES=1`` and ``SLICES=2``) is the same check against a real API server.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.model_pins import release_registry
from tests.unit.test_platform_manifests import ENOUGH, _cluster, _inputs, build
from tools import pin_model
from tools import serving_config as sc
from tools.trialbox import platform as pf
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "deploy" / "platform"
MIG = "3g.90gb"
SQ = {"TB_GPU_PROFILE": "shared-quota", "TB_MIG_PROFILE": MIG}


def node(slices: int, **labels: str) -> dict[str, Any]:
    """A GPU node as the NVIDIA device plugin (MIG strategy single) and GPU feature discovery show it."""
    lab = {
        "nvidia.com/mig.strategy": "single",
        "nvidia.com/gpu.product": f"NVIDIA-B200-MIG-{MIG}",
        "nvidia.com/gpu.sharing-strategy": "none",
        **labels,
    }
    res = {"cpu": "32", "memory": "256Gi", "nvidia.com/gpu": str(slices)}
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": "gpu-node-1", "labels": {k: v for k, v in lab.items() if v}},
        "status": {"capacity": res, "allocatable": res},
    }


def pod(component: str, *, scheduled: bool, message: str = "") -> dict[str, Any]:
    cond = (
        {"type": "Ready", "status": "True"}
        if scheduled
        else {"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": message}
    )
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": f"{component}-7d9-x",
            "labels": {"app.kubernetes.io/component": component},
            "ownerReferences": [{"kind": "ReplicaSet"}],
        },
        "spec": {"nodeName": "gpu-node-1"} if scheduled else {},
        "status": {"conditions": [cond]},
    }


def mig(st: pf.PlatformState, **env: str) -> Any:
    return pf.check_mig_instances(_inputs(st, False, **{**SQ, **env}))


def declared(objs: list[dict[str, Any]]) -> pf.PlatformState:
    st = _cluster(objs, quota=ENOUGH)
    st.source = "manifests"
    return st


# ------------------------------------------------------------------------------------------------ acceptance
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os.environ):
        if k.startswith(("TB_", "SMTP_", "IMAP_")) or k in (
            "KUBERNETES_SERVICE_HOST",
            "NHI_TWPAS_BASE_URL",
            "CLOUD_LLM_BASE_URL",
            "EGRESS_EXTRA",
        ):
            monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("slices", [1, 2])
def test_one_slice_fails_with_a_clear_reason_two_pass(
    slices: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`trialbox doctor --platform` on the shared-quota overlay with stand-in devices (TB_PLATFORM_GPU_STANDIN, as
    kind-check.sh runs it): the node offers one MIG instance -> exit 1, mig_instances names the reason; two -> exit
    0, every check passes or warns (TEST), the measured checks are skipped as stand-ins."""
    _clean_env(monkeypatch)
    from tools.trialbox import doctor

    eg = doctor._egress()
    pols, _ = eg.render_networkpolicy(eg.allowlist({"SMTP_HOST": "smtp.hospa.test"}), lambda h: ["10.0.0.25"])
    quota = {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": "trialbox"}, "spec": {"hard": ENOUGH}}
    man = tmp_path / "rendered.yaml"
    man.write_text(yaml.safe_dump_all([*build("shared-quota"), quota, *pols, node(slices)]), encoding="utf-8")
    site = {
        "TB_ENV": "TEST",
        "TB_PLATFORM_GPU_STANDIN": "1",
        "TB_MIG_PROFILE": MIG,
        "TB_NTP_SERVER": "ntp.hospa.test",
        "SMTP_HOST": "smtp.hospa.test",
        "TB_PLATFORM_STORAGE_ENCRYPTED": "yes",
        "TB_PLATFORM_STORAGE_EVIDENCE": "SC-1",
        "TB_BACKUP_TARGETS": "/mnt/nas",
        "TB_PLATFORM_BACKUP_EVIDENCE": "NAS-1",
    }
    for k, v in site.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(pf, "_connect", lambda h, p: None)
    monkeypatch.setattr(pf, "sntp_offset", lambda s, timeout=3.0: 0.002)
    monkeypatch.setattr(pf, "_resolve", lambda h: ["10.0.0.25"])
    ev = tmp_path / "iq-evidence.json"
    rc = cli(["doctor", "--platform", "--manifests", str(man), "--evidence", str(ev)])
    doc = json.loads(ev.read_text(encoding="utf-8"))
    by = {c["name"]: c for c in doc["checks"]}
    out = capsys.readouterr().out
    assert doc["gpu_standin"] is True and doc["gpu_profile"] == "shared-quota"
    assert by["serving_record"]["detail"] == by["canary"]["detail"] == pf.STANDIN
    assert by["gpu_serving"]["status"] == "PASS" and by["model_key"]["status"] == "PASS"
    if slices == 1:
        assert rc == 1 and doc["passed"] is False
        assert [n for n, c in by.items() if c["status"] == "FAIL"] == ["mig_instances"]
        why = by["mig_instances"]["detail"]
        assert "the nodes offer 1 nvidia.com/gpu for the pair's 2" in why and "ask for two" in why
        assert "FAIL  mig_instances" in out
    else:
        assert rc == 0 and doc["passed"] is True, [c for c in doc["checks"] if c["status"] == "FAIL"]
        assert by["mig_instances"]["status"] == "PASS"
        assert by["mig_instances"]["detail"].startswith(f"two MIG instances (judge {MIG}, verifier {MIG})")


def test_one_slice_in_the_cluster_without_node_read_is_the_pending_pod() -> None:
    """Without components/node-read the job sees no Node: the verifier's pod that the scheduler cannot place for
    want of a device is the reason, in the scheduler's own words."""
    st = _cluster(quota=ENOUGH)
    msg = "0/1 nodes are available: 1 Insufficient nvidia.com/gpu. preemption: 0/1 nodes are available"
    st.objects += [pod("llm-service", scheduled=True), pod("llm-verifier", scheduled=False, message=msg)]
    c = mig(st, TB_PLATFORM_GPU_SHARING="mig", TB_PLATFORM_GPU_EVIDENCE="nvidia-smi mig -lgi, 2026-11-11")
    assert c.status == "FAIL"
    assert (
        "the verifier pod llm-verifier-7d9-x cannot be scheduled (0/1 nodes are available: 1 Insufficient" in c.detail
    )
    assert "ask for two" in c.detail
    # both placed: the declaration is the evidence (and the job says it could not read the nodes)
    st.objects[-1] = pod("llm-verifier", scheduled=True)
    c = mig(st, TB_PLATFORM_GPU_SHARING="mig", TB_PLATFORM_GPU_EVIDENCE="nvidia-smi mig -lgi, 2026-11-11")
    assert c.status == "PASS" and "declared mig" in c.detail and "nodes not readable" in c.detail


# ------------------------------------------------------------------------------------------------ not time-sliced
def test_a_time_slice_or_mps_share_is_refused() -> None:
    def shared_resource(objs: list[dict[str, Any]]) -> None:
        for d in objs:
            if d["kind"] == "Deployment" and d["metadata"]["name"] in ("llm-service", "llm-verifier"):
                r = d["spec"]["template"]["spec"]["containers"][0]["resources"]
                for part in ("requests", "limits"):
                    r[part]["nvidia.com/gpu.shared"] = r[part].pop("nvidia.com/gpu")

    objs = copy.deepcopy(build("shared-quota"))
    shared_resource(objs)
    c = mig(declared([*objs, node(2)]))
    assert c.status == "FAIL" and "asks for nvidia.com/gpu.shared: a time-sliced or MPS share" in c.detail
    for labels, words in (
        ({"nvidia.com/gpu.sharing-strategy": "time-slicing"}, "sharing-strategy=time-slicing"),
        ({"nvidia.com/gpu.sharing-strategy": "mps"}, "sharing-strategy=mps"),
        ({"nvidia.com/gpu.replicas": "4"}, "handed out 4 times: time-sliced"),
        ({"nvidia.com/mig.strategy": "", "nvidia.com/gpu.product": "NVIDIA-B200"}, "MIG is off there"),
    ):
        c = mig(declared([*build("shared-quota"), node(2, **labels)]))
        assert c.status == "FAIL" and words in c.detail, (labels, c.detail)
    c = mig(declared(build("shared-quota")), TB_PLATFORM_GPU_SHARING="time-slicing")
    assert c.status == "FAIL" and "TB_PLATFORM_GPU_SHARING=time-slicing" in c.detail
    # nothing shows MIG: refused in shared-quota; a declaration needs its evidence reference
    c = mig(declared(build("shared-quota")))
    assert c.status == "FAIL" and "not shown to be MIG instances" in c.detail
    c = mig(declared(build("shared-quota")), TB_PLATFORM_GPU_SHARING="mig")
    assert c.status == "FAIL" and "without TB_PLATFORM_GPU_EVIDENCE" in c.detail
    # interim-cloud: whole cards are fine, a time-slice still is not
    whole = {"TB_GPU_PROFILE": "interim-cloud", "TB_MIG_PROFILE": ""}
    st = declared(build("interim-cloud"))
    assert mig(st, **whole).status == "WARN"
    assert mig(st, **whole, TB_PLATFORM_GPU_SHARING="whole").status == "PASS"
    assert mig(st, **whole, TB_PLATFORM_GPU_SHARING="mps").status == "FAIL"


def test_mixed_strategy_two_profiles_and_the_layout() -> None:
    """The `mixed` strategy names each instance's profile in the resource: a 45 GB class instance for the judge and
    a 23 GB class one for the verifier, as TB_MIG_PROFILE says; another layout is refused."""
    objs = copy.deepcopy(build("shared-quota"))
    for d in objs:
        if d["kind"] == "Deployment" and d["metadata"]["name"] in ("llm-service", "llm-verifier"):
            prof = "2g.45gb" if d["metadata"]["name"] == "llm-service" else "1g.23gb"
            r = d["spec"]["template"]["spec"]["containers"][0]["resources"]
            for part in ("requests", "limits"):
                r[part][f"nvidia.com/mig-{prof}"] = r[part].pop("nvidia.com/gpu")
    lay = "judge=2g.45gb,verifier=1g.23gb"
    c = mig(declared(objs), TB_MIG_PROFILE=lay)
    assert c.status == "PASS" and "judge 2g.45gb, verifier 1g.23gb" in c.detail
    c = mig(declared(objs), TB_MIG_PROFILE="judge=3g.90gb,verifier=1g.23gb")
    assert c.status == "FAIL" and "the judge is on MIG profile 2g.45gb, TB_MIG_PROFILE says 3g.90gb" in c.detail
    mixed = node(0, **{"nvidia.com/mig.strategy": "mixed", "nvidia.com/gpu.product": "NVIDIA-B200"})
    mixed["status"]["capacity"] = mixed["status"]["allocatable"] = {"nvidia.com/mig-2g.45gb": "1"}
    c = mig(declared([*objs, mixed]), TB_MIG_PROFILE=lay)
    assert c.status == "FAIL" and "the nodes offer 0 nvidia.com/mig-1g.23gb for the pair's 1" in c.detail
    mixed["status"]["allocatable"] = {"nvidia.com/mig-2g.45gb": "1", "nvidia.com/mig-1g.23gb": "1"}
    mixed["status"]["capacity"] = mixed["status"]["allocatable"]
    assert mig(declared([*objs, mixed]), TB_MIG_PROFILE=lay).status == "PASS"
    c = mig(declared(objs), TB_MIG_PROFILE="unmeasured")
    assert c.status == "FAIL" and "TB_MIG_PROFILE does not name the instances" in c.detail
    c = mig(declared(objs), TB_MIG_PROFILE="judge=2g.45gb")
    assert c.status == "FAIL" and "must name the judge and the verifier" in c.detail


def test_stand_in_devices_are_refused_in_validation_and_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    _clean_env(monkeypatch)  # the egress keys (TB_ENV among them) come from this shell
    man = tmp_path / "rendered.yaml"
    man.write_text(yaml.safe_dump_all(build("shared-quota")), encoding="utf-8")
    a = argparse.Namespace(manifests=man, compose_config=None, release=None, no_gpu=False)
    for env in ("VALIDATION", "PRODUCTION"):
        with pytest.raises(pf.PlatformError, match="stand-in devices are for a test cluster only"):
            pf.inputs_from(a, {"TB_ENV": env, "TB_PLATFORM_GPU_STANDIN": "1"}, ROOT / "models" / "routing.yaml")
        inp = _inputs(_cluster(quota=ENOUGH), TB_ENV=env)
        inp.gpu_standin = True  # given anyway: the measured checks fail, they never skip there
        assert pf.check_serving_record(inp).status == pf.check_canary(inp).status == "FAIL"
    inp = pf.inputs_from(a, {"TB_ENV": "TEST", "TB_PLATFORM_GPU_STANDIN": "1"}, ROOT / "models" / "routing.yaml")
    assert inp.gpu_standin and not inp.no_gpu


# ------------------------------------------------------------------------------------------------ model key
def test_the_shipped_manifests_put_the_key_and_the_guard_in_front_of_both_servers() -> None:
    objs = build("shared-quota")
    c = pf.check_model_key(_inputs(declared(objs)))
    assert c.status == "PASS" and "trialbox-model-key/TB_LLM_API_KEY" in c.detail
    names = {(o["kind"], o["metadata"]["name"]): o for o in objs}
    for svc in ("llm-service", "llm-verifier"):  # the names routing.yaml calls are the guard
        assert names[("Service", svc)]["spec"]["selector"] == {"app.kubernetes.io/component": "model-guard"}
        assert names[("Service", f"{svc}-vllm")]["spec"]["selector"] == {"app.kubernetes.io/component": svc}
    guard = names[("Deployment", "model-guard")]["spec"]["template"]
    env = {e["name"]: e for e in guard["spec"]["containers"][0]["env"]}
    assert env["TB_GUARD_ROUTES"]["value"] == "llm-service=llm-service-vllm:8000,llm-verifier=llm-verifier-vllm:8000"
    assert guard["metadata"]["labels"]["trialbox.io/tier"] == "model-guard"  # not app: other pods cannot reach it
    judge = names[("Deployment", "llm-service")]["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "--chat-template=/models/$(JUDGE_CHAT_TEMPLATE)" in judge  # T-674 on the platform too
    pols = {o["metadata"]["name"]: o["spec"] for o in objs if o["kind"] == "NetworkPolicy"}
    iso = pols["trialbox-model-isolation"]["ingress"][0]["from"]
    assert iso == [{"podSelector": {"matchLabels": {"app.kubernetes.io/component": "model-guard"}}}]
    assert pols["trialbox-gateway-to-models"]["egress"][0]["to"] == iso


def _mutate(fn: Any) -> Any:
    objs = copy.deepcopy(build("shared-quota"))
    fn({(o["kind"], o["metadata"]["name"]): o for o in objs}, objs)
    return pf.check_model_key(_inputs(declared(objs)))


def _env(o: dict[str, Any]) -> list[dict[str, Any]]:
    env: list[dict[str, Any]] = o["spec"]["template"]["spec"]["containers"][0]["env"]
    return env


def test_model_key_refuses_each_way_around_the_key() -> None:
    def no_key(n: dict[Any, Any], _: Any) -> None:
        env = _env(n[("Deployment", "llm-verifier")])
        env[:] = [e for e in env if e["name"] != "VLLM_API_KEY"]

    def plain(n: dict[Any, Any], _: Any) -> None:
        env = _env(n[("Deployment", "llm-service")])
        env[:] = [e for e in env if e["name"] != "VLLM_API_KEY"] + [{"name": "VLLM_API_KEY", "value": "k" * 40}]

    def direct(n: dict[Any, Any], _: Any) -> None:
        n[("Service", "llm-service")]["spec"]["selector"] = {"app.kubernetes.io/component": "llm-service"}

    def no_guard(n: dict[Any, Any], objs: list[dict[str, Any]]) -> None:
        objs.remove(n[("Deployment", "model-guard")])

    def gateway_keyless(n: dict[Any, Any], _: Any) -> None:
        env = _env(n[("Deployment", "gateway")])
        env[:] = [e for e in env if e["name"] != "TB_LLM_API_KEY"]

    def lake_holds_it(n: dict[Any, Any], _: Any) -> None:
        ref = {"secretKeyRef": {"name": "trialbox-model-key", "key": "TB_LLM_API_KEY"}}
        _env(n[("Deployment", "lake")]).append({"name": "X", "valueFrom": ref})

    def two_keys(n: dict[Any, Any], _: Any) -> None:
        for e in _env(n[("Deployment", "model-guard")]):
            if e["name"] == "TB_LLM_API_KEY":
                e["valueFrom"]["secretKeyRef"]["name"] = "another-key"

    for fn, words in (
        (no_key, "the verifier Deployment/llm-verifier runs without VLLM_API_KEY"),
        (plain, "VLLM_API_KEY is a plain value in the manifest"),
        (direct, "Service llm-service selects"),
        (no_guard, "no model-guard in front of the model servers"),
        (gateway_keyless, "the gateway (Deployment/gateway) holds no TB_LLM_API_KEY"),
        (lake_holds_it, "Deployment/lake also holds the model key"),
        (two_keys, "do not read one key"),
    ):
        c = _mutate(fn)
        assert c.status == "FAIL" and words in c.detail, (fn.__name__, c.detail)
        assert "k" * 40 not in c.detail  # a value is never echoed


@pytest.fixture
def guard() -> Iterator[str]:
    """The real model-guard (D-177) on a local port, routes as on the platform; nothing behind it."""
    from model_guard import Guard, make_handler, parse_routes

    g = Guard("platform-test-key-0123456789", parse_routes("llm-service=127.0.0.1:9,llm-verifier=127.0.0.1:9"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(g))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def open_server() -> Iterator[str]:
    """A model server with no key and no guard: everything answers 200."""

    class H(BaseHTTPRequestHandler):
        def _ok(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = do_POST = _ok

        def log_message(self, format: str, *args: Any) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_in_the_cluster_the_server_refuses_a_call_without_the_key(guard: str, open_server: str) -> None:
    st = _cluster(quota=ENOUGH)
    inp = _inputs(st)
    inp.guard_urls = {"llm-service": guard, "llm-verifier": guard}
    c = pf.check_model_key(inp)
    assert c.status == "PASS", c.detail
    assert "llm-service refuses without the key (401)" in c.detail and "llm-verifier refuses" in c.detail
    inp.guard_urls = {"llm-service": guard, "llm-verifier": open_server}
    c = pf.check_model_key(inp)
    assert c.status == "FAIL" and "llm-verifier: a call without the key answered 200" in c.detail
    assert "POST /invocations without the key answered 200" in c.detail
    inp.guard_urls = {"llm-service": "http://127.0.0.1:9", "llm-verifier": guard}
    c = pf.check_model_key(inp)
    assert c.status == "FAIL" and "llm-service: model-guard not reachable (no answer)" in c.detail
    # model_key needs no GPU: it runs with --no-gpu too (kind without devices)
    inp.no_gpu = True
    assert pf.check_model_key(inp).status == "FAIL"


def test_compose_form_guard_and_networks() -> None:
    key_set = {"VLLM_API_KEY": "secret-value-never-kept"}

    def config(verifier_nets: dict[str, Any]) -> dict[str, Any]:
        return {
            "services": {
                "llm-service": {"image": "v", "environment": key_set, "networks": {"model-backend-net": {}}},
                "llm-verifier": {"image": "v", "environment": key_set, "networks": verifier_nets},
                "model-guard": {"image": "p", "environment": {"TB_LLM_API_KEY": "k"}, "networks": {"model-net": {}}},
                "gateway": {"image": "p", "environment": {"TB_LLM_API_KEY": "k"}, "networks": {"model-net": {}}},
            }
        }

    st = pf.state_from_compose(config({"model-backend-net": {}}))
    assert "secret-value-never-kept" not in json.dumps(st.objects)
    c = pf.check_model_key(_inputs(st))
    assert c.status == "PASS" and "doctor --serving" in c.detail
    c = pf.check_model_key(_inputs(pf.state_from_compose(config({"model-net": {}}))))
    assert c.status == "FAIL" and "the verifier (Deployment/llm-verifier) is on model-net" in c.detail


def test_shared_quota_compose_keeps_both_servers_behind_the_guard() -> None:
    """LLM-028 on the Docker form: the shared-quota file no longer puts vLLM on model-net (the base's model-guard
    answers to their names there) and gives both servers the key."""
    from tests.unit.test_platform_manifests import _Loader

    doc = yaml.load((ROOT / "deploy/docker-compose.shared-quota.yml").read_text(encoding="utf-8"), Loader=_Loader)
    for svc, alias in (("llm-service", "llm-service-vllm"), ("llm-verifier", "llm-verifier-vllm")):
        body = doc["services"][svc]
        assert "VLLM_API_KEY" not in body["environment"], svc  # D-450: from the servers' own env file
        assert {"path": "./secrets/model/vllm.env", "required": False} in body["env_file"], svc
        assert body["networks"] == {"model-backend-net": {"aliases": [alias]}}, svc


# ------------------------------------------------------------------------------------------------ serving record
def _record(judge_dev: str = "MIG-aaaa-1", verifier_dev: str = "MIG-bbbb-2", **over: Any) -> dict[str, Any]:
    rec: dict[str, Any] = json.loads((ROOT / "deploy/measured/serving_config.rtxpro6000.json").read_text("utf-8"))
    rec["card"] = {**rec["card"], "name": "NVIDIA B200", "mig": True, "capped_to": None}
    for s, dev, prof, n in (
        (rec["servers"][0], judge_dev, "2g.45gb", 16384),
        (rec["servers"][1], verifier_dev, "1g.23gb", 8192),
    ):
        s.update({"gpu_devices": [dev] if dev else [], "mig_profile": prof, "max_model_len": n})
    rec.update(over)
    return rec


def test_the_serving_rule_is_keyed_on_the_mig_profile() -> None:
    assert [s["role"] for s in _record()["servers"]] == ["judge", "verifier"]
    assert sc.measured_for(_record(), "shared-quota") == []
    same = sc.measured_for(_record(verifier_dev="MIG-aaaa-1"), "shared-quota")
    assert any("time-sliced, not two MIG instances" in w for w in same)
    whole = sc.measured_for(_record(judge_dev="GPU-1234"), "shared-quota")
    assert any("judge ran on ['GPU-1234'], not on one MIG instance" in w for w in whole)
    small = _record()
    small["servers"][0]["max_model_len"] = 8192  # a 45 GB instance must reach 16k
    assert sc.measured_for(small, "shared-quota") == ["judge context 8192 < 16384"]
    odd = _record()
    odd["servers"][1]["mig_profile"] = "5g.99gb"
    assert any("no rule for MIG profile 5g.99gb" in w for w in sc.measured_for(odd, "shared-quota"))
    off = _record()
    off["card"]["mig"] = False
    assert any("MIG off" in w for w in sc.measured_for(off, "shared-quota"))
    assert any("not an B200" in w for w in sc.measured_for(_record(card={"name": "NVIDIA H100"}), "shared-quota"))
    assert sc.mig_layout("3g.90gb") == {"judge": "3g.90gb", "verifier": "3g.90gb"}
    assert sc.mig_layout(" judge=2g.45gb, verifier=1g.23gb+me ") == {"judge": "2g.45gb", "verifier": "1g.23gb+me"}
    assert sc.mig_layout("unmeasured") == {} and sc.mig_base("1g.23gb+me") == "1g.23gb"
    for bad in ("3g", "judge=3g.90gb", "judge=3g.90gb,cook=1g.23gb"):
        with pytest.raises(ValueError):
            sc.mig_layout(bad)
    smi = (
        "GPU 0: NVIDIA B200 (UUID: GPU-5f2c)\n"
        "  MIG 2g.45gb      Device  0: (UUID: MIG-aaaa-1)\n"
        "  MIG 1g.23gb      Device  1: (UUID: MIG-bbbb-2)\n"
    )
    assert sc.parse_mig_list(smi) == {"MIG-aaaa-1": "2g.45gb", "MIG-bbbb-2": "1g.23gb"}
    assert "shared-quota" in sc.PROFILE_CARDS  # `serving_config measured shared-quota <record>`


def test_platform_serving_record_follows_the_shared_quota_rule(tmp_path: Path) -> None:
    p = tmp_path / "serving_config.json"
    p.write_text(json.dumps(_record()), encoding="utf-8")
    st = _cluster(quota=ENOUGH)
    env = {"TB_GPU_PROFILE": "shared-quota", "TB_SERVING_RECORD": str(p)}
    c = pf.check_serving_record(_inputs(st, False, **env, TB_MIG_PROFILE="judge=2g.45gb,verifier=1g.23gb"))
    assert c.status == "PASS" and "judge 2g.45gb, verifier 1g.23gb" in c.detail
    c = pf.check_serving_record(_inputs(st, False, **env, TB_MIG_PROFILE="3g.90gb"))
    assert (
        c.status == "FAIL" and "the record's judge ran on MIG profile 2g.45gb, this namespace's is 3g.90gb" in c.detail
    )
    p.write_text(json.dumps(_record(verifier_dev="MIG-aaaa-1")), encoding="utf-8")
    c = pf.check_serving_record(_inputs(st, False, **env, TB_MIG_PROFILE="judge=2g.45gb,verifier=1g.23gb"))
    assert c.status == "FAIL" and "time-sliced" in c.detail


# ------------------------------------------------------------------------------------------------ builds and pins
def test_shared_quota_has_its_own_builds_and_the_pin_job_pins_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = yaml.safe_load((ROOT / "models/registry.yaml").read_text(encoding="utf-8"))
    builds = {b["build_id"]: b for b in doc["builds"]}
    pairs = pin_model.PROFILE_PAIRS["shared-quota"]
    assert [p[0] for p in pairs] == ["gemma-4-26b-a4b-it-sharedquota", "qwen3.5-9b-sharedquota"]
    for (build_id, endpoint, *_), measured in zip(pairs, pin_model.PROFILE_PAIRS["rtxpro6000"], strict=True):
        b = builds[build_id]
        assert endpoint in b["served"] and b["status"] == "candidate"
        assert b["expected"] == builds[measured[0]]["expected"]  # the same weights as the measured pair
        assert b["context_length"] is None  # measured on the instance, never assumed
    assert builds["gemma-4-26b-a4b-it-frontdesk-sharedquota"]["alias"] == "f-frontdesk"
    job = yaml.safe_load((PLATFORM / "overlays/shared-quota/pin.yaml").read_text(encoding="utf-8"))
    c = job["spec"]["template"]["spec"]["containers"][0]
    assert c["command"][:5] == ["python", "-m", "tools.pin_model", "--install", "shared-quota"]
    assert c["command"][-2:] == ["--out", "/data/pins/registry.site.yaml"]
    objs = build("shared-quota")
    gw = next(o for o in objs if o["kind"] == "Deployment" and o["metadata"]["name"] == "gateway")
    env = {e["name"]: e.get("value") for e in _env(gw)}
    assert env["TB_REGISTRY_OVERRIDE"] == "/data/pins/registry.site.yaml"
    assert any(o["kind"] == "Job" and o["metadata"]["name"] == "trialbox-pin" for o in objs)
    assert not any(o["kind"] == "Job" and o["metadata"]["name"] == "trialbox-pin" for o in build("interim-cloud"))
    # what the job does, on synthetic weights that are the (synthetic) release's
    models = tmp_path / "models"
    folders = {}
    for build_id, _ep, _dv, d, *_ in pairs:
        (models / d).mkdir(parents=True, exist_ok=True)
        (models / d / "model.safetensors").write_bytes(f"synthetic {d}".encode())
        folders[build_id] = models / d
    reg = release_registry(tmp_path, folders, monkeypatch)
    out = tmp_path / "pins" / "registry.site.yaml"
    out.parent.mkdir()
    ok, lines = pin_model.install_pins("shared-quota", models, out, {}, registry_path=reg)
    assert ok, lines
    pinned = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    assert set(pinned) == {b for b, *_ in pairs} and {p["status"] for p in pinned.values()} == {"candidate"}
    assert pinned["qwen3.5-9b-sharedquota"]["served"] == {"verifier": pin_model.VERIFIER_SERVED}
