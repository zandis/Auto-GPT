"""H-112 (the owner's go, #639 7121371183): the second serving profile behind a switch, and the engine comparison
harness, proved with stand-ins (no engine, no GPU, no model).

* The switch off changes nothing: the file list is the box's own, and ``docker compose config`` renders the same
  bytes as compose reading the box's ``COMPOSE_FILE`` itself, for every GPU stack.
* The switch on selects the second profile, and only on a TEST or VALIDATION box with a filled settings file and a
  GPU overlay; it changes nothing but what runs inside llm-service and llm-verifier. A caller's variable decides
  nothing. A PRODUCTION box is refused, and doctor FAILs the profile's file there.
* The harness's numbers on fixed rows are exact; repeat agreement counts the differing (patient, criterion) answers
  by tools.run_metrics.lists_compare's rule; through two local stand-in engines, the counts and the card's memory peak
  are exact and nothing but counts and times is written or printed.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.test_compose_limits import BASE, DEPLOY, DUMMY_ENV, STACKS, _compose, _merge
from tools import engine_compare as ec
from tools import images_lock as il
from tools import judge_bakeoff as jb
from tools import serving_profile as sp
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb

OVERLAY = sp.OVERLAY
GPU_STACKS = [
    s for s, p in STACKS if "gpu" in p and OVERLAY not in s and any("llm-verifier" in _merge((f,)) for f in s)
]
FILLED = {
    "SERVING2_IMAGE": "registry.invalid/engine@sha256:" + "ab" * 32,
    "SERVING2_SERVER": "engine-server",
    "SERVING2_JUDGE_DIR": "cand-a-judge",
    "SERVING2_JUDGE_NAME": "local/cand-a-judge",
    "SERVING2_JUDGE_CONFIG": "cand-a-judge.yaml",
    "SERVING2_VERIFIER_DIR": "cand-a-verifier",
    "SERVING2_VERIFIER_NAME": "local/cand-a-verifier",
    "SERVING2_VERIFIER_CONFIG": "cand-a-verifier.yaml",
}
ON = {**FILLED, "SERVING_ENGINE": "second"}
IMAGE = {"current": "sha256:" + "c1" * 32, "second": "sha256:" + "c2" * 32}


# ------------------------------------------------------------------------------------------------ a box's folder
def _box(tmp: Path, stack: tuple[str, ...], extra: str = "", settings: dict[str, str] | None = None) -> Path:
    """A deploy folder of a box: its .env names the stack's real compose files (absolute, as install.sh writes)."""
    d = tmp / "deploy"
    d.mkdir(parents=True, exist_ok=True)
    (d / sp.EXAMPLE).write_text((DEPLOY / sp.EXAMPLE).read_text(encoding="utf-8"), encoding="utf-8")
    files = ":".join(str(DEPLOY / f) for f in stack)
    (d / ".env").write_text(DUMMY_ENV + f"COMPOSE_FILE={files}\n" + extra, encoding="utf-8")
    if settings is not None:
        (d / "site").mkdir(exist_ok=True)
        p = d / sp.SETTINGS
        p.write_text("".join(f"{k}={v}\n" for k, v in settings.items()), encoding="utf-8")
        p.chmod(0o600)
    return d


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "TB_MEM_", "SERVING"))}


def _render(deploy: Path, files: list[str] | None, profiles: tuple[str, ...] = ("gpu",),
            env_files: tuple[Path, ...] = ()) -> bytes:  # fmt: skip
    """``docker compose config`` bytes: with ``files`` None, compose reads COMPOSE_FILE from the box's .env itself
    (today's way, no switch in the path)."""
    argv = ["docker", "compose", "--project-directory", str(deploy)]
    for e in env_files:
        argv += ["--env-file", str(e)]
    for f in files or []:
        argv += ["-f", str(f)]
    argv += [x for p in profiles for x in ("--profile", p)] + ["config"]
    r = subprocess.run(argv, capture_output=True, timeout=120, check=False, env=_clean_env())
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout


