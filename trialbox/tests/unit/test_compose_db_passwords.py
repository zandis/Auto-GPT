"""T-712 (D-481; trust review F1, TR-1): a service container holds its own database role's password and no other.

The compose files of the tree are merged and rendered in Python (``tools.trialbox.db_secrets.render``: the merge of
several files, ``env_file`` and ``${NAME}`` interpolation as compose does them), every database password set to its
own marker, and each service's environment is searched for a marker that is not its own, under any variable name.
No ``docker`` is needed, so this runs in every CI job and cannot be skipped; where the ``docker compose`` plugin
exists, one test holds the Python render against ``docker compose config``.

Every file set a box, a rehearsal or a developer starts is here, the base file alone included: the clears belong to
the base file, not to an overlay a stack may be started without.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import db_secrets as ds
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
BASE = "docker-compose.yml"
SECRETS = "docker-compose.secrets.yml"
#: every compose file set of the tree: what install.sh, poc.sh, the Makefile and the platform form start
STACKS: list[tuple[str, ...]] = [
    (BASE,),  # a developer's `docker compose up`, `make up`
    (BASE, "docker-compose.test.yml"),  # make test-compose
    (BASE, "docker-compose.test.yml", "docker-compose.poc.yml"),  # deploy/poc.sh
    (BASE, "docker-compose.gb10.yml", "docker-compose.test.yml", "docker-compose.poc.yml"),
    (BASE, SECRETS),  # install.sh, every box
    (BASE, SECRETS, "docker-compose.gb10.yml"),
    (BASE, SECRETS, "docker-compose.rtx5090.yml"),
    (BASE, SECRETS, "docker-compose.rtxpro6000.yml"),
    (BASE, SECRETS, "docker-compose.shared-quota.yml"),
    (BASE, SECRETS, "docker-compose.identity.yml"),
    (BASE, SECRETS, "docker-compose.identity.yml", "docker-compose.box.yml"),
    (BASE, SECRETS, "docker-compose.monitoring.yml"),
    (BASE, SECRETS, "docker-compose.identity.yml", "docker-compose.acceptance.yml"),
    (BASE, SECRETS, "docker-compose.gb10.yml", "two-device/docker-compose.spark.yml"),
    (BASE, SECRETS, "two-device/docker-compose.workstation.yml"),
    (BASE, SECRETS, "platform/docker-compose.platform.yml"),
]
IDS = [
    "+".join(f.rpartition("docker-compose.")[2].removesuffix(".yml").replace("yml", "base") for f in s) for s in STACKS
]


def secret_names() -> list[str]:
    """The database passwords the box's server is given (the `db` service of the base file)."""
    doc = yaml.safe_load((DEPLOY / BASE).read_text(encoding="utf-8"))
    return sorted(k for k in doc["services"]["db"]["environment"] if ds.DB_SECRET.match(k))


def db_url(role: str, word: str) -> str:
    """A trial-database URL of ``role``. Built here so that no line of this file reads as a credential."""
    return f"postgresql://{role}:{word}@db:5432/trialbox_wf"


def marks() -> dict[str, str]:
    return {n: f"dbm4rk{i:02d}q" for i, n in enumerate(secret_names())}


def box_env(m: dict[str, str]) -> dict[str, str]:
    """A box's deploy/.env: the passwords, the host tools' administrator URL (install.sh), and what the files
    require to render."""
    env = dict(m)
    env["TB_DB_URL"] = f"postgresql://trialbox:{m['POSTGRES_WF_PASSWORD']}@db:5432/trialbox_wf"
    env |= {"TB_TZ": "Asia/Taipei", "TB_TLS_HOSTNAME": "tb.test", "TB_ENV": "PRODUCTION", "TB_LINK_ADDR": "10.9.0.1",
            "TB_LINK_PEER": "10.9.0.2", "TB_ACCEPTANCE_MAIL_PASSWORD": "acc-mail-marker",
            "TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD": "acc-keystore-marker", "TB_MIG_PROFILE": "1g.23gb",
            "TB_MIG_JUDGE_DEVICE": "MIG-a", "TB_MIG_VERIFIER_DEVICE": "MIG-b",
            "TB_IMAGE": "tb:x", "TB_JVM_IMAGE": "tb:x", "TB_EMBED_IMAGE": "tb:x", "TB_DOCPARSER_IMAGE": "tb:x",
            "POSTGRES_IMAGE": "tb:x", "HAPI_IMAGE": "tb:x", "VLLM_IMAGE": "tb:x"}  # fmt: skip
    env |= {k: "1" for k in ("JUDGE_GPU_MEM_UTIL", "JUDGE_MAX_LEN", "JUDGE_MAX_SEQS", "VERIFIER_GPU_MEM_UTIL",
                             "VERIFIER_MAX_LEN", "VERIFIER_MAX_SEQS")}  # fmt: skip
    return env


