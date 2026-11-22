"""H-74, part A: the bench host's driver exception in the 48 GB host run (tools/measure48-host.sh), on H-67's rig.

Below deploy/images.lock gpu.driver_min the run goes on only with --bench-driver-exception forward-compat and an engine
probe result (tools/engine_probe.py) that passed with a forward-compatibility form of the pinned image on this card's
model and this driver; s08 then serves with that form, and the run's records say so in words. Without the option the
H-72 refusal stands; the install path (deploy/check_host.sh, deploy/install.sh, tools/images_lock.py) has no such
exception at all."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_measure48_host_h67 import ROOT, Rig
from tools import measure48_vm as m

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")

LOW = "575.57.08"
CARD_NAME = "NVIDIA stand-in 192 GB"
PINNED = "vllm/vllm-openai:v0.32.0@sha256:0000"  # the rig's pinned_ref
WORDS = f"bench exception: driver {LOW} with the forward-compatibility path; not valid for an install"


def probe_doc(**change: Any) -> dict[str, Any]:
    """An engine probe result of the shape tools/engine_probe.py writes: the pinned form refused by the driver, the
    compatibility switch passed with the image's compatibility libraries seen inside."""
    doc: dict[str, Any] = {
        "schema": "tb-engine-probe/1",
        "at": "2026-11-22T05:00:00+00:00",
        "host": {"arch": "x86_64", "card": CARD_NAME, "driver": LOW, "compute_cap": "12.0"},
        "images": {"pinned": {"ref": PINNED, "verified_in_lock": True, "digest_matches": True}},
        "tests": [
            {"name": "pinned", "status": "DRIVER", "probe": None},
            {"name": "pinned+compat", "status": "PASS", "probe": {"compat_libs": ["libcuda.so.1"], "matmul": 262144.0}},
        ],
        "verdict": {"answer": "pass", "use": "pinned+compat", "image": "pinned", "pinned_engine": True,
                    "env": {"NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}},
    }  # fmt: skip
    for k, v in change.items():
        doc[k] = v
    return doc


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    r = Rig(tmp_path)
    r.smi(driver=LOW)
    return r


def _probe(rig: Rig, doc: dict[str, Any]) -> Path:
    p = rig.tmp / "tb-engine-probe.json"
    p.write_text(json.dumps(doc))
    return p


def _bench(rig: Rig, cmd: str, doc: dict[str, Any] | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    p = _probe(rig, doc or probe_doc())
    return rig.go(cmd, "--bench-driver-exception", "forward-compat", "--engine-probe", str(p), **env)


def test_the_run_goes_on_under_the_exception_and_says_so_in_every_record(rig: Rig) -> None:
    r = _bench(rig, "run")
    assert r.returncode == 0, r.stdout + r.stderr
    pre = (rig.out / "preflight.txt").read_text()
    assert f"NVIDIA driver {LOW} is below 580.65.06" in pre and WORDS in pre and "pinned+compat" in pre
    assert "caution: reported by the server's session" in pre and "a driver reload" in pre
    head = json.loads((rig.out / "records" / "head.json").read_text())
    assert head["bench_exception"] == WORDS and head["driver_found"] == LOW and head["driver_min"] == "580.65.06"
    assert head["engine_form"] == "pinned+compat"
    rec = json.loads((rig.out / "records" / "bench-exception.json").read_text())
    assert rec["valid_for_an_install"] is False and rec["words"] == WORDS
    mark = (rig.out / "BENCH-EXCEPTION.txt").read_text()
    assert WORDS in mark and "not a supported configuration" in mark and "580.65.06" in mark
    assert "UNDER THE BENCH EXCEPTION" in (rig.out / "host.log").read_text()
    measures = [c for c in rig.calls.read_text().splitlines() if c.startswith("ballast48 measure")]
    assert measures and all(f"--engine pinned+compat --probe {rig.tmp / 'tb-engine-probe.json'}" in c for c in measures)
    assert "NVIDIA_DISABLE_REQUIRE=1 VLLM_ENABLE_CUDA_COMPATIBILITY=1" in pre  # the probe's own environment, named
    rig.assert_nothing_forbidden_and_others_untouched()


def test_without_the_option_the_low_driver_is_refused_as_before(rig: Rig) -> None:
    r = rig.go("run", TB_BENCH_DRIVER_EXCEPTION="forward-compat", BENCH="forward-compat")  # no variable is read
    assert r.returncode == 2 and f"NVIDIA driver {LOW} is below 580.65.06" in r.stdout
    assert "this script never installs a driver" in r.stdout and "bench exception" not in r.stdout
    assert not rig.run_dir.exists()


@pytest.mark.parametrize(
    ("doc", "said"),
    [
        (probe_doc(host={"card": CARD_NAME, "driver": "570.86.10"}), "the probe ran on driver 570.86.10"),
        (probe_doc(host={"card": "NVIDIA other card", "driver": LOW}), "the probe ran on a NVIDIA other card"),
        (probe_doc(images={"pinned": {"ref": "vllm/vllm-openai:v0.31.0@sha256:1111"}}), "the lock's is " + PINNED),
        (
            probe_doc(verdict={"answer": "pass", "use": "cu129", "image": "cu129", "pinned_engine": False, "env": {}}),
            "did not pass with a forward-compatibility form",
        ),
        (
            probe_doc(verdict={"answer": "none", "use": None, "pinned_engine": False, "env": {}}),
            "its verdict is 'none'",
        ),
        (
            probe_doc(tests=[{"name": "pinned+compat", "status": "PASS", "probe": {"compat_libs": []}}]),
            "saw no compatibility library",
        ),
        ({"schema": "something-else"}, "is not an engine probe result"),
    ],
)
def test_the_exception_needs_a_probe_of_this_card_driver_and_image(rig: Rig, doc: dict[str, Any], said: str) -> None:
    r = _bench(rig, "run", doc)
    assert r.returncode == 2, r.stdout
    assert "the bench exception is not granted" in r.stdout and said in r.stdout, r.stdout
    assert not rig.run_dir.exists()
    rig.assert_nothing_forbidden_and_others_untouched()


def test_the_option_is_refused_where_no_exception_is_needed(rig: Rig) -> None:
    rig.smi(driver="590.44.01")
    r = _bench(rig, "preflight")
    assert r.returncode == 2 and "no exception is needed: run without it" in r.stdout


@pytest.mark.parametrize(
    ("more", "said"),
    [
        (("--bench-driver-exception", "forward-compat"), "needs --engine-probe FILE"),
        (("--engine-probe", "/nonexistent"), "read only with --bench-driver-exception forward-compat"),
        (("--bench-driver-exception", "any"), "the one kind is forward-compat"),
    ],
)
def test_the_options_usage(rig: Rig, more: tuple[str, ...], said: str) -> None:
    r = rig.go("preflight", *more)
    assert r.returncode == 2 and said in r.stderr


def test_the_helper_grants_only_below_the_minimum(tmp_path: Path) -> None:
    lock = ROOT / "deploy" / "images.lock"
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(probe_doc()))
    problems, rec = m.bench_exception(p, LOW, CARD_NAME, PINNED, lock)
    assert problems == [] and rec["words"] == WORDS and rec["engine_form"] == "pinned+compat"
    assert rec["engine_env"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] == "1"
    problems, _ = m.bench_exception(p, "580.65.06", CARD_NAME, PINNED, lock)
    assert problems and "no exception is needed" in problems[0]
    problems, _ = m.bench_exception(tmp_path / "missing.json", LOW, CARD_NAME, PINNED, lock)
    assert problems and "cannot be read" in problems[0]


# ------------------------------------------------------------------------------------------------ the install path


INSTALL_PATH = ("deploy/check_host.sh", "deploy/install.sh", "tools/images_lock.py")


# H-89 (the integrator's ruling, 2026-11-22 13:55 UTC): the one exception on the install path is the rehearsal with
# real servers, and it lives only inside its marked blocks; outside them nothing has changed
H89_BLOCK = re.compile(r"# rehearsal-real-servers \(h-89\).*?# ---- end of rehearsal-real-servers \(h-89\)", re.S)


@pytest.mark.parametrize("rel", INSTALL_PATH)
def test_the_install_path_has_no_bench_exception(rel: str) -> None:
    raw = (ROOT / rel).read_text(encoding="utf-8").lower()
    assert H89_BLOCK.search(raw), f"{rel}: the one rehearsal path (H-89) is named in its block"
    text = H89_BLOCK.sub("", raw)
    for name in ("rehearsal-real-servers", "rehearsal_real", "--engine-probe"):
        assert name not in text, f"{rel}: {name} outside the H-89 rehearsal blocks"
    for word in ("bench-driver-exception", "bench_driver_exception", "bench exception", "engine-probe",
                 "vllm_enable_cuda_compatibility=1", "nvidia_disable_require"):  # fmt: skip
        assert word not in text, f"{rel}: {word}"


def test_check_host_refuses_the_option_as_unknown() -> None:
    r = subprocess.run(["bash", str(ROOT / "deploy" / "check_host.sh"), "--bench-driver-exception", "forward-compat"],
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 2 and "unknown option --bench-driver-exception" in r.stderr


def test_the_lock_tool_refuses_the_option_and_a_low_driver_still_fails() -> None:
    base = [sys.executable, str(ROOT / "tools" / "images_lock.py"), "host", "--arch", "x86_64", "--driver", LOW]
    r = subprocess.run([*base, "--bench-driver-exception", "forward-compat"], capture_output=True, text=True,
                       timeout=60, check=False)  # fmt: skip
    assert r.returncode == 2 and "unrecognized arguments" in r.stderr
    r = subprocess.run(base, capture_output=True, text=True, timeout=60, check=False)
    assert f"FAIL  NVIDIA driver {LOW} is below 580.65.06" in r.stdout


# ------------------------------------------------------------------------------------------------ s08's server environment


def _engine_and_override(tmp: Path, probe: Path | None, forced: str) -> tuple[dict[str, Any], str]:
    from tools import dgpu48

    doc = json.loads(probe.read_text()) if probe else None
    engine = dgpu48.engine_from_probe(doc, forced)
    return engine, dgpu48.run_override(engine, tmp).read_text()


def test_ballast48_hands_lane_js_measure_the_probe_only_under_the_exception(tmp_path: Path) -> None:
    from tests.unit.test_ballast48_h47 import Card
    from tools import ballast48 as b48

    got: list[tuple[Any, Any]] = []

    def spy(run: Any, oid: str, out: Path, probe: Any, engine: str, *a: Any, **k: Any) -> dict[str, Any]:
        got.append((probe, engine))
        return {"option": oid, "started": True, "outcome": "STARTED"}

    b48.measure(Card(), "pair-32k", tmp_path, "pinned", False, False, measure_fn=spy, say=lambda _: None)
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(probe_doc()))
    b48.measure(Card(), "pair-32k", tmp_path, "pinned+compat", False, False, measure_fn=spy, say=lambda _: None,
                probe=p)  # fmt: skip
    assert got == [(None, "pinned"), (p, "")]  # without: forced by name, as before; with: the probe's verdict
    with pytest.raises(b48.Refused, match="passed with 'pinned\\+compat', not --engine 'pinned\\+libs'"):
        b48.measure(Card(), "pair-32k", tmp_path, "pinned+libs", False, False, measure_fn=spy, probe=p)


def test_the_servers_take_the_probes_environment_only_under_the_exception(tmp_path: Path) -> None:
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(probe_doc()))
    engine, text = _engine_and_override(tmp_path, p, "")
    assert engine["use"] == "pinned+compat" and engine["from_probe"] is True
    assert engine["env"] == {"NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}
    assert "NVIDIA_DISABLE_REQUIRE: '1'" in text  # in the containers' environment (the toolkit reads it there)
    # without the exception: the forms forced by name, the run file exactly as before this card
    engine, text = _engine_and_override(tmp_path, None, "pinned")
    assert engine["env"] == {} and engine["from_probe"] is False
    assert text == ("# written by tools/dgpu48.py for one measuring run\nservices:\n  llm-service:\n    restart: 'no'\n"
                    "  llm-verifier:\n    restart: 'no'\n")  # fmt: skip
    engine, text = _engine_and_override(tmp_path, None, "pinned+compat")
    assert engine["env"] == {"VLLM_ENABLE_CUDA_COMPATIBILITY": "1"} and "NVIDIA_DISABLE_REQUIRE" not in text