# ------------------------------------------------------------------------------------------ the switch off: nothing
@pytest.mark.parametrize("value", [None, "current", "", '"Current"'])
@pytest.mark.parametrize("stack", [(BASE,), *GPU_STACKS], ids="+".join)
def test_the_switch_off_gives_the_box_its_own_file_list(
    tmp_path: Path, stack: tuple[str, ...], value: str | None
) -> None:
    settings = FILLED if value is None else {**FILLED, "SERVING_ENGINE": value}
    deploy = _box(tmp_path, stack, "TB_ENV=TEST\n", settings=settings)  # a filled file changes nothing while off
    assert sp.files(deploy) == [str(DEPLOY / f) for f in stack]
    argv = sp.compose_argv(deploy)
    assert str(deploy / sp.SETTINGS) not in argv and str(DEPLOY / OVERLAY) not in argv


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
@pytest.mark.parametrize("stack", GPU_STACKS, ids="+".join)
def test_the_switch_off_renders_the_same_bytes_as_compose_reading_the_box(
    tmp_path: Path, stack: tuple[str, ...]
) -> None:
    """The invariant: with the switch off (absent, or `current`), what the switch gives renders byte for byte what
    compose renders from the box's own COMPOSE_FILE, with no part of this card in the path."""
    deploy = _box(tmp_path, stack)  # no settings file: the box as every box is
    today = _render(deploy, None, ("gpu", "doctor"))
    assert b"serving2" not in today and b"SERVING" not in today
    assert _render(deploy, sp.files(deploy), ("gpu", "doctor")) == today
    _box(tmp_path, stack, settings={**FILLED, "SERVING_ENGINE": "current"})  # the bench host's file, switch off
    assert _render(deploy, sp.files(deploy), ("gpu", "doctor")) == today
    assert _render(deploy, None, ("gpu", "doctor")) == today  # the box's own files never read the settings file
    argv = sp.compose_argv(deploy)
    r = subprocess.run([*argv, "--profile", "gpu", "--profile", "doctor", "config"], capture_output=True, timeout=120,
                       check=False, env=_clean_env())  # fmt: skip
    assert r.returncode == 0 and r.stdout == today


def test_a_callers_variable_decides_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=FILLED)
    monkeypatch.setenv("SERVING_ENGINE", "second")
    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.setenv("COMPOSE_FILE", str(DEPLOY / OVERLAY))
    assert sp.files(deploy) == [str(DEPLOY / f) for f in GPU_STACKS[0]]  # off: the files say nothing of it
    deploy = _box(tmp_path / "p", GPU_STACKS[0], settings={**FILLED, "SERVING_ENGINE": "second"})
    with pytest.raises(sp.Refused, match="PRODUCTION box"):  # the box's .env has no TB_ENV: PRODUCTION
        sp.files(deploy)
    assert sp.clean_environ({"SERVING2_IMAGE": "x", "SERVING_ENGINE": "second", "COMPOSE_FILE": "y", "PATH": "/b"}) == {
        "PATH": "/b"
    }