def make_box(tmp: Path, env: dict[str, str]) -> Path:
    """A deploy folder: the tree's compose files and a `.env` of ``env``."""
    for f in DEPLOY.glob("docker-compose*.yml"):
        shutil.copy(f, tmp / f.name)
    for sub in ("two-device", "platform"):
        (tmp / sub).mkdir()
        for f in (DEPLOY / sub).glob("docker-compose*.yml"):
            shutil.copy(f, tmp / sub / f.name)
    (tmp / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    return tmp


def rendered(tmp: Path, stack: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, str]]:
    m = marks()
    env = box_env(m)
    box = make_box(tmp, env)
    return ds.render([box / f for f in stack], env, project_dir=box), m


# ----------------------------------------------------------------------------------------------- the acceptance
@pytest.mark.parametrize("stack", STACKS, ids=IDS)
def test_no_container_holds_a_foreign_database_password(tmp_path: Path, stack: tuple[str, ...]) -> None:
    config, m = rendered(tmp_path, stack)
    assert ds.reach_problems(config, m) == []


@pytest.mark.parametrize("stack", STACKS, ids=IDS)
def test_each_service_holds_its_own_password_and_only_in_its_url(tmp_path: Path, stack: tuple[str, ...]) -> None:
    """The positive half, so that the test above cannot pass on a render that lost every value."""
    config, m = rendered(tmp_path, stack)
    with_role = ds.database_services(config)
    assert {"lake", "orchestrator", "console", "audit-writer"} <= set(with_role)
    for svc in with_role:
        env = config["services"][svc]["environment"]
        own = m[ds.role_secret(svc)]
        assert [k for k, v in env.items() if own in v] == ["TB_DB_URL"], svc
        assert env["TB_DB_URL"].startswith(f"postgresql://tb_{svc.replace('-', '_')}:{own}@"), svc
    for svc in ("embed-service", "doc-parser", "llm-stub"):  # they open no database
        assert config["services"][svc]["environment"].get("TB_DB_URL", "") == "", svc


def test_every_role_with_a_url_has_a_password_of_its_own(tmp_path: Path) -> None:
    """A new service with a role needs its `TB_DB_PW_<SERVICE>` in the `db` service (and install.sh); a password
    with no service is a left-over."""
    env = box_env(marks())
    box = make_box(tmp_path, env)
    config = ds.render([box / BASE], env, project_dir=box)
    roles = {ds.role_secret(s) for s in ds.database_services(config)}
    assert roles == set(secret_names()) - set(ds.ADMIN)
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert all(name in install for name in secret_names())


# ------------------------------------------------------------------------------------------- the check can fail
def test_the_check_finds_a_password_under_another_name(tmp_path: Path) -> None:
    config, m = rendered(tmp_path, (BASE, SECRETS))
    config["services"]["doc-parser"]["environment"]["SOME_URL"] = (
        f"postgresql://tb_console:{m['TB_DB_PW_CONSOLE']}@db/x"
    )
    assert ds.reach_problems(config, m) == ["doc-parser holds TB_DB_PW_CONSOLE (in SOME_URL)"]


def test_the_check_finds_another_roles_url(tmp_path: Path) -> None:
    config, m = rendered(tmp_path, (BASE, SECRETS))
    config["services"]["lake"]["environment"]["TB_DB_URL"] = db_url("tb_console", "short")
    assert ds.reach_problems(config, m) == ["lake: TB_DB_URL signs in as tb_console, not as tb_lake"]


