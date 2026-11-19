"""W-2: runbook §27 followed alone, from the tag (``tools/runbook_workstation.py``).

These tests hold, on stand-ins (no GPU, no network, no Docker):

* the follower knows every command of §27's step table and nothing §27 no longer has (a guide change fails here until
  ``KNOWN`` says what the follower does with it);
* the checks of each step against the guide's "You should see";
* the follow: steps 1 to 11 in order, the tag's commit checked after step 8, a strict stop recorded with the guide's
  own "If not" command, the one lift on a rerun (the database image) recorded and marking the verdict, the mail lift;
* the record holds no secret (the start's once-shown password, a hub token); raw outputs are 0600;
* the module runs on the host's Python with the standard library only (the guide installs only python3-yaml).
"""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from tools import runbook_workstation as rw

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
TAG = "v1.0.0-rc1"
SHA = "a" * 40


# ------------------------------------------------------------------------------------------------ extraction
def test_the_follower_knows_every_command_of_section_27_and_no_other():
    unknown, gone = rw.diff()
    assert not unknown, [f"{c.line} step {c.step}: {c.text}" for c in unknown]
    assert not gone, gone
    assert rw.main(["diff"]) == 0


def test_extraction_rule_on_a_fixture(tmp_path):
    g = tmp_path / "guide.md"
    g.write_text(
        "# 27. X\n\n| # | Step | Type or click | You should see | If not |\n| --- | --- | --- | --- | --- |\n"
        "| 1 | A | `sudo apt install -y x`; open `http://127.0.0.1:1` | `24.04` | `deploy/poc.sh status` |\n"
        "| 2 | B | `python3 -m tools.x --a`, then without `--a` | `nvidia-smi` | – |\n"
        "Prose `deploy/poc.sh down` outside the table.\n",
        encoding="utf-8",
    )
    got = [(c.step, c.column, c.line, c.text) for c in rw.extract("guide.md", root=tmp_path)]
    assert got == [
        (1, "do", 5, "sudo apt install -y x"),
        (1, "else", 5, "deploy/poc.sh status"),
        (2, "do", 6, "python3 -m tools.x --a"),
        (2, "do", 6, "--a"),
        (2, "see", 6, "nvidia-smi"),
    ]
    assert rw.extract("guide.md", root=tmp_path)[3].fragment


def test_every_launcher_step_is_named_and_every_role_is_known():
    roles = {"run", "check", "host", "else", "manual", "fragment"}
    assert set(rw.KNOWN.values()) <= roles
    for (step, _text), role in rw.KNOWN.items():
        if role == "host":
            assert step in rw.LAUNCHER, step
    assert set(rw.MANUAL_STEPS) <= set(rw.LAUNCHER)
    titles = rw.step_titles()
    assert sorted(titles) == list(range(1, 16))
    for lift in rw.LIFTS:
        assert (ROOT / lift.source.split()[0]).is_file()


# ------------------------------------------------------------------------------------------------ checks
@pytest.mark.parametrize(
    ("out", "ok"),
    [
        (
            "name, memory.total [MiB], driver_version\nNVIDIA RTX PRO 6000 Blackwell Server Edition, 97887 MiB, 580.95.05",
            True,
        ),
        ("NVIDIA RTX 6000 Ada Generation, 49140 MiB, 580.95.05", False),
        ("NVIDIA RTX PRO 6000 Blackwell Max-Q, 49152 MiB, 580.95.05", False),
        ("NVIDIA A100, 81920 MiB", False),
    ],
)
def test_the_card_check(out, ok):
    assert (rw.check_card(out) == "") is ok


def test_the_driver_check():
    assert rw.check_driver("| NVIDIA-SMI 580.95.05   Driver Version: 580.95.05   CUDA Version: 13.0 |") == ""
    assert "580.65" in rw.check_driver("Driver Version: 575.57.08")
    assert rw.check_driver("No devices were found") != ""


def test_a_newer_compose_is_recorded_not_a_stop():
    assert rw.check_compose("Docker Compose version v5.0.1") == ""
    assert "v5.0" in rw.compose_note("Docker Compose version v5.0.1")
    assert rw.compose_note("Docker Compose version v2.40.3") == ""