# --------------------------------------------------------------------------------------- the switch on: the profile
@pytest.mark.parametrize("box", ["TEST", "VALIDATION", "test"])
def test_the_switch_on_adds_the_second_profile_last(tmp_path: Path, box: str) -> None:
    stack = GPU_STACKS[0]
    deploy = _box(tmp_path, stack, f"TB_ENV={box}\n", settings=ON)
    assert sp.files(deploy) == [*(str(DEPLOY / f) for f in stack), str(deploy / OVERLAY)]
    argv = sp.compose_argv(deploy)
    assert argv[argv.index(str(deploy / sp.SETTINGS)) - 1] == "--env-file"


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
@pytest.mark.parametrize("stack", GPU_STACKS, ids="+".join)
def test_the_switch_on_renders_the_second_engine_in_the_two_servers_only(
    tmp_path: Path, stack: tuple[str, ...]
) -> None:
    deploy = _box(tmp_path, stack, "TB_ENV=TEST\n", settings=FILLED)
    off = yaml.safe_load(_render(deploy, sp.files(deploy), ("gpu", "doctor")))["services"]
    _box(tmp_path, stack, "TB_ENV=TEST\n", settings=ON)
    # the overlay sits beside the real files: compose reads it from the repository's deploy/
    listed = [f if Path(f).name != OVERLAY else str(DEPLOY / OVERLAY) for f in sp.files(deploy)]
    on = yaml.safe_load(_render(deploy, listed, ("gpu", "doctor"), (deploy / ".env", deploy / sp.SETTINGS)))["services"]
    assert set(on) == set(off)
    for svc in set(on) - set(sp.SERVICES):
        assert on[svc] == off[svc], svc  # model-guard, the gateway and every other service: unchanged
    for svc, who in (("llm-service", "JUDGE"), ("llm-verifier", "VERIFIER")):
        body = on[svc]
        assert body["image"] == FILLED["SERVING2_IMAGE"] and body["pull_policy"] == "never"
        assert body["entrypoint"] == [FILLED["SERVING2_SERVER"]]
        assert body["command"][:2] == ["serve", f"/models/{FILLED[f'SERVING2_{who}_DIR']}"]
        assert f"--served_model_name={FILLED[f'SERVING2_{who}_NAME']}" in body["command"]
        assert "--port=8000" in body["command"] and "--log_level=warning" in body["command"]
        # the card, the caps, the networks, the controls and the health check stay the GPU overlay's
        for key in ("deploy", "mem_limit", "pids_limit", "networks", "security_opt", "healthcheck", "volumes",
                    "labels", "restart", "logging"):  # fmt: skip
            assert body.get(key) == off[svc].get(key), (svc, key)


def test_the_profile_file_changes_only_what_runs_and_is_never_pulled() -> None:
    text = (DEPLOY / OVERLAY).read_text(encoding="utf-8")
    assert sp.MARK in text.splitlines() and doctor.BENCH_SERVING_MARK == sp.MARK
    doc = yaml.safe_load(text)
    assert set(doc["services"]) == set(sp.SERVICES)
    for body in doc["services"].values():
        assert set(body) == {"image", "pull_policy", "entrypoint", "command", "environment"}
        assert body["pull_policy"] == "never"
        assert body["image"] == "${SERVING2_IMAGE:-serving2-unset@sha256:" + "0" * 64 + "}"  # by digest, no tag
    # the bench image is named nowhere else: no other compose file can run the second engine
    others = [p for p in DEPLOY.rglob("docker-compose*.yml") if p.name != OVERLAY]
    assert all("SERVING2_" not in p.read_text(encoding="utf-8") for p in others)
    # every key the overlay interpolates is a key of the example the switch requires
    keys = set(sp.required_keys(DEPLOY))
    used = set(re.findall(r"\$\{(SERVING2_[A-Z_]+)", text))
    assert used <= keys and "SERVING2_IMAGE" in keys
    example = (DEPLOY / sp.EXAMPLE).read_text(encoding="utf-8")
    example_values = sp.env_file(DEPLOY / sp.EXAMPLE)
    assert example_values.pop(sp.SWITCH) == "current"  # the committed example leaves the box as it is
    assert all(v.startswith("<") for v in example_values.values())
    assert "@sha256:<digest>" in example


@pytest.mark.parametrize(
    ("extra", "settings", "why"),
    [
        ("", ON, "PRODUCTION box"),
        ("TB_ENV=PRODUCTION\n", ON, "PRODUCTION box"),
        ("TB_ENV=DEV\n", ON, "DEV box"),
        ("TB_ENV=TEST\n", {**ON, "SERVING2_JUDGE_NAME": "<served name>"}, "SERVING2_JUDGE_NAME is not filled"),
        ("TB_ENV=TEST\n", {k: v for k, v in ON.items() if k != "SERVING2_SERVER"}, "SERVING2_SERVER is not filled"),
        ("TB_ENV=TEST\n", {**ON, "SERVING2_IMAGE": "registry.invalid/engine:1.0"}, "not pinned by digest"),
        ("TB_ENV=TEST\n", {**ON, "SERVING2_IMAGE": "registry.invalid/engine:1.0@sha256:" + "ab" * 32},
         "never a tag"),
        ("TB_ENV=TEST\n", {**ON, "SERVING2_IMAGE": "registry.invalid/engine@sha256:abc"}, "not pinned by digest"),
        ("TB_ENV=TEST\n", {**FILLED, "SERVING_ENGINE": "yes"}, "not one of current, second"),
        ("TB_ENV=TEST\nSERVING_ENGINE=second\n", FILLED, None),  # the switch in deploy/.env is not the switch
    ],
)  # fmt: skip
def test_the_switch_on_is_refused_with_its_reason(
    tmp_path: Path, extra: str, settings: dict[str, str] | None, why: str | None
) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], extra, settings=settings)
    if why is None:
        assert sp.files(deploy) == [str(DEPLOY / f) for f in GPU_STACKS[0]]
        return
    with pytest.raises(sp.Refused, match=why):
        sp.files(deploy)
    assert sp.main(["files", "--deploy", str(deploy)]) == 1


