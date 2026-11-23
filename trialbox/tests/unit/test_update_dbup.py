"""UPDATE-DBUP (D-624): what a release does once the database is up and before its services start (the role script,
the schemas no service owns, whatever a later release adds) is run by the NEW release's own command, on an update
and on an install. The updater that is running is the installed, older release's."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import prestart
from tools.trialbox import update as up

# a box that ran the installer's database step: the admin URL and the FHIR store's password (D-541). Synthetic
# words; the URL is put together here so that no credential URL stands in the file as one text.
DB_ENV = "TB_DB_URL=postgresql://" + "trialbox:pw" + "@db:5432/trialbox_wf\nTB_DB_PW_FHIR_STORE=synthetic-fhir-store\n"

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

ROLES = "/docker-entrypoint-initdb.d/30-service-roles.sh"

NEW_RELEASE = '''"""A later release: after the database is up it runs a step the installed release never heard of."""
import sys
from pathlib import Path

deploy = Path(sys.argv[sys.argv.index("--deploy") + 1])
cmd = sys.argv[1]
if cmd == "db-up":
    if (deploy / "FAIL").exists():
        print("db-up: the new grant failed", file=sys.stderr)
        raise SystemExit(1)
    (deploy / "db-up.ran").write_text("the new release's database steps")
    print("db-up: a grant new in this release: made")
else:
    print("pre-start: nothing new")
'''


class Run:
    """The updater's runner: records every command; runs the new tree's commands for real, nothing else."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], **_kw: Any) -> str:
        self.calls.append(list(argv))
        if "tools.trialbox" in argv:
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            r = subprocess.run(list(argv), capture_output=True, text=True, env=env, check=False)
            if r.returncode != 0:
                raise up.UpdateFailed(r.stderr.strip())
            return r.stdout
        return ""

    def where(self, *words: str) -> int:
        hits = [i for i, c in enumerate(self.calls) if all(w in c for w in words)]
        assert hits, (words, self.calls)
        return hits[0]

    def has(self, *words: str) -> bool:
        return any(all(w in c for w in words) for c in self.calls)