def test_redact_drops_the_once_shown_password_and_a_hub_token():
    text = (
        "console: administrator 'admin' created (mailbox admin@hospa.test)\n"
        "console: password (shown once): Zq8rT2xLwP0v\nHF_TOKEN=hf_abcdefghijklmnopqrstu\nusing hf_abcdefghijk1234"
    )
    red = rw.redact(text)
    assert "Zq8rT2xLwP0v" not in red
    assert "hf_abcdefghij" not in red
    assert "administrator 'admin' created" in red


# ------------------------------------------------------------------------------------------------ the follow
GOOD = {
    "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv": "name, memory.total [MiB], driver_version\nNVIDIA RTX PRO 6000 Blackwell Server Edition, 97887 MiB, 580.95.05",
    "lsb_release -rs": "24.04\n",
    "nvidia-smi": "| NVIDIA-SMI 580.95.05   Driver Version: 580.95.05 |",
    "docker compose version": "Docker Compose version v2.40.3",
    "docker run --rm --gpus all ubuntu:24.04 nvidia-smi": "| 0 NVIDIA RTX PRO 6000 Blackwell Server Edition | 97887MiB |",
    "sh deploy/gpu_profile.sh": "rtxpro6000\n",
    "python3 -m tools.fetch_weights --profile rtxpro6000": "ok ...\nNext step: step 11",
    "python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only": "All present and pinned.",
    "TB_LLM_MODE=gpu deploy/poc.sh": "==> console administrator\nconsole: password (shown once): Zq8rT2xLwP0v\n==> done",
    "git rev-parse HEAD": SHA,
    f"git rev-list -n 1 {TAG}": SHA,
    "git status --porcelain": "",
}


class Machine:
    """A stand-in shell: each command's output from a table, the clone makes the folder, a list of what ran."""

    def __init__(self, work: Path, table: dict[str, str] | None = None, rc: dict[str, int] | None = None):
        self.work, self.table, self.rc, self.ran = work, {**GOOD, **(table or {})}, dict(rc or {}), []

    def __call__(self, cmd: str, cwd: Path, timeout: int) -> rw.Result:
        self.ran.append(cmd)
        if cmd.startswith("git clone"):
            (self.work / "Auto-GPT" / "trialbox").mkdir(parents=True)
        rc = self.rc.get(cmd, 0)
        if callable(rc):
            rc = rc()
        return rw.Result(rc, self.table.get(cmd, ""), 1.0)


def _follow(tmp_path, **kw):
    m = kw.pop("machine", None) or Machine(tmp_path)
    f = rw.Follower(TAG, tmp_path, run=m, root=ROOT, **kw)
    return f, f.follow(), m


def test_the_happy_path_walks_steps_1_to_11_in_order(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _, rec, m = _follow(tmp_path, raw_dir=raw)
    assert rec.stopped_at is None, rec.verdict
    assert rec.verdict.startswith("the guide alone installs the box")
    assert rec.checkout_commit == SHA
    steps = [s["step"] for s in rec.steps]
    assert steps == sorted(steps) and set(steps) == set(range(1, 12))
    assert f"git checkout {TAG}" in m.ran and "python3 -m tools.fetch_weights --profile rtxpro6000" in m.ran
    assert m.ran.index("python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run") < m.ran.index(
        "TB_LLM_MODE=gpu deploy/poc.sh"
    )
    # what the launcher did and what is left by hand are named
    assert any("step 5:" in n and "docs.docker.com" in n for n in rec.notes)
    assert [x["step"] for x in rec.manual] == [12, 13, 14, 15]
    # no secret in the record; the raw outputs are the owner's only
    blob = json.dumps(asdict(rec))
    assert "Zq8rT2xLwP0v" not in blob
    files = sorted(raw.iterdir())
    assert files and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files)
    assert any("Zq8rT2xLwP0v" in p.read_text() for p in files)
    assert rw.timings(rec)[0]["step"] == 1


def test_a_checkout_that_is_not_the_tag_stops_at_step_8(tmp_path):
    m = Machine(tmp_path, {f"git rev-list -n 1 {TAG}": "b" * 40})
    _, rec, _ = _follow(tmp_path, machine=m)
    assert rec.stopped_at == 8 and "not the tag" in rec.verdict
    assert not any("poc.sh" in c for c in m.ran)


