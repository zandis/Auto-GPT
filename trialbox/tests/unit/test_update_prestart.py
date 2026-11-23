"""UPDATE-PRESTART: the steps a release runs on the host before its stack starts are run by the NEW release.

``tools/apply_update.sh`` starts the installed release's updater. It switches the box to the new tree and then
restarted the stack from the same old process: the pre-start steps were the old release's, the compose files the
new one's. A step a release added (a new secret file, a role script) first ran on the update after the one that
brought it, and the update that brought it failed and rolled back. Now the restart runs the new tree's
``python3 -m tools.trialbox pre-start`` as a process of its own."""

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

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

NEW_RELEASE = '''"""A later release's pre-start: it has a step the installed release never heard of."""
import sys
from pathlib import Path

deploy = Path(sys.argv[sys.argv.index("--deploy") + 1])
if (deploy / "FAIL").exists():
    print("pre-start: the new step failed", file=sys.stderr)
    raise SystemExit(1)
(deploy / "secrets").mkdir(exist_ok=True)
(deploy / "secrets" / "new-in-this-release.key").write_text("made by the new release")
with (deploy / ".env").open("a") as fh:
    fh.write("TB_NEW_SETTING=1\\n")
print("pre-start: new-in-this-release.key made")
'''


class Run:
    """The updater's runner: records every command; runs the pre-start command for real, nothing else."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], **_kw: Any) -> str:
        self.calls.append(list(argv))
        if "pre-start" in argv:
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            r = subprocess.run(list(argv), capture_output=True, text=True, env=env, check=False)
            if r.returncode != 0:
                raise up.UpdateFailed(r.stderr.strip())
            return r.stdout
        return ""


def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, new_tree: bool) -> tuple[up.ComposeBox, Run, Path]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_SITE_ID=T\n", encoding="utf-8")
    if new_tree:  # what apply_host leaves: the install folder's tools/ is the new release's
        pkg = tmp_path / "tools" / "trialbox"
        pkg.mkdir(parents=True)
        (tmp_path / "tools" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "prestart.py").write_text("", encoding="utf-8")
        (pkg / "__main__.py").write_text(NEW_RELEASE, encoding="utf-8")
    monkeypatch.setenv("TB_COMPOSE", "dc")
    run = Run()
    return up.ComposeBox(deploy, run=run), run, deploy


def _plan(tmp_path: Path) -> Any:
    return up.Plan(bundle_id="B1", manifest_sha256="0" * 64, signer="t", files=[], stage=tmp_path / "stage")


def test_the_new_trees_steps_run_before_the_stack_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box, run, deploy = _box(tmp_path, monkeypatch, new_tree=True)
    monkeypatch.setattr(box, "resolve_pins", lambda: pytest.fail("the old release's own step ran"))
    monkeypatch.setattr(box, "ensure_model_key", lambda: pytest.fail("the old release's own step ran"))
    box.restart(_plan(tmp_path))
    lines = [" ".join(c) for c in run.calls]
    pre = next(n for n, ln in enumerate(lines) if "-m tools.trialbox pre-start" in ln)
    start = next(n for n, ln in enumerate(lines) if ln.startswith("dc up -d"))
    assert pre < start
    assert str(tmp_path) in run.calls[pre] and "--deploy" in run.calls[pre]  # in the install folder, on this deploy
    assert (deploy / "secrets" / "new-in-this-release.key").read_text() == "made by the new release"
    assert box.env["TB_NEW_SETTING"] == "1"  # what the step wrote to .env is what the rest of the update reads


def test_a_failed_step_stops_the_update_before_the_stack_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, run, deploy = _box(tmp_path, monkeypatch, new_tree=True)
    (deploy / "FAIL").write_text("", encoding="utf-8")
    with pytest.raises(up.UpdateFailed, match="the new step failed"):
        box.restart(_plan(tmp_path))
    assert not any(c[:2] == ["dc", "up"] for c in run.calls)


def test_a_tree_from_before_the_command_gets_the_steps_it_always_got(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A downgrade to a release without ``pre-start``, and every test box without a tree: the two steps of the
    releases before this one, in this process, as before."""
    box, run, _deploy = _box(tmp_path, monkeypatch, new_tree=False)
    ran: list[str] = []
    monkeypatch.setattr(box, "resolve_pins", lambda: ran.append("pins"))

    def key() -> bool:
        ran.append("key")
        return False

    monkeypatch.setattr(box, "ensure_model_key", key)
    box.restart(_plan(tmp_path))
    assert ran == ["pins", "key"] and not any("pre-start" in c for c in run.calls)
    assert any(c[:2] == ["dc", "up"] for c in run.calls)