def test_the_switch_on_is_refused_without_a_gpu_overlay_or_with_a_loose_settings_file(tmp_path: Path) -> None:
    deploy = _box(tmp_path / "a", (BASE,), "TB_ENV=TEST\n", settings=ON)
    with pytest.raises(sp.Refused, match="define no llm-verifier"):
        sp.files(deploy)
    deploy = _box(tmp_path / "b", GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    (deploy / sp.SETTINGS).chmod(0o666)
    with pytest.raises(sp.Refused, match="writable by group or others"):
        sp.files(deploy)
    deploy = _box(tmp_path / "c", (*GPU_STACKS[0], OVERLAY), "TB_ENV=TEST\n", settings=ON)
    with pytest.raises(sp.Refused, match="already names"):
        sp.files(deploy)


def test_check_image_checks_the_pinned_digest_and_never_tags_or_pulls(tmp_path: Path) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    ref = FILLED["SERVING2_IMAGE"]
    digest = ref.rsplit("@", 1)[1]
    calls: list[list[str]] = []

    def runner(found: list[str], rc: int = 0) -> Any:
        def run(argv: Any) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            return subprocess.CompletedProcess(list(argv), rc, json.dumps(found), "")

        return run

    assert sp.check_image(deploy, runner([f"registry.invalid/engine@{digest}"])) == digest
    assert calls == [["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", ref]]
    with pytest.raises(sp.Refused, match="not the pinned one"):
        sp.check_image(deploy, runner(["registry.invalid/engine@sha256:" + "cd" * 32]))
    with pytest.raises(sp.Refused, match="not on this host"):
        sp.check_image(deploy, runner([], rc=1))
    assert all(c[:3] == ["docker", "image", "inspect"] for c in calls)  # no tag, no pull, ever


def test_the_image_a_run_records_is_the_switchs_digest(tmp_path: Path) -> None:
    lock = json.loads((DEPLOY / "images.lock").read_text(encoding="utf-8"))
    engine = next(e for e in lock["third_party"].values() if e.get("gpu"))
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n")
    (deploy / "images.lock").write_text(json.dumps(lock), encoding="utf-8")
    engine_vars = tuple(f"{v}=" for v in engine["variables"])
    own = [ln for ln in (deploy / ".env").read_text(encoding="utf-8").splitlines() if not ln.startswith(engine_vars)]
    (deploy / ".env").write_text("\n".join(own) + "\n", encoding="utf-8")
    assert sp.image(deploy) == engine["digest"]  # off, the box sets none: the lock's pin of the current engine
    (deploy / ".env").write_text("\n".join(own) + f"\n{engine['variables'][0]}=engine:1.0\n", encoding="utf-8")
    with pytest.raises(sp.Refused, match="not pinned by digest"):
        sp.image(deploy)  # a tag the box set is never recorded as what ran
    other = "sha256:" + "ef" * 32
    _box(tmp_path, GPU_STACKS[0], f"TB_ENV=TEST\n{engine['variables'][0]}=mirror.invalid/x@{other}\n")
    assert sp.image(deploy) == other  # the box's own setting of the current engine's image
    _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    assert sp.image(deploy) == FILLED["SERVING2_IMAGE"].rsplit("@", 1)[1]
    _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings={**ON, "SERVING2_IMAGE": "registry.invalid/engine:1.0"})
    with pytest.raises(sp.Refused, match="not pinned by digest"):
        sp.image(deploy)