def test_a_new_service_that_reads_the_env_file_is_caught(tmp_path: Path) -> None:
    """A service added with `env_file: [.env]` and no clears holds every password: the test fails until it has them."""
    m = marks()
    env = box_env(m)
    box = make_box(tmp_path, env)
    (box / "extra.yml").write_text(
        "services:\n  new-thing:\n    image: x\n    env_file: [.env]\n    environment: {PORT: '1'}\n", encoding="utf-8"
    )
    bad = ds.reach_problems(ds.render([box / BASE, box / SECRETS, box / "extra.yml"], env, project_dir=box), m)
    held = {b.split()[2] for b in bad if b.startswith("new-thing holds ")}
    assert held == set(m)  # every role's password and both administrators'
    assert "new-thing: TB_DB_URL signs in as trialbox, not as tb_new_thing" in bad
    assert all(b.startswith("new-thing") for b in bad)


def test_a_missing_role_password_gives_the_service_the_administrators(tmp_path: Path) -> None:
    """Why `doctor` fails a box without `TB_DB_PW_<SERVICE>`: the URL falls back to the workflow password."""
    m = marks()
    env = box_env(m)
    del env["TB_DB_PW_LAKE"]
    box = make_box(tmp_path, env)
    bad = ds.reach_problems(ds.render([box / BASE, box / SECRETS], env, project_dir=box), m)
    assert bad == ["lake holds POSTGRES_WF_PASSWORD (in TB_DB_URL)"]
    assert ds.env_problems(env, ["lake", "console"]) == [
        "TB_DB_PW_LAKE is not set: lake would sign in with the workflow administrator's password"
    ]


def test_env_problems_names_example_and_shared_passwords() -> None:
    env = {
        "POSTGRES_PASSWORD": "change-me-pg",
        "POSTGRES_WF_PASSWORD": "one-password-x",
        "TB_DB_PW_LAKE": "one-password-x",
    }
    assert ds.env_problems(env, ["lake"]) == [
        "POSTGRES_PASSWORD is still the example value",
        "TB_DB_PW_LAKE and POSTGRES_WF_PASSWORD are the same password",
    ]
    assert not any("one-password-x" in line or "change-me-pg" in line for line in ds.env_problems(env, ["lake"]))


# ------------------------------------------------------------------------------------------ the render is compose's
def test_interpolation_forms() -> None:
    env = {"A": "a", "EMPTY": ""}
    cases = {"${A}": "a", "$A-x": "a-x", "${B:-d}": "d", "${EMPTY:-d}": "d", "${EMPTY-d}": "", "${B-d}": "d",
             "${B:-${C:-${A}}}": "a", "${A:+yes}": "yes", "${EMPTY:+yes}": "", "${EMPTY+yes}": "yes", "$$A": "$A",
             "${A:?need}": "a", "x${B}y": "xy"}  # fmt: skip
    assert {k: ds.interpolate(k, env) for k in cases} == cases
    for bad in ("${B:?need it}", "${EMPTY:?need it}", "${B?need it}", "${A", "${A!x}"):
        with pytest.raises(ds.RenderError):
            ds.interpolate(bad, env)