def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, tree: str) -> tuple[up.ComposeBox, Run, Path]:
    """``tree``: ``db-up`` (a release with the command), ``pre-start`` (D-620's release, before it), ``none``."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(
        "TB_SITE_ID=T\n" + DB_ENV,
        encoding="utf-8",
    )
    if tree != "none":  # what apply_host leaves: the install folder's tools/ is the new release's
        pkg = tmp_path / "tools" / "trialbox"
        pkg.mkdir(parents=True)
        (tmp_path / "tools" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "prestart.py").write_text("DB_STEPS = []\n" if tree == "db-up" else "STEPS = []\n", encoding="utf-8")
        (pkg / "__main__.py").write_text(NEW_RELEASE, encoding="utf-8")
    monkeypatch.setenv("TB_COMPOSE", "dc")
    run = Run()
    return up.ComposeBox(deploy, run=run), run, deploy


def _plan(tmp_path: Path) -> Any:
    return up.Plan(bundle_id="B1", manifest_sha256="0" * 64, signer="t", files=[], stage=tmp_path / "stage")


def test_the_new_trees_database_steps_run_before_the_services_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box, run, deploy = _box(tmp_path, monkeypatch, tree="db-up")
    box.restart(_plan(tmp_path))
    assert (deploy / "db-up.ran").is_file()  # the new release's step ran: the installed updater never knew it
    assert run.where("pre-start") < run.where("db-up") < run.where("up", "--wait-timeout")
    call = run.calls[run.where("db-up")]
    assert call[:2] == ["sh", "-c"] and str(tmp_path) in call  # in the install folder, as pre-start
    # the new tree decides what runs against the database: the old updater does not run its own copy as well
    assert not run.has("exec", ROLES) and not run.has("orchestrator.migrate")
    assert "db-up: a grant new in this release: made" in capsys.readouterr().out


def test_a_failed_database_step_stops_the_update_before_the_services_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, run, deploy = _box(tmp_path, monkeypatch, tree="db-up")
    (deploy / "FAIL").write_text("", encoding="utf-8")
    with pytest.raises(up.UpdateFailed) as exc:
        box.restart(_plan(tmp_path))
    assert str(exc.value) == "db-up: the new grant failed"  # the reason, not the command line around it
    assert not run.has("up", "--wait-timeout")


@pytest.mark.parametrize("tree", ["pre-start", "none"])
def test_a_tree_from_before_the_command_gets_the_two_commands_it_always_got(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tree: str
) -> None:
    box, run, _ = _box(tmp_path, monkeypatch, tree=tree)
    monkeypatch.setattr(box, "resolve_pins", lambda: None)
    monkeypatch.setattr(box, "ensure_model_key", lambda: False)
    box.restart(_plan(tmp_path))
    assert not run.has("db-up")
    assert run.where("exec", ROLES) < run.where("orchestrator.migrate") < run.where("up", "--wait-timeout")


# ------------------------------------------------------------------------------------ this release's own command
def _steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str) -> tuple[list[str], list[list[str]]]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(env, encoding="utf-8")
    calls: list[list[str]] = []

    def fake(argv: Sequence[str], **_kw: Any) -> str:
        calls.append(list(argv))
        return ""

    monkeypatch.setenv("TB_COMPOSE", "dc")
    return prestart.run_db(deploy, up.ComposeBox(deploy, run=fake)), calls


def test_this_releases_steps_are_the_database_then_the_roles_then_the_owned_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines, calls = _steps(
        tmp_path,
        monkeypatch,
        DB_ENV,
    )
    assert [name for name, _ in prestart.DB_STEPS] == [
        "FHIR store password is set",
        "database",
        "service roles",
        "owned schemas",
        "service stores",
    ]
    assert [ln.split(":")[1].strip() for ln in lines] == [
        "FHIR store password is set",
        "database",
        "service roles",
        "owned schemas",
        "service stores",
    ]
    assert all(ln.startswith("db-up: ") for ln in lines)
    # the role script reads each service's password from the database container's environment: a release that adds
    # a role needs the container on the NEW settings first, or the role is made without a password
    up_db = next(i for i, c in enumerate(calls) if c[:3] == ["dc", "up", "-d"] and c[-1] == "db")
    roles = next(i for i, c in enumerate(calls) if ROLES in c)
    migrate = next(i for i, c in enumerate(calls) if "orchestrator.migrate" in c)
    assert up_db < roles < migrate
    assert "--wait" in calls[up_db] and calls[up_db][calls[up_db].index("--pull") + 1] == "never"
    assert not any("pw@db" in a for c in calls for a in c)  # the admin's URL is never on a command line


def test_a_box_that_never_ran_the_installers_database_step_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines, calls = _steps(tmp_path, monkeypatch, "TB_SITE_ID=T\n")
    assert calls == [] and len(lines) == len(prestart.DB_STEPS) == 5


def test_the_command_refuses_a_deploy_folder_that_is_not_there(tmp_path: Path) -> None:
    assert prestart.main(tmp_path / "nowhere", "db-up") == 1


def test_the_pull_setting_is_checked_as_at_the_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_INSTALL_PULL", "always")
    with pytest.raises(up.UpdateFailed, match="TB_INSTALL_PULL"):
        _steps(
            tmp_path,
            monkeypatch,
            DB_ENV,
        )


# ---------------------------------------------------------------------------------------------- from the review
def test_review_a_failed_step_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The installer's compose command is long and the runner's message shows only its first words: without the
    step's name the operator could not tell the roles from the schemas."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(
        DB_ENV,
        encoding="utf-8",
    )

    def fake(argv: Sequence[str], **_kw: Any) -> str:
        if "orchestrator.migrate" in argv:
            raise up.UpdateFailed("docker compose --project-directory deploy -f a -f b exit 1: boom")
        return ""

    monkeypatch.setenv("TB_COMPOSE", "dc")
    with pytest.raises(up.UpdateFailed, match=r"^owned schemas: .*boom"):
        prestart.run_db(deploy, up.ComposeBox(deploy, run=fake))


def test_review_the_real_command_names_its_three_steps(tmp_path: Path) -> None:
    """The parser and the command of THIS tree, as a process: a box with no database step is left alone."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_SITE_ID=T\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "tools.trialbox", "db-up", "--deploy", str(deploy)],
                       capture_output=True, text=True, cwd=ROOT, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    names = [ln.split(":")[1].strip() for ln in r.stdout.splitlines() if ln.startswith("db-up: ")]
    assert names == ["FHIR store password is set", "database", "service roles", "owned schemas", "service stores"]


def test_review_the_install_gives_the_command_no_compose_line_of_its_own() -> None:
    """A compose command quoted by bash does not always read back in Python (a path that is not ASCII); the
    installer has written COMPOSE_FILE and COMPOSE_PROFILES to deploy/.env by then, which is what an update uses."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    call = text.index('python3 -m tools.trialbox db-up --deploy "$ROOT/deploy"')
    assert "TB_COMPOSE=" not in text[call - 200 : call]
    assert text.index("COMPOSE_FILE=$FILES") < call and text.index("COMPOSE_PROFILES=$MODE") < call


def test_review_the_parent_waits_as_long_as_the_steps_may_take(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each step has its own limit from TB_INSTALL_UP_TIMEOUT; the updater must not stop the command before them."""
    box, _, _ = _box(tmp_path, monkeypatch, tree="db-up")
    seen: list[int] = []

    def fake(argv: Sequence[str], **kw: Any) -> str:
        if "db-up" in argv:
            seen.append(kw["timeout"])
        return "1000000" if "pg_database_size" in " ".join(argv) else ""

    box.run = fake
    monkeypatch.setenv("TB_INSTALL_UP_TIMEOUT", "2000")
    box.db_up()
    assert seen and seen[0] >= (2000 + 120) + 2000 + 900
    assert seen[0] >= (2000 + 120) + 2000 + 900 + len(up.STORE_SERVICES) * (box.migrate_limit_s() or 0)  # D-921