# ------------------------------------------------------------------------- nothing bench-only reaches a bundle
def test_the_lock_refuses_the_bench_image_and_only_the_bench_file_names_it(tmp_path: Path) -> None:
    """The rulings on #1459 (7122790579): the bench image is never in deploy/images.lock (whose gpu entries are the
    engine images make_bundle puts in the model pack, and whose entries are the only third-party images a box's
    compose files may name), only the bench-marked file names it, by digest only; the bench settings file is site
    state, never in a release's host tree."""
    lock = il.load()
    assert il.lock_problems(lock) == []
    assert not {v for e in lock["third_party"].values() for v in e.get("variables") or []} & il.BENCH_VARS
    planted = json.loads(json.dumps(lock))
    planted["third_party"]["bench"] = {**lock["third_party"]["hapi"], "variables": ["SERVING2_IMAGE"]}
    assert [p for p in il.lock_problems(planted) if "bench-only" in p] == [
        "bench: SERVING2_IMAGE is the bench-only second serving profile's image (H-112): never in the lock"
    ]
    real = DEPLOY / OVERLAY
    assert il.check_compose(lock, [real]) == ([], set())
    text = real.read_text(encoding="utf-8")
    unmarked = tmp_path / "docker-compose.x.yml"
    unmarked.write_text(text.replace(sp.MARK, "x-other: true"), encoding="utf-8")
    assert any("only the file marked" in p for p in il.check_compose(lock, [unmarked])[0])
    for bad in ("registry.invalid/engine:1.0", "registry.invalid/engine:1.0@sha256:" + "ab" * 32):
        tagged = tmp_path / "docker-compose.y.yml"
        tagged.write_text(text.replace("serving2-unset@sha256:" + "0" * 64, bad), encoding="utf-8")
        problems = il.check_compose(lock, [tagged])[0]
        assert len(problems) == 2 and all("never by a tag" in p for p in problems), bad
    from tools import host_tree

    assert host_tree.is_state("deploy/site/serving-second.env")
    assert not host_tree.is_state(f"deploy/{OVERLAY}")  # the overlay rides, its image is a placeholder digest


# ------------------------------------------------------------------------------------------ doctor: never PRODUCTION
@pytest.mark.parametrize(("env", "status"), [({}, "FAIL"), ({"TB_ENV": "PRODUCTION"}, "FAIL"),
                                             ({"TB_ENV": "TEST"}, "WARN"), ({"TB_ENV": "VALIDATION"}, "WARN")])  # fmt: skip
def test_doctor_fails_the_profile_on_a_production_box(tmp_path: Path, env: dict[str, str], status: str) -> None:
    files = ":".join([str(DEPLOY / f) for f in GPU_STACKS[0]] + [str(DEPLOY / OVERLAY)])
    c = doctor.check_bench_serving(doctor.DoctorInputs(env={**env, "COMPOSE_FILE": files}, deploy=DEPLOY))
    assert c.status == status
    plain = ":".join(str(DEPLOY / f) for f in GPU_STACKS[0])
    assert doctor.check_bench_serving(
        doctor.DoctorInputs(env={**env, "COMPOSE_FILE": plain}, deploy=DEPLOY)
    ).status == ("PASS")
    assert doctor.check_bench_serving in doctor.CHECKS


# ----------------------------------------------------------------------------------------- the harness: exact numbers
def _row(pid: str, crit: str, answer: str, latency: float, attempts: int = 1, out: int = 10, err: str = "") -> jb.Row:
    return jb.Row(id=f"synthetic:{pid}:{crit}", source="synthetic", cluster=pid, pair="", kind="exclusion",
                  gold="unknown", gated=True, predicate=answer, latency_s=latency, attempts=attempts, tokens_out=out,
                  error=err)  # fmt: skip