def test_render_merges_as_compose_does(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("# c\nFROM_FILE='f'\nBOTH=file\nexport X=1\n\nnot a pair\n", encoding="utf-8")
    (tmp_path / "more.env").write_text("BOTH=more\n", encoding="utf-8")
    (tmp_path / "a.yml").write_text(
        "x-a: &a {P: '1', Q: '2'}\nservices:\n  s:\n    env_file: [.env]\n    environment: {<<: *a, Q: '${V:-q}', N: 5}\n"
        "  t:\n    environment: [K=v, PASSED, ABSENT]\n  u: {}\n", encoding="utf-8")  # fmt: skip
    (tmp_path / "b.yml").write_text(
        "services:\n  s:\n    env_file:\n      - {path: more.env}\n      - {path: none.env, required: false}\n"
        "    environment: {P: '', T: true}\n", encoding="utf-8")  # fmt: skip
    got = ds.render([tmp_path / "a.yml", tmp_path / "b.yml"], {"PASSED": "p"})["services"]
    assert got["s"]["environment"] == {
        "FROM_FILE": "f",
        "BOTH": "more",
        "X": "1",
        "P": "",
        "Q": "q",
        "N": "5",
        "T": "true",
    }
    assert got["t"]["environment"] == {"K": "v", "PASSED": "p"}
    assert got["u"]["environment"] == {}
    (tmp_path / "c.yml").write_text("services:\n  s:\n    env_file: gone.env\n", encoding="utf-8")
    with pytest.raises(ds.RenderError, match="gone.env"):
        ds.render([tmp_path / "c.yml"], {})
    (tmp_path / "d.yml").write_text("- a\n", encoding="utf-8")
    with pytest.raises(ds.RenderError, match="not a mapping"):
        ds.render([tmp_path / "d.yml"], {})


def _compose() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin (the Python render above runs everywhere)")
@pytest.mark.parametrize("stack", STACKS, ids=IDS)
def test_the_python_render_agrees_with_docker_compose(tmp_path: Path, stack: tuple[str, ...]) -> None:
    """Section 5.3 of plan v6.1: a stand-in is held against the real thing. Every service's environment, every
    profile."""
    m = marks()
    env = box_env(m)
    box = make_box(tmp_path, env)
    (box / "secrets" / "model").mkdir(parents=True)
    (box / "secrets" / "model" / "vllm.env").write_text("VLLM_API_KEY=model-key-marker\n", encoding="utf-8")
    argv = ["docker", "compose", "--project-directory", str(box), *(x for f in stack for x in ("-f", str(box / f))),
            "--profile", "*", "config", "--format", "json"]  # fmt: skip
    out = subprocess.run(argv, cwd=box, capture_output=True, text=True, timeout=120, check=False,
                         env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(box)})  # fmt: skip
    assert out.returncode == 0, out.stderr
    real = {s: b.get("environment") or {} for s, b in json.loads(out.stdout)["services"].items()}
    mine = {
        s: b["environment"] for s, b in ds.render([box / f for f in stack], env, project_dir=box)["services"].items()
    }
    assert mine == real


# ---------------------------------------------------------------------------------------------------- the doctor
def _doctor(box: Path, env: dict[str, str], **kw: Any) -> doctor.Check:
    inp = doctor.DoctorInputs(env=env, deploy=box, **kw)
    return doctor.check_db_passwords(inp, running=lambda project: None)


def test_doctor_passes_a_box_as_install_makes_it(tmp_path: Path) -> None:
    m = marks()
    env = box_env(m)
    box = make_box(tmp_path, env)
    env["COMPOSE_FILE"] = f"{box / BASE}:{box / SECRETS}"
    got = _doctor(box, env)
    assert got.status == "PASS", got.detail
    assert "8 service roles" in got.detail and "running containers not read" in got.detail


def test_doctor_fails_a_production_box_whose_role_password_is_missing(tmp_path: Path) -> None:
    m = marks()
    env = box_env(m)
    del env["TB_DB_PW_CONSOLE"]
    box = make_box(tmp_path, env)
    env["COMPOSE_FILE"] = f"{box / BASE}:{box / SECRETS}"
    got = _doctor(box, env)
    assert got.status == "FAIL"
    assert "TB_DB_PW_CONSOLE is not set" in got.detail and "console holds POSTGRES_WF_PASSWORD" in got.detail
    assert not any(v in got.detail for v in m.values())
    env["TB_ENV"] = "DEV"  # a developer's stack runs on the example file: said, not failed
    assert _doctor(box, env).status == "WARN"


def test_doctor_reads_the_running_containers(tmp_path: Path) -> None:
    """A container started before the clears keeps what it was given until it is made again."""
    m = marks()
    env = box_env(m)
    box = make_box(tmp_path, env)
    env["COMPOSE_FILE"] = f"{box / BASE}:{box / SECRETS}"
    stale = {"services": {"doc-parser": {"environment": {"TB_DB_PW_CONSOLE": m["TB_DB_PW_CONSOLE"]}}}}
    got = doctor.check_db_passwords(doctor.DoctorInputs(env=env, deploy=box), running=lambda project: stale)
    assert got.status == "FAIL" and "running: doc-parser holds TB_DB_PW_CONSOLE (in TB_DB_PW_CONSOLE)" in got.detail
    fresh = {"services": {"doc-parser": {"environment": {"TB_DB_PW_CONSOLE": ""}}}}
    got = doctor.check_db_passwords(doctor.DoctorInputs(env=env, deploy=box), running=lambda project: fresh)
    assert got.status == "PASS" and "1 running container(s) read" in got.detail