def test_this_releases_command_runs_its_steps_and_names_them(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_SITE_ID=T\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    r = subprocess.run([sys.executable, "-m", "tools.trialbox", "pre-start", "--deploy", str(deploy)], cwd=ROOT,
                       capture_output=True, text=True, env=env, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    for name, _fn in prestart.STEPS:
        assert f"pre-start: {name}" in r.stdout, r.stdout
    assert [n for n, _ in prestart.STEPS][:2] == ["image pins", "model key"]


def test_review_a_relative_deploy_folder_still_reaches_the_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command changes into the install folder first; a relative ``--deploy`` then named a folder that is not
    there, every step found nothing to do, and the update went on without them."""
    _, run, deploy = _box(tmp_path, monkeypatch, new_tree=True)
    monkeypatch.chdir(tmp_path.parent)
    rel = up.ComposeBox(Path(tmp_path.name) / "deploy", run=run)
    rel.restart(_plan(tmp_path))
    pre = next(c for c in run.calls if "pre-start" in c)
    assert str(deploy) in pre and str(tmp_path) in pre  # absolute, both
    assert (deploy / "secrets" / "new-in-this-release.key").exists()


def test_review_the_command_refuses_a_deploy_folder_that_is_not_there(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    r = subprocess.run([sys.executable, "-m", "tools.trialbox", "pre-start", "--deploy", str(tmp_path / "none")],
                       cwd=ROOT, capture_output=True, text=True, env=env, check=False)  # fmt: skip
    assert r.returncode == 1 and "no deploy folder" in r.stderr


def test_review_the_operator_reads_the_steps_and_a_short_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box, _run, deploy = _box(tmp_path, monkeypatch, new_tree=True)
    box.restart(_plan(tmp_path))
    assert "pre-start: new-in-this-release.key made" in capsys.readouterr().out  # the child's lines are shown
    (deploy / "FAIL").write_text("", encoding="utf-8")
    with pytest.raises(up.UpdateFailed) as exc:
        box.restart(_plan(tmp_path))
    assert str(exc.value).startswith("pre-start") and "sh -c" not in str(exc.value)  # the reason, not the command
    assert box.env.get("TB_NEW_SETTING") == "1"  # .env is read again after a failure too


def test_review_a_fresh_install_runs_the_same_steps_before_its_stack_starts() -> None:
    """A step that is only in STEPS would be skipped by every fresh install: install.sh runs the command too."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    call = text.index('python3 -m tools.trialbox pre-start --deploy "$ROOT/deploy"')
    assert call < text.index('"${COMPOSE[@]}" up -d --pull "$PULL" --wait db')
    assert "|| stop_or_warn pre-start" in text[call : call + 300]  # H-94: the helper (PoC: warned, listed, goes on)


def test_review_the_contract_of_a_step_is_written_where_steps_are_added() -> None:
    doc = prestart.__doc__ or ""
    for words in ("safe to run again", "stack down", "harmless to the previous release", "install.sh"):
        assert words in " ".join(doc.split()), words


def test_the_runbook_says_where_a_release_puts_a_new_step() -> None:
    page = (ROOT / "docs" / "runbook" / "05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    assert "tools/trialbox/prestart.py" in page and "min_installed_version" in page