def test_a_dirty_checkout_stops_at_step_8(tmp_path):
    _, rec, _ = _follow(tmp_path, machine=Machine(tmp_path, {"git status --porcelain": " M deploy/poc.sh"}))
    assert rec.stopped_at == 8 and "not clean" in rec.verdict


def test_step_1_without_a_driver_is_a_strict_stop(tmp_path):
    m = Machine(
        tmp_path,
        {"nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv": "bash: nvidia-smi: command not found"},
        rc={"nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv": 127},
    )
    _, rec, _ = _follow(tmp_path, machine=m)
    assert rec.stopped_at == 1 and "exited 127" in rec.verdict


def test_docker_without_the_group_names_step_6(tmp_path):
    m = Machine(
        tmp_path,
        {"docker info": "permission denied while trying to connect to the Docker daemon socket"},
        rc={"docker info": 1},
    )
    _, rec, _ = _follow(tmp_path, machine=m)
    assert rec.stopped_at == 6 and "sign out and in" in rec.verdict


def test_a_newer_compose_is_a_note(tmp_path):
    _, rec, _ = _follow(
        tmp_path, machine=Machine(tmp_path, {"docker compose version": "Docker Compose version v5.0.1"})
    )
    assert rec.stopped_at is None
    assert any("v5.0" in n for n in rec.notes)


DB_FAIL = "Error response from daemon: pull access denied for trialbox-postgres, repository does not exist"


def test_the_start_without_the_database_image_is_a_strict_stop_with_the_guides_status(tmp_path):
    m = Machine(
        tmp_path,
        {"TB_LLM_MODE=gpu deploy/poc.sh": DB_FAIL},
        rc={"TB_LLM_MODE=gpu deploy/poc.sh": 1, f"docker image inspect {rw.DB_IMAGE}": 1},
    )
    _, rec, _ = _follow(tmp_path, machine=m)
    assert rec.stopped_at == 11 and not rec.lifts
    assert m.ran[-1] == "deploy/poc.sh status"
    assert rec.verdict.startswith("the guide alone does not install the box: stopped at step 11")


def test_a_rerun_lifts_the_database_image_once_and_says_so(tmp_path):
    (tmp_path / "Auto-GPT" / "trialbox").mkdir(parents=True)
    starts = iter([1, 0])
    m = Machine(
        tmp_path,
        {"TB_LLM_MODE=gpu deploy/poc.sh": DB_FAIL},
        rc={"TB_LLM_MODE=gpu deploy/poc.sh": lambda: next(starts), f"docker image inspect {rw.DB_IMAGE}": 1},
    )
    _, rec, _ = _follow(tmp_path, machine=m, strict=False, rerun=True)
    assert not any(c.startswith("git clone") for c in m.ran)
    assert [x["key"] for x in rec.lifts] == ["db-image"]
    lift_at = m.ran.index(rw.LIFTS[0].command)
    assert m.ran[lift_at + 1 :].count("TB_LLM_MODE=gpu deploy/poc.sh") == 1
    assert rec.verdict == "the guide alone does not install the box: a lift was needed (see lifts)"
    assert rec.after_lifts_verdict == "after lifts, steps 1 to 11 passed"
    assert rec.steps[-1]["after_lifts"] is True


def test_no_lift_when_the_image_is_there(tmp_path):
    (tmp_path / "Auto-GPT" / "trialbox").mkdir(parents=True)
    m = Machine(
        tmp_path,
        {"TB_LLM_MODE=gpu deploy/poc.sh": "poc: the pair canary did not pass"},
        rc={"TB_LLM_MODE=gpu deploy/poc.sh": 1},
    )
    _, rec, _ = _follow(tmp_path, machine=m, strict=False, rerun=True)
    assert rec.stopped_at == 11 and not rec.lifts


def _mailhog(machine: Machine, per_send: list[list[list[str]]]):
    """A stand-in web-mail API: after the k-th test mail is sent, the replies of per_send[:k] are in the mailbox."""

    def fetch(url: str) -> bytes:
        sent = sum(1 for c in machine.ran if "send_test_mail.py" in c)
        replies = [names for batch in per_send[:sent] for names in batch]
        items = [
            {
                "ID": f"m{i}",
                "Content": {"Headers": {"To": [rw.ADMIN_MAIL]}},
                "MIME": {
                    "Parts": [{"Headers": {"Content-Disposition": [f'attachment; filename="{n}"']}} for n in names]
                },
            }
            for i, names in enumerate(replies)
        ]
        return json.dumps({"items": items}).encode()

    return fetch