def test_doctor_says_when_it_has_nothing_to_judge(tmp_path: Path) -> None:
    # review of #308 (H1): "not judged" is never a pass; on a box that may hold real data it fails
    for env_name, want in (("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("", "FAIL"), ("DEV", "WARN")):
        got = doctor.check_db_passwords(doctor.DoctorInputs(env={"TB_ENV": env_name}))
        assert got.status == want and "not judged" in got.detail, env_name
    env = box_env(marks()) | {"COMPOSE_FILE": str(tmp_path / "gone.yml")}
    got = _doctor(tmp_path, env)
    assert got.status == "FAIL" and "gone.yml" in got.detail
    assert doctor.check_db_passwords in doctor.CHECKS


def test_running_config_reads_docker_inspect() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str]) -> str:
        calls.append(argv)
        if argv[1] == "ps":
            return "aaa\nbbb\n"
        return json.dumps([
            {"Config": {"Env": ["A=1", "TB_DB_URL=" + db_url("tb_lake", "pw")],
                        "Labels": {"com.docker.compose.service": "lake"}}},
            {"Config": {"Env": ["B=2"], "Labels": {}}},
        ])  # fmt: skip

    got = ds.running_config("box", run)
    assert got == {"services": {"lake": {"environment": {"A": "1", "TB_DB_URL": db_url("tb_lake", "pw")}}}}
    assert calls[0][-1] == "label=com.docker.compose.project=box" and calls[1][:2] == ["docker", "inspect"]
    assert ds.running_config("box", lambda argv: "") is None

    def no_docker(argv: list[str]) -> str:
        raise FileNotFoundError("docker")

    assert ds.running_config("box", no_docker) is None


def test_doctor_judges_the_box_from_inside_its_own_image(tmp_path: Path) -> None:
    """Review of #308 (H1): ``check_host.sh`` runs the doctor in the box's image, where ``deploy`` is mounted at
    another path than the host-absolute entries of ``COMPOSE_FILE`` (``install.sh`` writes ``$ROOT/deploy/...``)."""
    m = marks()
    env = box_env(m)
    del env["TB_DB_PW_CONSOLE"]
    box = make_box(tmp_path, env)
    env["COMPOSE_FILE"] = f"/opt/trialbox-host/deploy/{BASE}:/opt/trialbox-host/deploy/{SECRETS}"
    got = _doctor(box, env)
    assert got.status == "FAIL" and "TB_DB_PW_CONSOLE is not set" in got.detail, got.detail
    env = box_env(m) | {"COMPOSE_FILE": env["COMPOSE_FILE"]}
    (tmp_path / "ok").mkdir()
    assert _doctor(make_box(tmp_path / "ok", env), env).status == "PASS"
    text = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    before, run = text.split('docker run --rm --network none --env-file "$ENV_FILE"', 1)
    # the doctor in the image is told where the box's file is (the deploy folder is mounted at /app/deploy)
    assert 'set -- "$@" --env-file /app/deploy/.env' in before.rsplit("set -- ;", 1)[1]
    assert '-v "$ROOT_DIR/deploy:/app/deploy:ro"' in run and 'tools.trialbox doctor "$@"' in run[: run.index("then")]


def test_an_empty_tb_env_is_production_for_the_doctor(tmp_path: Path) -> None:
    """Review of #308 (M1): ``TB_ENV=`` in deploy/.env is PRODUCTION everywhere else (D-127)."""
    m = marks()
    env = box_env(m) | {"TB_ENV": ""}
    del env["TB_DB_PW_CONSOLE"]
    box = make_box(tmp_path, env)
    env["COMPOSE_FILE"] = f"{box / BASE}:{box / SECRETS}"
    assert _doctor(box, env).status == "FAIL"


def test_the_platform_doctor_holds_no_database_password(tmp_path: Path) -> None:
    """Review of #308 (H2): it is on the egress network only and cannot reach the database; it held the
    administrator's password and URL for nothing."""
    assert ds.ADMIN_HOLDERS["POSTGRES_WF_PASSWORD"] == {"db"}
    m = marks()
    env = box_env(m)
    box = make_box(tmp_path, env)
    files = [box / BASE, box / SECRETS, box / "platform" / "docker-compose.platform.yml"]
    got = ds.render(files, env, project_dir=box)["services"]["doctor"]["environment"]
    assert not any(v and v in str(x) for x in got.values() for v in m.values()), sorted(got)