def test_the_numbers_on_fixed_rows_are_exact() -> None:
    r1 = [_row("s:1", "C1", "pass", 1.0), _row("s:1", "C2", "fail", 2.0), _row("s:2", "C1", "unknown", 4.0),
          _row("s:3", "C1", "unknown", 0.0, attempts=0, out=0)]  # s:3 had no note: no model asked  # fmt: skip
    r2 = [_row("s:1", "C1", "pass", 1.5), _row("s:1", "C2", "pass", 2.5), _row("s:2", "C1", "unknown", 5.0),
          _row("s:3", "C1", "unknown", 0.0, attempts=0, out=0)]  # fmt: skip
    r3 = [_row("s:1", "C1", "pass", 2.0), _row("s:1", "C2", "fail", 3.0),
          _row("s:2", "C1", "unknown", 6.0, err="no_answer"), _row("s:3", "C1", "unknown", 0.0, attempts=0, out=0)]  # fmt: skip
    assert ec.chart_times(r1) == [3.0, 4.0]
    s = ec.summarize([r1, r2, r3], [10.0, 20.0, 30.0], {"engine": "second", "candidate": "A", "quant": "q4",
                                                         "set_sha256": "f" * 64}, {"memory_peak_mib": 81234.0,
                                                                                   "samples": 7})  # fmt: skip
    # chart times pooled: 3, 4, 4, 5, 5, 6 -> p50 4.5, p95 5.75 (linear interpolation, run_metrics.percentile)
    assert (s["chart_p50_s"], s["chart_p95_s"], s["charts_timed"]) == (4.5, 5.75, 6)
    assert (s["charts"], s["items"], s["repeats"], s["wall_s"]) == (3, 4, 3, 60.0)
    assert s["charts_per_hour"] == 540.0  # 3 charts x 3 repeats / 60 s
    assert s["gen_tokens_per_s"] == 1.5  # 9 calls x 10 tokens / 60 s
    assert s["gpu_memory_peak_mib"] == 81234.0
    # (s:1, C2) pass in r2 only; (s:2, C1) no answer in r3: two pairs over two patients; no pair unanswered thrice
    assert (s["pairs"], s["pairs_differ"], s["patients_differ"], s["no_answer"]) == (4, 2, 2, 0)
    # E2-9's form: each later run against run 1
    assert s["from_run_1"] == [{"run": 2, "pairs": 1, "by_criterion": {"C2": 1}},
                               {"run": 3, "pairs": 1, "by_criterion": {"C1": 1}}]  # fmt: skip
    r4 = [_row("s:1", "C1", "fail", 1), _row("s:1", "C2", "pass", 1), _row("s:2", "C1", "pass", 1), r1[3]]
    assert ec.from_run_1([r1, r4]) == [{"run": 2, "pairs": 3, "by_criterion": {"C1": 2, "C2": 1}}]
    line = ec.render_table([{**s, "from_run_1": ec.from_run_1([r1, r4, r1])}]).splitlines()[-1]
    assert line == "- second A q4: run 2 3 (2 on C1, 1 on C2); run 3 0."


def test_repeat_agreement_is_lists_compare_s_rule() -> None:
    """A pair missing from a repeat differs (lists_compare's '-'); the same answers in every repeat do not; the
    order of the rows and of the repeats does not matter."""
    a = [_row("p:1", "X", "pass", 1), _row("p:2", "X", "fail", 1), _row("p:2", "Y", "unknown", 1)]
    b = [_row("p:2", "Y", "unknown", 1), _row("p:1", "X", "pass", 1)]  # (p:2, X) missing
    c = [_row("p:2", "X", "fail", 1), _row("p:1", "X", "pass", 1), _row("p:2", "Y", "unknown", 1)]
    assert ec.differ([a, a, a]) == {"pairs": 3, "pairs_differ": 0, "patients_differ": 0}
    assert ec.differ([a, b, c]) == {"pairs": 3, "pairs_differ": 1, "patients_differ": 1}
    assert ec.differ([c, b, a]) == ec.differ([a, b, c])
    flip = [_row("p:1", "X", "fail", 1), _row("p:2", "X", "pass", 1), _row("p:2", "Y", "unknown", 1)]
    assert ec.differ([a, flip, a]) == {"pairs": 3, "pairs_differ": 2, "patients_differ": 2}
    both = [_row("p:1", "X", "pass", 1), _row("p:2", "X", "pass", 1), _row("p:2", "Y", "fail", 1)]
    assert ec.differ([a, both, a]) == {"pairs": 3, "pairs_differ": 2, "patients_differ": 1}  # two pairs, one patient
    with pytest.raises(ValueError):
        ec.differ([a])