def test_the_mail_lift_reads_the_replies(tmp_path):
    (tmp_path / "Auto-GPT" / "trialbox").mkdir(parents=True)
    m = Machine(tmp_path)
    fetch = _mailhog(m, [[["feasibility.pdf", "feasibility.xlsx"]], [["screened.xlsx", "summary.pdf"], []]])
    _, rec, _ = _follow(tmp_path, machine=m, strict=False, rerun=True, mail=True, fetch=fetch, sleep=lambda s: None)
    assert any("send_test_mail.py" in c and "FEAS GZQO" in c for c in m.ran)
    mail = [s for s in rec.steps if "replies" in s]
    assert [(s["step"], s["replies"]) for s in mail] == [(13, 1), (14, 2)]
    assert rec.after_lifts_verdict == ""
    assert [x["step"] for x in rec.manual] == [12, 15]


def test_the_mail_lift_without_a_reply_stops(tmp_path):
    (tmp_path / "Auto-GPT" / "trialbox").mkdir(parents=True)
    m = Machine(tmp_path)
    _, rec, _ = _follow(
        tmp_path,
        machine=m,
        strict=False,
        rerun=True,
        mail=True,
        fetch=_mailhog(m, []),
        sleep=lambda s: None,
        mail_wait=0,
    )
    assert "stopped at step 13" in rec.after_lifts_verdict


# ------------------------------------------------------------------------------------------------ preflight, CLI
def _args(tmp_path, **kw):
    import argparse

    base = {"tag": TAG, "work": str(tmp_path), "strict": True, "rerun": False, "mail": False}
    return argparse.Namespace(**{**base, **kw})


def _ok(cmd, cwd, timeout):
    return rw.Result(0, "", 0.0)


def test_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(rw.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(rw.os, "geteuid", lambda: 1000, raising=False)
    assert rw.preflight(_args(tmp_path), run=_ok) == []
    monkeypatch.setattr(rw.os, "geteuid", lambda: 0, raising=False)
    assert any("not as root" in w for w in rw.preflight(_args(tmp_path), run=_ok))
    monkeypatch.setattr(rw.os, "geteuid", lambda: 1000, raising=False)
    assert any("--mail is a lift" in w for w in rw.preflight(_args(tmp_path, mail=True), run=_ok))
    assert any("not both" in w for w in rw.preflight(_args(tmp_path, rerun=True), run=_ok))
    assert any("not a tag" in w for w in rw.preflight(_args(tmp_path, tag="v1; rm -rf /"), run=_ok))
    (tmp_path / "Auto-GPT").mkdir()
    assert any("empty working folder" in w for w in rw.preflight(_args(tmp_path), run=_ok))
    monkeypatch.setattr(rw.platform, "machine", lambda: "aarch64")
    assert any("not W-2's" in w for w in rw.preflight(_args(tmp_path, strict=False, rerun=True), run=_ok))


def test_the_module_needs_only_the_standard_library_and_python_310():
    src = (ROOT / "tools/runbook_workstation.py").read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 10))
    assert "datetime" not in src  # datetime.UTC is 3.11+ (lane J's fault in pin_model under 22.04)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUNBUFFERED", "PYTHONPATH")}
    p = subprocess.run(
        [sys.executable, "-S", "-c", "import tools.runbook_workstation"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert p.returncode == 0, p.stderr


def test_the_cli_plan_and_extract_run_without_pythonunbuffered():
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    for sub in (["plan"], ["extract", "--json"], ["diff"]):
        p = subprocess.run(
            [sys.executable, "-m", "tools.runbook_workstation", *sub],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert p.returncode == 0, p.stderr
    assert (
        "db-image"
        in subprocess.run(
            [sys.executable, "-m", "tools.runbook_workstation", "plan"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout
    )


def test_follow_refuses_root_before_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rw.os, "geteuid", lambda: 0, raising=False)
    rc = rw.main(["follow", "--tag", TAG, "--out", str(tmp_path / "r.json"), "--work", str(tmp_path / "w")])
    assert rc == 2 and not (tmp_path / "r.json").exists()
    assert "not as root" in capsys.readouterr().err
