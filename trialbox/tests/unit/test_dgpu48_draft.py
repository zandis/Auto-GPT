"""Cards 24-5 and 24-6 (root review 24): the DRAFT 48 GB class, UNMEASURED, prepared and not enabled.

``deploy/docker-compose.dgpu48.yml`` and ``deploy/dgpu48-profile.yaml`` hold the options; ``tools/dgpu48.py`` carries
the 96 GB card's measured figures to 48 GB and runs the measuring run on the owner's machine. Shown here without a
card: the overlay parses and serves only registry builds with the pinned engine by default; install.sh and poc.sh
refuse the word whatever is set, and the measuring run refuses without its switch; the arithmetic gives review 19's
figures; the box planner's answer on the owner's 53 GB; the dry run; and one faked measuring run end to end, whose
files carry no host name, device UUID, host path or key. Nothing here becomes a profile: no measurement rule, no
detection, no record."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import dgpu48, serving_config
from tools import engine_probe as ep
from tools.box import plan as bp

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy" / "docker-compose.dgpu48.yml"

pytestmark = pytest.mark.nodb


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return dgpu48.load()


# ------------------------------------------------------------------------------------------------ the files
def test_the_overlay_parses_and_serves_the_pinned_pair_with_the_pinned_engine() -> None:
    svc = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))["services"]
    lock = json.loads((ROOT / "deploy/images.lock").read_text(encoding="utf-8"))["third_party"]["vllm"]
    for name in ("llm-service", "llm-verifier"):
        s = svc[name]
        assert s["image"] == f"${{VLLM_IMAGE:-{lock['image']}@{lock['digest']}}}"
        assert s["labels"]["tb.profile"] == "dgpu48-UNMEASURED"
        assert s["profiles"] == ["gpu"]
        assert s["environment"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] == "${VLLM_ENABLE_CUDA_COMPATIBILITY:-0}"
    judge = " ".join(svc["llm-service"]["command"])
    assert "--gpu-memory-utilization=${JUDGE_GPU_MEM_UTIL:-0.57}" in judge
    assert "--max-model-len=${JUDGE_MAX_LEN:-32768}" in judge and "--chat-template-content-format=string" in judge
    assert "--gpu-memory-utilization=${VERIFIER_GPU_MEM_UTIL:-0.27}" in " ".join(svc["llm-verifier"]["command"])
    assert svc["gateway"]["environment"]["TB_PROFILE"] == "P-DGPU48-UNMEASURED"


def test_the_overlay_defaults_are_the_first_option(doc: dict[str, Any]) -> None:
    text = OVERLAY.read_text(encoding="utf-8")
    first = min(doc["options"], key=lambda o: o["order"])
    assert first["id"] == "pair-32k"
    for var, value in first["env"].items():
        assert f"${{{var}:-{value}}}" in text, var


def test_the_profile_is_unmeasured_and_names_only_registry_builds(doc: dict[str, Any]) -> None:
    assert doc["status"] == "unmeasured" and doc["record"] is None
    assert doc["card"]["memory_measured_mib"] is None
    assert set(doc["host"]["measured_peak_gib"].values()) == {None}
    assert doc["switch"] == dgpu48.SWITCH
    reg = yaml.safe_load((ROOT / "models/registry.yaml").read_text(encoding="utf-8"))
    ids = {b["build_id"] for b in reg["builds"]}
    assert "gemma-4-31b-it-qat-challenger" in ids  # the one other build the options name
    assert [o["order"] for o in doc["options"]] == sorted(o["order"] for o in doc["options"])
    assert {o["id"] for o in doc["options"] if o["scripted"]} == {"pair-32k", "pair-16k", "judge-alone",
                                                                  "verifier-alone"}  # fmt: skip


def test_it_is_not_a_profile_anywhere() -> None:
    assert "dgpu48" not in serving_config.PROFILES  # no measurement rule: no record makes it installable
    assert "dgpu48" not in bp.PAIR_PROFILES
    for arch, card in (("aarch64", "NVIDIA RTX A6000"), ("x86_64", "NVIDIA RTX A6000"),
                       ("x86_64", "NVIDIA RTX 6000 Ada Generation")):  # fmt: skip
        out = subprocess.run(["sh", str(ROOT / "deploy/gpu_profile.sh"), arch, card], capture_output=True, text=True,
                             check=True).stdout.strip()  # fmt: skip
        assert out != "dgpu48"
    from tools import pin_model

    assert "dgpu48" not in pin_model.PROFILE_PAIRS


# ------------------------------------------------------------------------------------------------ refusals
def test_install_refuses_it_whatever_is_set() -> None:
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    line = next(ln for ln in install.splitlines() if ln.strip().startswith("dgpu48)"))
    assert "die " in line and "no install serves it" in line and dgpu48.SWITCH in line
    # the refusal comes before the list of words install.sh accepts, which does not name it
    assert install.index('  dgpu48) die "dgpu48 is a DRAFT') < install.index('case "$GPU" in auto|default|')
    accepted = next(ln for ln in install.splitlines() if ln.startswith('case "$GPU" in auto|default|'))
    assert "dgpu48" not in accepted


def _poc(tmp: Path, **env: str) -> subprocess.CompletedProcess[str]:
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    for rel in ("deploy/poc.sh", "deploy/gpu_profile.sh", ".env.example"):
        (root / rel).write_bytes((ROOT / rel).read_bytes())
    bindir = tmp / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text('#!/bin/sh\necho "$*" >> "$TB_TEST_LOG"\necho "Runtimes: nvidia runc"\nexit 0\n',
                                   encoding="utf-8")  # fmt: skip
    (bindir / "nvidia-smi").write_text('#!/bin/sh\necho "GPU 0: NVIDIA RTX A6000 (UUID: GPU-0)"\n', encoding="utf-8")
    for f in bindir.iterdir():
        f.chmod(0o755)
    full = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    full.update(PATH=f"{bindir}:/usr/bin:/bin", TB_TEST_LOG=str(tmp / "docker.log"), **env)
    return subprocess.run(["bash", str(root / "deploy/poc.sh")], capture_output=True, text=True, env=full,
                          timeout=60, check=False)  # fmt: skip


@pytest.mark.parametrize("switch", ["", "1"])
def test_the_poc_refuses_it_even_with_the_switch(tmp_path: Path, switch: str) -> None:
    res = _poc(tmp_path, TB_LLM_MODE="gpu", TB_GPU_PROFILE="dgpu48", TB_UNMEASURED_DGPU48_MEASURING_RUN=switch)
    assert res.returncode == 1
    assert "dgpu48 is a DRAFT, UNMEASURED 48 GB profile" in res.stderr and "tools/dgpu48.py measure" in res.stderr
    assert not (tmp_path / "root/deploy/.env").exists()


def test_the_measuring_run_refuses_without_its_switch(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        calls.append(cmd)
        return 0, "", ""

    probe = tmp_path / "p.json"
    probe.write_text(json.dumps({"verdict": {"use": "pinned"}}), encoding="utf-8")
    with pytest.raises(dgpu48.Refused, match=f"{dgpu48.SWITCH}=1 is not set"):
        dgpu48.measure(run, "pair-32k", tmp_path / "out", probe, environ={}, say=lambda s: None, root=tmp_path)
    assert calls == []  # nothing asked of docker or the card
    with pytest.raises(dgpu48.Refused, match="arithmetic only"):
        dgpu48.measure(run, "swap-32k", tmp_path / "out", probe, environ={dgpu48.SWITCH: "1"}, say=lambda s: None,
                       root=tmp_path)  # fmt: skip
    assert dgpu48.main(["measure", "--option", "pair-32k", "--probe", str(probe), "--out-dir", str(tmp_path)]) == 2


def test_no_probe_or_a_probe_that_found_nothing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(dgpu48.Refused, match="engine probe found no form"):
        dgpu48.engine_from_probe(None)
    with pytest.raises(dgpu48.Refused, match="engine probe found no form"):
        dgpu48.engine_from_probe({"verdict": {"use": None}})
    assert dgpu48.engine_from_probe({"verdict": {"use": "pinned+compat"}})["env"] == {
        "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"
    }
    cu = dgpu48.engine_from_probe({"verdict": {"use": "cu129"}})
    assert cu["env"] == {"VLLM_IMAGE": ep.CU129} and cu["pinned_engine"] is False
    assert dgpu48.engine_from_probe(None, "pinned")["pinned_engine"] is True


# ------------------------------------------------------------------------------------------------ the arithmetic
def test_the_pair_at_32k_is_review_19s_split(doc: dict[str, Any]) -> None:
    a = dgpu48.arith(doc, dgpu48.option(doc, "pair-32k"))
    j, v = a["servers"]["judge"], a["servers"]["verifier"]
    assert (j["budget_mib"], j["cache_mib"], v["budget_mib"], v["cache_mib"]) == (28010, 9090, 13268, 4268)
    assert a["used_mib"] == 45128 and a["spare_mib"] == 4012  # review 24 §2's table
    assert j["one_sequence_fits"] and v["one_sequence_fits"] and a["fits"]
    assert 84000 < j["cache_tokens"] < 85000  # "about 86k tokens" in review 19 (its 9 GiB rounded)
    assert a["slack_mib"] == 2815  # the verifier's cache past one 32k sequence is the smallest margin


def test_every_scripted_option_fits_the_card_on_the_measured_figures(doc: dict[str, Any]) -> None:
    for o in doc["options"]:
        a = dgpu48.arith(doc, o)
        if o["scripted"]:
            assert a["fits"], o["id"]
            assert a["spare_mib"] >= doc["basis"]["min_free_mib"], o["id"]
        else:
            assert a["fits"] is None and a["servers"] == {}


def test_the_96_gb_profiles_split_does_not_fit_48_gb(doc: dict[str, Any]) -> None:
    """Review 24 §2: the rtxpro6000 profile's 0.40 and 0.20 on this card start neither server."""
    o = {"id": "rtxpro6000-on-48", "serves": ["judge", "verifier"],
         "env": {"JUDGE_GPU_MEM_UTIL": "0.40", "VERIFIER_GPU_MEM_UTIL": "0.20", "JUDGE_MAX_LEN": "32768",
                 "VERIFIER_MAX_LEN": "32768"}}  # fmt: skip
    a = dgpu48.arith(doc, o)
    assert not a["servers"]["judge"]["one_sequence_fits"] and not a["servers"]["verifier"]["one_sequence_fits"]
    assert not a["fits"]