# --------------------------------------------------------------------------- two stand-in engines, end to end
def _items() -> list[jb.Item]:
    """Every item of the first patients of the synthetic set that have two or more criteria, and some singles."""
    items = jb.synthetic_items()
    by: dict[str, list[jb.Item]] = {}
    for it in items:
        by.setdefault(it.cluster, []).append(it)
    multi = [c for c, its in by.items() if len(its) > 1][:6]
    single = [c for c, its in by.items() if len(its) == 1][:10]
    return [it for c in multi + single for it in by[c]]


def _fake_card_monitor(tmp: Path, peaks: list[int]) -> list[str]:
    """A stand-in for the card's monitor command: each call prints the next memory.used of ``peaks`` (the last one again after)."""
    state, script = tmp / "calls", tmp / "monitor.py"
    tmp.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"p = Path({str(state)!r}); n = int(p.read_text()) if p.exists() else 0; p.write_text(str(n + 1))\n"
        f"v = {peaks!r}[min(n, {len(peaks) - 1})]\n"
        "print(f'2026/11/24 10:00:{n % 60:02d}.000, 50, {v}, 97887, 40, 300.5')\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_two_stand_in_engines_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    items = _items()
    sha = jb.set_sha(items)
    patients = {it.cluster for it in items}
    asked = [it for it in items if it.excerpts]
    flip_crit = asked[0].id.removeprefix(f"synthetic:{asked[0].cluster}:")
    flip_key = asked[0].criterion_text, asked[0].excerpts[0]["text"]  # the second engine wavers on this one pair
    calls = {"n": 0}

    def wavering(inp: dict[str, Any]) -> dict[str, Any]:
        a = jb.stub_answer(inp)
        if (inp["criterion_text"], inp["excerpts"][0]["text"]) == flip_key:
            calls["n"] += 1
            if calls["n"] == 2:  # its second repeat only
                return {**a, "verdict": "unknown", "quote": "", "quote_date": ""}
        return a

    outs = {}
    # the monitor is asked at least twice (at the start and at the stop): the peak is the second answer, kept after
    for engine, answer, peaks in (("current", jb.stub_answer, [1000, 41000]), ("second", wavering, [900, 39000])):
        with jb.stub_server(answer=answer) as url:
            outs[engine] = tmp_path / engine
            s = ec.run(url, jb.STUB_NAME, items, {"engine": engine, "candidate": "A", "quant": "q4",
                                                  "set_sha256": sha, "image": IMAGE[engine]}, outs[engine], repeats=3, workers=4,
                       sample_every=0.05, gpu_cmd=_fake_card_monitor(tmp_path / f"monitor-{engine}", peaks))  # fmt: skip
        assert (s["charts"], s["items"], s["repeats"]) == (len(patients), len(items), 3)
        assert s["charts_timed"] == 3 * len({it.cluster for it in asked})
        assert s["pairs"] == len(items) and s["no_answer"] == 0
        assert s["gpu_memory_peak_mib"] == max(peaks)
        assert 0 < s["chart_p50_s"] <= s["chart_p95_s"] and s["charts_per_hour"] > 0
    first = json.loads((outs["current"] / ec.SUMMARY).read_text(encoding="utf-8"))
    second = json.loads((outs["second"] / ec.SUMMARY).read_text(encoding="utf-8"))
    assert (first["pairs_differ"], first["patients_differ"]) == (0, 0)
    assert (second["pairs_differ"], second["patients_differ"]) == (1, 1)
    assert [x["pairs"] for x in first["from_run_1"]] == [0, 0]
    assert second["from_run_1"] == [{"run": 2, "pairs": 1, "by_criterion": {flip_crit: 1}},
                                    {"run": 3, "pairs": 0, "by_criterion": {}}]  # fmt: skip
    assert (first["image"], second["image"]) == (IMAGE["current"], IMAGE["second"])
    assert ec.main(["table", str(outs["current"]), str(outs["second"]), "--out", str(tmp_path / "table.md")]) == 0
    table = (tmp_path / "table.md").read_text(encoding="utf-8")
    assert table.count("\n| current | A | q4 |") == 1 and table.count("\n| second | A | q4 |") == 1
    assert f"One chart set for every row (sha256 {sha[:12]})" in table
    assert "differences from run 1 in (patient, criterion) answers" in table
    assert "- current A q4: run 2 0; run 3 0." in table
    assert f"- second A q4: run 2 1 (1 on {flip_crit}); run 3 0." in table
    assert IMAGE["second"] in table
    # nothing but counts and times: no id, no criterion, no excerpt or quote text in any file or on the console
    printed = capsys.readouterr()
    written = [p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file() and p.suffix != ".py"]
    texts = [*written, printed.out, printed.err]
    secrets = {it.cluster.split(":", 1)[1] for it in items} | {it.criterion_text for it in items}
    secrets |= {e["text"][:20] for it in items for e in it.excerpts} | {it.id for it in items}
    for t in texts:
        assert not [x for x in secrets if x and x in t]
    assert set(first) == {"engine", "candidate", "quant", "charts", "items", "repeats", "charts_timed", "chart_p50_s",
                          "chart_p95_s", "wall_s", "charts_per_hour", "gen_tokens_per_s", "gpu_memory_peak_mib",
                          "gpu_samples", "pairs", "pairs_differ", "patients_differ", "no_answer", "set_sha256",
                          "from_run_1", "image"}  # fmt: skip
    files = sorted(p.relative_to(outs["second"]).as_posix() for p in outs["second"].rglob("*") if p.is_file())
    assert files == ["card/gpu.csv", "summary.json"]


