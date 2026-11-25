"""H-112 (the owner's go, #639 7121371183): the second serving profile behind a switch, and the engine comparison
harness, proved with stand-ins (no engine, no GPU, no model).

* The switch off changes nothing: the file list is the box's own, and ``docker compose config`` renders the same
  bytes as compose reading the box's ``COMPOSE_FILE`` itself, for every GPU stack.
* The switch on selects the second profile, and only on a TEST box with a filled settings file and a
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

from tests.unit.test_compose_limits import BASE, DEPLOY, DUMMY_ENV, STACKS, _compose, _load, _merge
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
# the judge's pinned chat template every GPU overlay names (read from the file: no name is written here)
_T = sp.CURRENT_TEMPLATE.search((DEPLOY / "docker-compose.gb10.yml").read_text(encoding="utf-8"))
assert _T is not None
CURRENT_T = _T.group(1)
FILLED = {
    "SERVING2_IMAGE": "registry.invalid/engine@sha256:" + "ab" * 32,
    "SERVING2_JUDGE_CHAT_TEMPLATE": CURRENT_T,
    "SERVING2_VERIFIER_CHAT_TEMPLATE": "templates/cand-a-verifier-no-thinking.jinja",
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
    d.chmod(0o755)  # H-139 (item 5, ruled b): explicit modes, never the run's umask
    (d / sp.EXAMPLE).write_text((DEPLOY / sp.EXAMPLE).read_text(encoding="utf-8"), encoding="utf-8")
    files = ":".join(str(DEPLOY / f) for f in stack)
    (d / ".env").write_text(DUMMY_ENV + f"COMPOSE_FILE={files}\n" + extra, encoding="utf-8")
    if settings is not None:
        (d / "site").mkdir(exist_ok=True)
        (d / "site").chmod(0o755)  # H-139 (item 5, ruled b)
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
@pytest.mark.parametrize("box", ["TEST", "test"])
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
        # OCR 1459-4: the chat template; 1459-5: the model servers' key file is not handed to the second engine
        assert f"--chat_template=/models/{FILLED[f'SERVING2_{who}_CHAT_TEMPLATE']}" in body["command"]
        assert not body.get("env_file"), svc  # the overlay resets it (the test box has no key file to render)
        # the card, the caps, the networks, the controls and the health check stay the GPU overlay's
        for key in ("deploy", "mem_limit", "pids_limit", "networks", "security_opt", "healthcheck", "volumes",
                    "labels", "restart", "logging"):  # fmt: skip
            assert body.get(key) == off[svc].get(key), (svc, key)


def test_the_profile_file_changes_only_what_runs_and_is_never_pulled() -> None:
    text = (DEPLOY / OVERLAY).read_text(encoding="utf-8")
    assert sp.MARK in text.splitlines() and doctor.BENCH_SERVING_MARK == sp.MARK
    doc = _load(OVERLAY)  # compose's !reset read as plain YAML (test_compose_limits's loader)
    assert "env_file: !reset []" in text
    assert set(doc["services"]) == set(sp.SERVICES)
    for body in doc["services"].values():
        assert set(body) == {"image", "pull_policy", "entrypoint", "command", "environment", "env_file"}
        assert body["env_file"] == []  # !reset: the current engine's key file is not this engine's
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
        ("TB_ENV=VALIDATION\n", ON, "VALIDATION box"),  # OCR 1459-5: no key check of its own
        ("TB_ENV=TEST\n", {**ON, "SERVING2_JUDGE_CHAT_TEMPLATE": "templates/other.jinja"}, "chat template"),
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
    for mode in (0o666, 0o640, 0o604):  # OCR 1459-8: a readable copy refused too
        (deploy / sp.SETTINGS).chmod(mode)
        with pytest.raises(sp.Refused, match="readable or writable by group or others"):
            sp.files(deploy)
    (deploy / sp.SETTINGS).chmod(0o600)
    (deploy / "site").chmod(0o777)
    with pytest.raises(sp.Refused, match="alone"):  # a folder others may write: a file could be swapped in
        sp.files(deploy)
    (deploy / "site").chmod(0o755)
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


@pytest.mark.parametrize("stack", GPU_STACKS, ids="+".join)
def test_the_image_a_run_records_is_the_one_its_stack_runs(tmp_path: Path, stack: tuple[str, ...]) -> None:
    """OCR 1459-13: the current engine's digest is the image its own llm-service line resolves to on this box (the
    variable that stack uses, its default when the box sets none), never another variable of the lock entry."""
    lock = json.loads((DEPLOY / "images.lock").read_text(encoding="utf-8"))
    engine = next(e for e in lock["third_party"].values() if e.get("gpu"))
    m = sp.IMAGE_VAR.match(str(_merge(stack)["llm-service"]["image"]))
    assert m is not None
    used = m.group(1)
    others = [v for v in engine["variables"] if v != used]
    base = [ln for ln in DUMMY_ENV.splitlines() if not ln.startswith(tuple(f"{v}=" for v in engine["variables"]))]

    def box(extra: str) -> Path:
        d = _box(tmp_path, stack, "TB_ENV=TEST\n")
        (d / ".env").write_text("\n".join(base) + f"\nCOMPOSE_FILE={':'.join(str(DEPLOY / f) for f in stack)}\n"
                                + extra, encoding="utf-8")  # fmt: skip
        return d

    mine, theirs = "sha256:" + "ef" * 32, "sha256:" + "ab" * 32
    if m.group(2):  # a default: the lock's pin when the box sets nothing, or sets only another variable
        assert sp.image(box("")) == engine["digest"]
        for v in others:
            assert sp.image(box(f"{v}=mirror.invalid/x@{theirs}\n")) == engine["digest"], v
    else:  # no default (the platform form): the box must set it
        with pytest.raises(sp.Refused, match="not pinned by digest"):
            sp.image(box(""))
    assert sp.image(box(f"{used}=mirror.invalid/x@{mine}\n")) == mine
    with pytest.raises(sp.Refused, match="not pinned by digest"):
        sp.image(box(f"{used}=engine:1.0\n"))  # a tag the box set is never recorded as what ran


def test_the_second_engines_recorded_image_is_its_pin(tmp_path: Path) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
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
                                             ({"TB_ENV": "TEST"}, "WARN"), ({"TB_ENV": "VALIDATION"}, "FAIL")])  # fmt: skip
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
    # the largest answer first and a lower one after it: "the largest sample" is never "the last" (OCR 1459-15)
    for engine, answer, peaks in (("current", jb.stub_answer, [41000, 1000]), ("second", wavering, [39000, 900])):
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


# ----------------------------------------------------------------------------- the external review of bae68bbd
def test_ocr_1459_1_compose_runs_the_checked_digest_and_never_a_tag(tmp_path: Path) -> None:
    """1459-1 / 1459-9: with the switch on, `compose` checks the local image against the pin and hands compose the
    values it checked, in a private copy, by digest: no tag is made, nothing is pulled, and a settings file swapped
    after the check is never used."""
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    ref = FILLED["SERVING2_IMAGE"]
    seen: list[list[str]] = []
    handed: dict[str, str] = {}

    def run(argv: Any, **_: Any) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        seen.append(argv)
        if argv[1:3] == ["image", "inspect"]:  # after the check: someone swaps the settings file
            (deploy / sp.SETTINGS).write_text("".join(f"{k}={v}\n" for k, v in {**ON, "SERVING2_SERVER": "other"}.items()),
                                              encoding="utf-8")  # fmt: skip
            return subprocess.CompletedProcess(argv, 0, json.dumps([ref]), "")
        env_files = [argv[i + 1] for i, x in enumerate(argv) if x == "--env-file"]
        private = Path(env_files[-1])
        assert private.parent != deploy / "site" and stat.S_IMODE(private.stat().st_mode) == 0o600
        handed.update(sp.parse_env(private.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(argv, 0, "", "")

    assert sp.compose(deploy, ["up", "-d"], run=run) == 0
    assert [c[1] for c in seen] == ["image", "compose"]  # no tag, no pull
    assert handed == ON  # the values it checked, not the swapped file
    files = [seen[-1][i + 1] for i, x in enumerate(seen[-1]) if x == "-f"]
    assert seen[-1][-2:] == ["up", "-d"] and Path(files[-1]).name == OVERLAY and len(files) == len(GPU_STACKS[0]) + 1


@pytest.mark.parametrize("form", ["bom", "export", "not-utf8", "a-folder"])
def test_ocr_1459_2_a_switch_written_on_is_never_read_as_off(tmp_path: Path, form: str) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    p = deploy / sp.SETTINGS
    rest = "".join(f"{k}={v}\n" for k, v in FILLED.items())
    if form == "bom":
        p.write_text(f"\ufeff{sp.SWITCH}=second\n" + rest, encoding="utf-8")
    elif form == "export":
        p.write_text(f"export {sp.SWITCH}=second\n" + rest, encoding="utf-8")
    elif form == "not-utf8":
        p.write_bytes(f"{sp.SWITCH}=second\n".encode() + b"\xff\xfe\n" + rest.encode())
    else:
        p.unlink()
        p.mkdir()
    if form in ("bom", "export"):
        assert sp.switch(deploy) == "second"
        assert sp.files(deploy)[-1].endswith(OVERLAY)
        return
    with pytest.raises(sp.Refused, match="cannot be read"):
        sp.switch(deploy)
    assert sp.main(["files", "--deploy", str(deploy)]) == 1
    c = doctor.check_bench_serving(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=deploy))
    assert c.status == "FAIL"  # and doctor never takes it for off


@pytest.mark.parametrize(("env", "status"), [("TB_ENV=TEST\n", "WARN"), ("", "FAIL"), ("TB_ENV=VALIDATION\n", "FAIL")])
def test_ocr_1459_3_doctor_sees_the_switch_not_only_compose_file(tmp_path: Path, env: str, status: str) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], env, settings=ON)
    c = doctor.check_bench_serving(doctor.DoctorInputs(env=sp.env_file(deploy / ".env"), deploy=deploy))
    assert c.status == status and "the switch in" in c.detail, c
    off = _box(tmp_path / "off", GPU_STACKS[0], env, settings={**FILLED, "SERVING_ENGINE": "current"})
    assert doctor.check_bench_serving(doctor.DoctorInputs(env=sp.env_file(off / ".env"), deploy=off)).status == "PASS"


def test_ocr_1459_4_the_judge_renders_the_current_engines_chat_template(tmp_path: Path) -> None:
    """The switch refuses a judge template other than the one the current engine renders on this box: the GPU
    overlay's default, or the box's own JUDGE_CHAT_TEMPLATE when it sets one."""
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    assert sp.files(deploy)[-1].endswith(OVERLAY)
    for stack in GPU_STACKS:
        assert sp.current_template(deploy, {}, [str(DEPLOY / f) for f in stack]) == CURRENT_T, stack
    _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\nJUDGE_CHAT_TEMPLATE=templates/site.jinja\n", settings=ON)
    with pytest.raises(sp.Refused, match="chat template"):
        sp.files(deploy)
    _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\nJUDGE_CHAT_TEMPLATE=templates/site.jinja\n",
         settings={**ON, "SERVING2_JUDGE_CHAT_TEMPLATE": "templates/site.jinja"})  # fmt: skip
    assert sp.files(deploy)[-1].endswith(OVERLAY)
    assert "SERVING2_VERIFIER_CHAT_TEMPLATE" in sp.required_keys(DEPLOY)


@pytest.mark.parametrize("line", ["x-trialbox-bench-serving: true", "x-trialbox-bench-serving: true  ",
                                  "x-trialbox-bench-serving:   true  # bench"])  # fmt: skip
def test_ocr_1459_7_the_mark_is_found_as_compose_reads_it(tmp_path: Path, line: str) -> None:
    copy = tmp_path / "docker-compose.copy.yml"
    copy.write_text((DEPLOY / OVERLAY).read_text(encoding="utf-8").replace(sp.MARK, line), encoding="utf-8")
    assert yaml.safe_load(sp.COMPOSE_TAG.sub("", copy.read_text(encoding="utf-8")))["x-trialbox-bench-serving"] is True
    files = ":".join([str(DEPLOY / f) for f in GPU_STACKS[0]] + [str(copy)])
    c = doctor.check_bench_serving(doctor.DoctorInputs(env={"COMPOSE_FILE": files}, deploy=tmp_path))
    assert c.status == "FAIL"
    assert il.check_compose(il.load(), [copy]) == ([], set())  # the bench file's own rules apply to the copy too
    assert sp.MARK_LINE.search(copy.read_text(encoding="utf-8"))


def test_ocr_1459_8_the_key_file_is_its_owners_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    key = tmp_path / "key"
    key.write_text("not-a-real-key\n", encoding="utf-8")
    items = _items()[:2]
    set_file = tmp_path / "set.jsonl"
    sha = jb.write_set(items, set_file)
    argv = ["run", "--engine", "current", "--candidate", "A", "--quant", "q4", "--image-digest", IMAGE["current"],
            "--base-url", "http://127.0.0.1:9/v1", "--served-name", "x", "--key-file", str(key), "--set",
            str(set_file), "--expect-set-sha", sha, "--out", str(tmp_path / "o")]  # fmt: skip
    for mode in (0o644, 0o640, 0o604):
        key.chmod(mode)
        assert ec.main(argv) == 2
        assert "the key file is refused" in capsys.readouterr().err
    key.chmod(0o600)
    assert ec.read_key(key) == "not-a-real-key"


def test_ocr_1459_10_a_run_leaves_no_old_or_half_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    out = tmp_path / "o"
    out.mkdir()
    (out / ec.SUMMARY).write_text(json.dumps({"engine": "current", "candidate": "A", "quant": "old"}), "utf-8")

    def interrupted(*_: Any, **__: Any) -> list[jb.Row]:
        raise KeyboardInterrupt

    monkeypatch.setattr(jb, "run", interrupted)  # the module engine_compare calls
    with jb.stub_server() as url, pytest.raises(KeyboardInterrupt):
        ec.run(url, jb.STUB_NAME, _items()[:2], {"engine": "current", "candidate": "A", "quant": "q4"}, out,
               gpu_cmd=[])  # fmt: skip
    assert not (out / ec.SUMMARY).exists()  # the earlier run's row is not left for `table`
    assert ec.main(["table", str(out)]) == 2 and "no whole summary.json" in capsys.readouterr().err
    (out / ec.SUMMARY).write_text('{"engine": "cur', encoding="utf-8")  # a half-written file
    assert ec.main(["table", str(out)]) == 2
    ec.write_summary(out, {"engine": "current"})
    assert json.loads((out / ec.SUMMARY).read_text(encoding="utf-8")) == {"engine": "current"}
    assert not (out / (ec.SUMMARY + ".tmp")).exists()


def test_ocr_1459_12_by_criterion_never_carries_a_patient_report_or_item_id() -> None:
    """Only the synthetic set's item ids end in a criterion id; any other source's id carries a patient, report or
    item id, so its differences are counted under its source alone, in summary.json and in the table."""
    others = sorted(set(jb.GATED) - {"synthetic"})

    def row(src: str, rid: str, cl: str, ans: str) -> jb.Row:
        return jb.Row(rid, src, cl, "", "exclusion", "unknown", False, predicate=ans, attempts=1)

    def rows(ans: str) -> list[jb.Row]:
        out = [row("synthetic", "synthetic:site-a:1:C1", "site-a:1", ans)]
        out += [row(s, f"{s}:P-{i}|T-1|0", f"P-{i}", ans) for i, s in enumerate(others, 1)]
        out += [row(s, f"{s}:ja:RPT-{i}-f2", f"RPT-{i}", ans) for i, s in enumerate(others, 1)]
        return out

    got = ec.from_run_1([rows("pass"), rows("fail")])
    labels = {"C1": 1, **{f"{s} (all items)": 2 for s in others}}
    assert got == [{"run": 2, "pairs": 1 + 2 * len(others), "by_criterion": dict(sorted(labels.items(),
                   key=lambda kv: (-kv[1], kv[0])))}]  # fmt: skip
    table = ec.render_table([{"engine": "second", "candidate": "A", "quant": "q4", "from_run_1": got}])
    assert "P-" not in table and "RPT-" not in table and "site-a" not in table


def test_ocr_1459_16_a_digest_with_a_final_newline_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    d = "sha256:" + "ab" * 32
    assert ec.DIGEST.match(d) and not ec.DIGEST.match(d + "\n")
    assert sp.PINNED.match("r.invalid/e@" + d) and not sp.PINNED.match("r.invalid/e@" + d + "\n")
    assert not sp.DIGEST_TAIL.search("r.invalid/e:1@" + d + "\n")
    assert il.BENCH_REF.match("r.invalid/e@" + d) and not il.BENCH_REF.match("r.invalid/e@" + d + "\n")
    argv = ["run", "--engine", "current", "--candidate", "A", "--quant", "q4", "--image-digest", d + "\n",
            "--base-url", "http://127.0.0.1:9/v1", "--served-name", "x", "--set", str(tmp_path / "s.jsonl"),
            "--expect-set-sha", "0", "--out", str(tmp_path / "o")]  # fmt: skip
    assert ec.main(argv) == 2 and "never a tag" in capsys.readouterr().err