def test_the_table_prints_every_option(doc: dict[str, Any]) -> None:
    out = dgpu48.arith_table(doc)
    for o in doc["options"]:
        assert o["id"] in out
    assert "45,128  4,012" in out


# ------------------------------------------------------------------------------------------------ the planner
def test_the_planner_refuses_the_whole_box_with_the_pair_on_53_gib() -> None:
    p = dgpu48.planner(53)
    assert not p["accepted"] and "needs at least 63 GiB" in p["notes"][0]
    assert p["model_caps_gib"] == {"TB_MEM_LLM": 32.0, "TB_MEM_VERIFIER": 32.0}
    assert dgpu48.planner(64)["accepted"]  # at the planner's floor: every cap at half its default
    assert p["least_gib_floor"] == 63.9 and p["least_gib_unshrunk"] == 123.9
    # the stub box still fits 53 GiB as it did (review 24 §3)
    assert bp.memory_caps(53, "stub")[1] == [
        "memory: 53 GiB, 5.3 GiB kept for the system, the caps at 1.00 of the defaults"
    ]


# ------------------------------------------------------------------------------------------------ the measuring run
def test_the_dry_run_starts_nothing_and_names_the_commands(tmp_path: Path) -> None:
    probe = tmp_path / "p.json"
    probe.write_text(json.dumps({"verdict": {"use": "pinned+compat"}}), encoding="utf-8")
    said: list[str] = []

    def run(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        raise AssertionError(f"the dry run ran {cmd}")

    s = dgpu48.measure(run, "pair-32k", tmp_path / "out", probe, dry_run=True, environ={}, say=said.append,
                       root=tmp_path)  # fmt: skip
    up = s["commands"]["up"]
    assert up[:4] == ["docker", "compose", "--project-directory", "deploy"]
    assert "deploy/docker-compose.dgpu48.yml" in up and up[-2:] == ["llm-service", "llm-verifier"]
    assert "--verifier-url" in s["commands"]["canary"]
    text = "\n".join(said)
    assert "VLLM_ENABLE_CUDA_COMPATIBILITY=1" in text and "JUDGE_GPU_MEM_UTIL=0.57" in text
    assert "tools/serving_config.py capture" in text
    # the verifier alone: no judge, no canary, no wait for a judge
    s = dgpu48.measure(run, "verifier-alone", tmp_path / "out", probe, dry_run=True, environ={}, say=said.append,
                       root=tmp_path)  # fmt: skip
    assert s["commands"]["canary"] is None and "--no-deps" in s["commands"]["up"]
    # the judge alone: the canary without a verifier
    s = dgpu48.measure(run, "judge-alone", tmp_path / "out", probe, dry_run=True, environ={}, say=said.append,
                       root=tmp_path)  # fmt: skip
    assert "--verifier-url" not in s["commands"]["canary"] and s["commands"]["up"][-1] == "llm-service"


def test_the_dry_run_runs_from_the_command_line(tmp_path: Path) -> None:
    probe = tmp_path / "p.json"
    probe.write_text(json.dumps({"verdict": {"use": "pinned"}}), encoding="utf-8")
    env = {**os.environ, dgpu48.SWITCH: "1"}
    res = subprocess.run(["python3", "tools/dgpu48.py", "measure", "--option", "pair-32k", "--probe", str(probe),
                          "--out-dir", str(tmp_path / "o"), "--dry-run"], cwd=ROOT, env=env, capture_output=True,
                         text=True, check=False)  # fmt: skip
    assert res.returncode == 0, res.stderr
    assert "nothing is started" in res.stdout


def _machine(tmp: Path) -> tuple[Path, Path]:
    """A checkout with deploy/.env, the weights folders and the template (fake files), and the probe's result."""
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    (root / "deploy/.env").write_text("TB_EMBED_MODE=hash\n", encoding="utf-8")
    (root / "deploy/secrets/model").mkdir(parents=True)
    (root / "deploy/secrets/model/vllm.env").write_text("VLLM_API_KEY=key-that-must-not-show-0123\n", encoding="utf-8")
    for d in ("gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"):
        (root / "deploy/models" / d).mkdir(parents=True)
        (root / "deploy/models" / d / "config.json").write_text("{}", encoding="utf-8")
    tpl = root / "deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("{{ x }}", encoding="utf-8")
    probe = tmp / "probe.json"
    probe.write_text(json.dumps({"verdict": {"use": "pinned+compat"}}), encoding="utf-8")
    return root, probe


class Box:
    """The machine's commands, answered: a 48 GB card, compose, docker, the record capture and the canary."""

    def __init__(self, root: Path, card_mib: int = 49140, running: str = "", up_rc: int = 0) -> None:
        self.root, self.card_mib, self.running, self.up_rc = root, card_mib, running, up_rc
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []

    def __call__(self, cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        self.calls.append((cmd, env))
        if cmd[0] == "nvidia-smi":
            if "memory.used" in cmd[1]:
                return 0, "45300\n", ""
            return 0, f"NVIDIA RTX A6000, {self.card_mib}, 535.183.01\n", ""
        if cmd[:2] == ["docker", "ps"]:
            return 0, self.running, ""
        if cmd[:2] == ["docker", "compose"]:
            if "up" in cmd:
                return self.up_rc, "", "" if self.up_rc == 0 else "container trialbox-llm-service-1 is unhealthy"
            if "ps" in cmd:
                return 0, ("aaa" if cmd[-1] == "llm-service" else "bbb") + "\n", ""
            return 0, "", ""
        if cmd[:2] == ["docker", "inspect"]:
            name = "trialbox-llm-service-1" if cmd[-1] == "aaa" else "trialbox-llm-verifier-1"
            return 0, f"/{name}|0\n", ""
        if cmd[:2] == ["docker", "logs"]:
            return 0, "INFO Available KV cache memory: 8.61 GiB\nINFO GPU KV cache size: 81,920 tokens\n", ""
        if cmd[:2] == ["docker", "stats"]:
            return 0, "trialbox-llm-service-1 14.2GiB / 32GiB\ntrialbox-llm-verifier-1 6.5GiB / 32GiB\n", ""
        if cmd[:3] == ["docker", "run", "--rm"]:  # the canary
            rep = {"ok": True, "cases": 54, "models": [{"role": "judge", "model": "local/j", "cases": 54,
                   "answered": 54, "correct": 53, "flips": 0, "seconds": 300.0}], "pair": {"decided_wrong": 0},
                   "problems": [], "seconds": 600.0}  # fmt: skip
            return 0, json.dumps(rep), ""
        if "capture" in cmd:  # tools/serving_config.py capture: a record as the real one writes it
            out = Path(cmd[cmd.index("--out") + 1])
            server = {"role": "judge", "container": "trialbox-llm-service-1", "vllm_version": "0.32.0",
                      "model": "/models/gemma-4-26b-a4b-it-4bit", "max_model_len": 32768, "max_num_seqs": 16,
                      "enforce_eager": True, "gpu_memory_utilization": 0.57, "model_files_sha256": "a" * 64,
                      "model_files": [{"path": "config.json", "bytes": 2, "sha256": "b" * 64}],
                      "model_dir": str(self.root / "deploy/models/gemma-4-26b-a4b-it-4bit"),
                      "gpu_devices": ["GPU-5f3c2a1b-77aa-4d2e-9b10-0123456789ab"]}  # fmt: skip
            rec = {"schema": serving_config.SCHEMA, "captured_at": "2026-11-25T01:00:00+00:00",
                   "host": "igx-lab-07.example.internal", "memory_used_mib": 45300,
                   "card": {"name": "NVIDIA RTX A6000", "memory_total_mib": 49140, "driver": "535.183.01",
                            "cuda": "12.2", "count": 1, "capped_to": None, "mig": False},
                   "servers": [server, {**server, "role": "verifier", "container": "trialbox-llm-verifier-1"}],
                   "notes": cmd[cmd.index("--notes") + 1]}  # fmt: skip
            out.write_text(json.dumps(rec), encoding="utf-8")
            return 0, "wrote; complete", ""
        raise AssertionError(f"unexpected command {cmd}")


def test_a_faked_measuring_run_end_to_end(tmp_path: Path) -> None:
    root, probe = _machine(tmp_path)
    box = Box(root)
    out = tmp_path / "out"
    s = dgpu48.measure(box, "pair-32k", out, probe, environ={dgpu48.SWITCH: "1"}, say=lambda x: None, root=root)
    assert s["started"] and s["record_complete"] and s["canary"]["ok"]
    assert s["outcome"] == "STARTED, RECORD TAKEN, CANARY PASSED: send the files"
    assert s["engine_log"]["judge"] == {"kv_cache_gib": 8.61, "kv_cache_tokens": 81920}
    assert s["card_peak_mib"] == 45300 and s["host_peak_mib"]["trialbox-llm-service-1"] == 14540.8
    assert s["predicted"]["spare_mib"] == 4012
    _, up_env = next((c, e) for c, e in box.calls if c[:2] == ["docker", "compose"] and "up" in c)
    assert up_env is not None and up_env["VLLM_ENABLE_CUDA_COMPATIBILITY"] == "1"
    assert up_env["JUDGE_GPU_MEM_UTIL"] == "0.57" and up_env["TB_MODELS_DIR"] == str(root / "deploy/models")
    canary_cmd, canary_env = next((c, e) for c, e in box.calls if c[:3] == ["docker", "run", "--rm"])
    assert "--network" in canary_cmd and dgpu48.BACKEND_NET in canary_cmd
    assert canary_env == {"TB_GPU_KEY": "key-that-must-not-show-0123"}  # from the servers' own file, by environment
    assert "key-that-must-not-show-0123" not in " ".join(canary_cmd)
    assert any(c[:2] == ["docker", "compose"] and "rm" in c for c, _ in box.calls)  # the servers are stopped
    # the record: the 96 GB record's shape, complete, nothing that names the machine
    rec = json.loads((out / "serving_config.dgpu48.pair-32k.json").read_text(encoding="utf-8"))
    assert serving_config.validate(rec) == []
    assert set(rec) == set(json.loads((ROOT / "deploy/measured/serving_config.rtxpro6000.json").read_text()))
    assert rec["host"] == dgpu48.WITHHELD
    assert rec["servers"][0]["gpu_devices"] == ["GPU-<withheld>"]
    assert rec["servers"][0]["model_dir"] == "/models/gemma-4-26b-a4b-it-4bit"
    assert "not a profile" in rec["notes"] and "pinned+compat" in rec["notes"]
    assert serving_config.measured_for(rec, "rtxpro6000")  # not a measurement of any profile
    files = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    for leak in ("igx-lab-07", "5f3c2a1b", str(root), "key-that-must-not-show"):
        assert leak not in files, leak
    assert not list(out.glob(".serving_config.*"))  # the raw capture is not left behind


def test_a_run_that_does_not_start_says_so_and_stops(tmp_path: Path) -> None:
    root, probe = _machine(tmp_path)
    box = Box(root, up_rc=1)
    s = dgpu48.measure(box, "pair-32k", tmp_path / "out", probe, environ={dgpu48.SWITCH: "1"}, say=lambda x: None,
                       root=root)  # fmt: skip
    assert not s["started"] and s["outcome"].startswith("DID NOT START")
    assert "unhealthy" in s["start_error"]
    assert not any("capture" in c for c, _ in box.calls)
    assert any(c[:2] == ["docker", "compose"] and "rm" in c for c, _ in box.calls)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"card_mib": 97887}, "dgpu48 is for one card of"),
        ({"running": "abc\n"}, "the box is running"),
    ],
)
def test_the_wrong_machine_or_a_running_box_is_refused(tmp_path: Path, change: dict[str, Any], said: str) -> None:
    root, probe = _machine(tmp_path)
    box = Box(root, **change)
    with pytest.raises(dgpu48.Refused, match=said):
        dgpu48.measure(box, "pair-32k", tmp_path / "out", probe, environ={dgpu48.SWITCH: "1"}, say=lambda x: None,
                       root=root)  # fmt: skip
    assert not any(c[:2] == ["docker", "compose"] for c, _ in box.calls)