def test_the_table_says_when_the_rows_are_not_comparable() -> None:
    a = {"engine": "current", "candidate": "A", "quant": "q4", "set_sha256": "a" * 64, "gpu_memory_peak_mib": None}
    b = {**a, "engine": "second", "set_sha256": "b" * 64}
    t = ec.render_table([a, b])
    assert "NOT COMPARABLE" in t and "not measured" in t


@pytest.mark.parametrize(("flag", "value"), [("--engine", "third"), ("--candidate", "E"), ("--quant", "a b/c"),
                                           ("--image-digest", "engine:1.0"), ("--image-digest", "sha256:abc")])  # fmt: skip
def test_labels_only_never_a_model_name_and_the_image_by_digest(
    tmp_path: Path, flag: str, value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["run", "--engine", "current", "--candidate", "A", "--quant", "q4", "--image-digest", IMAGE["current"],
            "--base-url", "http://127.0.0.1:9/v1", "--served-name", "x", "--set", str(tmp_path / "s.jsonl"),
            "--expect-set-sha", "0", "--out", str(tmp_path / "o")]  # fmt: skip
    argv[argv.index(flag) + 1] = value
    if flag == "--image-digest":
        assert ec.main(argv) == 2  # refused before the set is read or anything is sent
        assert "--image-digest is sha256:<64 hex>, never a tag" in capsys.readouterr().err
        assert not (tmp_path / "o").exists()
        return
    with pytest.raises(SystemExit):
        ec.main(argv)


def test_the_committed_files_hold_placeholders_only_and_are_not_writable_by_others() -> None:
    """The committed example holds placeholders only, and no file of this card is group or world writable."""
    for p in (DEPLOY / sp.EXAMPLE, DEPLOY / OVERLAY):
        assert not p.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    values = {k: v for k, v in sp.env_file(DEPLOY / sp.EXAMPLE).items() if k != sp.SWITCH}
    assert all("<" in v for v in values.values())