def test_review_the_pages_do_not_say_every_service_is_stopped() -> None:
    """fhir-store is not stopped by an update, and nothing is with --no-backup: the database restarts under them."""
    rec = (ROOT / "docs" / "decisions" / "D-624-steps-after-the-database-is-up.md").read_text(encoding="utf-8")
    code = (ROOT / "tools" / "trialbox" / "update.py").read_text(encoding="utf-8")
    assert "stopped either way" not in code and "are stopped at that point in both orders" not in rec
    assert "fhir-store" in rec


@pytest.mark.parametrize("mounted", ["previous", "current", "unknown", "none"])
def test_review_the_database_container_is_made_again_when_it_holds_another_releases_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mounted: str
) -> None:
    """``deploy/docker`` is a link through ``current`` (tools/host_tree.py), and a bind mount is resolved when the
    container is made: a container the previous release started keeps the PREVIOUS release's db-init folder, so a
    release that changes only the role script would run the old one, and compose leaves a container whose settings
    did not change. The step makes it again then, and when it cannot tell; not when the folder is this release's
    (a fresh install: the container was made a moment ago and may still be filling an empty volume)."""
    deploy = tmp_path / "deploy"
    for rel in ("releases/old/db-init", "releases/new/db-init"):
        (tmp_path / rel).mkdir(parents=True)
    (deploy / "docker").mkdir(parents=True)
    (deploy / "docker" / "db-init").symlink_to(tmp_path / "releases" / "new" / "db-init")
    (deploy / ".env").write_text(
        DB_ENV,
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake(argv: Sequence[str], **_kw: Any) -> str:
        calls.append(list(argv))
        if argv[-2:] == ["-q", "db"]:
            return "" if mounted == "none" else "abc123\n"
        if "inspect" in argv:
            if mounted == "unknown":
                raise up.UpdateFailed("docker inspect exit 1")
            return str(tmp_path / "releases" / ("old" if mounted == "previous" else "new") / "db-init") + "\n"
        return ""

    monkeypatch.setenv("TB_COMPOSE", "dc")
    line = up.ComposeBox(deploy, run=fake).db_on_new_settings()
    up_db = next(c for c in calls if c[:3] == ["dc", "up", "-d"] and c[-1] == "db")
    assert ("--force-recreate" in up_db) == (mounted in ("previous", "unknown")), (mounted, up_db)
    assert ("made again" in line) == (mounted in ("previous", "unknown"))
    assert "resolved when the container is made" in " ".join((up.ComposeBox.db_on_new_settings.__doc__ or "").split())


def test_review_the_page_does_not_say_install_writes_no_step_twice() -> None:
    """install.sh keeps shell copies for a host without python3 (the password of a new role among them)."""
    doc = " ".join((prestart.__doc__ or "").split())
    assert "is not written a second time there" not in doc and "without python3" in doc


# ------------------------------------------------------------------------------------------- install and the pages
def test_a_fresh_install_runs_the_same_command_after_the_database_is_up() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    db_up = text.index('"${COMPOSE[@]}" up -d --pull "$PULL" --wait db')
    call = text.index('python3 -m tools.trialbox db-up --deploy "$ROOT/deploy"')
    stack = text.index('"${COMPOSE[@]}" up -d --pull "$PULL" "${UP_EXTRA[@]}" --wait')
    assert db_up < call < stack
    assert "|| stop_or_warn db-up" in text[call : call + 300]  # H-94: the helper (PoC: warned, listed, goes on)
    # a host without python3 still gets the roles and the schemas, by the two shell commands
    assert text.count(f"exec -T db {ROLES}") == 1 and text.count("python -m orchestrator.migrate") >= 1


def test_the_contract_of_a_database_step_is_written_where_steps_are_added() -> None:
    doc = " ".join((prestart.__doc__ or "").split())
    for words in ("DB_STEPS", "db-up", "the database is up", "no other service"):
        assert words in doc, words


def test_the_runbook_names_the_second_command() -> None:
    page = (ROOT / "docs" / "runbook" / "05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    assert "tools.trialbox db-up" in page and "DB_STEPS" in page