def test_missing_weights_are_refused(tmp_path: Path) -> None:
    root, probe = _machine(tmp_path)
    (root / "deploy/models/qwen3.5-9b-4bit/config.json").unlink()
    with pytest.raises(dgpu48.Refused, match="no verifier weights"):
        dgpu48.measure(Box(root), "pair-32k", tmp_path / "out", probe, environ={dgpu48.SWITCH: "1"},
                       say=lambda x: None, root=root)  # fmt: skip
    # the judge alone does not need the verifier's folder
    s = dgpu48.measure(Box(root), "judge-alone", tmp_path / "out", probe, environ={dgpu48.SWITCH: "1"},
                       say=lambda x: None, root=root)  # fmt: skip
    assert s["started"]


def test_the_libs_first_form_writes_its_own_override_outside_the_checkout(tmp_path: Path) -> None:
    def run(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        return 0, json.dumps(["PATH=/usr/bin", "LD_LIBRARY_PATH=/usr/local/nvidia/lib64"]), ""

    f = dgpu48.libs_override(run, "img", tmp_path)
    body = yaml.safe_load(f.read_text(encoding="utf-8"))
    for svc in ("llm-service", "llm-verifier"):
        assert (
            body["services"][svc]["environment"]["LD_LIBRARY_PATH"] == "/usr/local/cuda/compat:/usr/local/nvidia/lib64"
        )


def test_host_memory_text_is_read() -> None:
    assert dgpu48.to_mib("14.2GiB") == 14540.8 and dgpu48.to_mib("512MiB") == 512 and dgpu48.to_mib("n/a") is None


def test_the_canary_runs_the_judge_alone() -> None:
    """tools/canary.py --judge-url without --verifier-url: the judge's cases only (judge-alone option)."""
    from tools import canary

    judge, verifier = canary.direct_clients("http://j/v1", "", "k")
    assert judge is not None and verifier is None
