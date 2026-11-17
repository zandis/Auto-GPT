"""H-19 (D-1105): the GPU driver names the qualification record's code by the installed release's commit.

H-15's finding F1: on every driver route the record's code was ``image:<id>`` (the box has no git), while the three
evidence gates (``n12``, ``public_e2e``, ``goldens``: ``tools.qualify.step_evidence``) compare the evidence files'
git commit with the record's code, so no full qualify through the driver could pass. The integrator kept the gates on
the git sha; lane D's installer now records ``commit`` beside ``dirty`` in ``deploy/updates/installed.json`` (D-994).

The driver (``deploy/gcp/box-install-run.sh``, ``code_commit``) reads it with ``box_vm.py installed-commit``: 40
lowercase hex and ``dirty: false`` only. ``dirty: true``, a null, missing or malformed commit are refused by name
(non-zero, the reason on stderr). It hands the commit to qualify as ``TB_CODE_COMMIT`` beside ``TB_CODE_IMAGE``;
``tools.code_identity`` names the code by it, and the serving record keeps the image id beside it. The last test runs
that route, the driver's own shell function and helper, and the three gates as they are. Synthetic data only."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from tests.unit.test_n12_screen import BIG
from tools import code_identity as ci
from tools import n12_screen as n12
from tools import qualify as q

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "deploy" / "gcp" / "box-install-run.sh"
VM = ROOT / "deploy" / "gcp" / "box_vm.py"
SHA = "0123456789abcdef0123456789abcdef01234567"
IMAGE_ID = "sha256:" + "e" * 64


def _installed(tmp: Path, doc: object) -> Path:
    p = tmp / "box" / "deploy" / "updates" / "installed.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return p


def _helper(path: Path) -> subprocess.CompletedProcess[str]:
    """``vm installed-commit`` as the driver calls it: the VM's python3 and the helper, standard library only."""
    cmd = [sys.executable, str(VM), "installed-commit", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_a_clean_commit_is_printed_alone(tmp_path: Path) -> None:
    p = _helper(_installed(tmp_path, {"release_seq": 3, "commit": SHA, "dirty": False}))
    assert p.returncode == 0 and p.stdout == SHA + "\n" and p.stderr == ""


@pytest.mark.parametrize(
    ("doc", "named"),
    [
        ({"commit": SHA, "dirty": True}, "dirty: true"),
        ({"commit": None, "dirty": False}, "commit: null"),
        ({"dirty": False}, "commit: missing"),
        ({"commit": SHA.upper(), "dirty": False}, "commit: malformed"),
        ({"commit": SHA[:39], "dirty": False}, "commit: malformed"),
        ({"commit": SHA + "0", "dirty": False}, "commit: malformed"),
        ({"commit": SHA + " ", "dirty": False}, "commit: malformed"),
        ({"commit": "image:" + IMAGE_ID, "dirty": False}, "commit: malformed"),
        ({"commit": 7, "dirty": False}, "commit: malformed"),
        ({"commit": [SHA], "dirty": False}, "commit: malformed"),
        ({"commit": SHA}, "dirty: null"),
        ({"commit": SHA, "dirty": "false"}, 'dirty: "false"'),
        ([SHA], "not a JSON object"),
        ("{not json", "unreadable"),
    ],
)
def test_each_bad_record_is_refused_by_name(tmp_path: Path, doc: object, named: str) -> None:
    p = _helper(_installed(tmp_path, doc))
    assert p.returncode == 1 and p.stdout == ""
    assert p.stderr.startswith("installed-commit refused: ") and named in p.stderr


def test_a_box_with_no_installed_record_is_refused(tmp_path: Path) -> None:
    p = _helper(tmp_path / "deploy" / "updates" / "installed.json")
    assert p.returncode == 1 and p.stdout == "" and "missing (no installed release on this box)" in p.stderr


def test_dirty_is_named_before_the_commit(tmp_path: Path) -> None:
    """A dirty release whose commit is also unusable is refused as dirty first: dirty is what keeps it out."""
    p = _helper(_installed(tmp_path, {"commit": None, "dirty": True}))
    assert p.returncode == 1 and "dirty: true" in p.stderr and "commit" not in p.stderr.split("json: ", 1)[1]


# ---------------------------------------------------------------- the driver's shell function, run as it is
def _code_commit_fn() -> str:
    text = DRIVER.read_text(encoding="utf-8")
    m = re.search(r"^CODE_ENV=\(\)\ncode_commit\(\) \{[^\n]*\n.*?^\}\n", text, re.S | re.M)
    assert m, "box-install-run.sh: code_commit not found"
    return m.group(0)


def _driver(tmp: Path, installed: Path | None, arg: str) -> tuple[int, list[str], str, str, str]:
    """``code_commit [record]`` from the driver, with its own ``vm`` (the helper) and ``note``: the exit, CODE_ENV,
    STOP, the part's notes and the step log."""
    box = installed.parents[2] if installed else tmp / "nobox"
    notes, log = tmp / "notes", tmp / "step.log"
    script = (
        f'PY={sys.executable}; HELPER={VM}; BOXROOT={box}; NOTES={notes}; STEP_LOG={log}; STOP=""\n'
        'vm() { "$PY" "$HELPER" "$@"; }\n'
        'note() { printf \'%s\\t%s\\n\' "$1" "$2" >> "$NOTES"; }\n'
        + _code_commit_fn()
        + f'code_commit {arg}; rc=$?\nprintf "%s\\n" "$rc" "STOP=$STOP" ${{CODE_ENV[@]+"${{CODE_ENV[@]}}"}}\n'
    )
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    out = p.stdout.splitlines()
    return int(out[0]), out[2:], out[1].removeprefix("STOP="), _text(notes), _text(log)


def _text(f: Path) -> str:
    return f.read_text(encoding="utf-8") if f.exists() else ""


def test_the_driver_hands_a_clean_commit_to_qualify(tmp_path: Path) -> None:
    rc, env, stop, notes, _ = _driver(tmp_path, _installed(tmp_path, {"commit": SHA, "dirty": False}), "record")
    assert (rc, env, stop) == (0, ["-e", f"TB_CODE_COMMIT={SHA}"], "")
    assert f'code_commit\t"{SHA}"' in notes


@pytest.mark.parametrize(
    ("doc", "named"),
    [
        ({"commit": SHA, "dirty": True}, "dirty: true"),
        ({"commit": None, "dirty": False}, "commit: null"),
        ({"dirty": False}, "commit: missing"),
        ({"commit": "abc", "dirty": False}, "commit: malformed"),
        (None, "missing (no installed release on this box)"),
    ],
)
def test_the_driver_stops_a_record_run_on_each_refusal(tmp_path: Path, doc: object, named: str) -> None:
    installed = None if doc is None else _installed(tmp_path, doc)
    rc, env, stop, notes, log = _driver(tmp_path, installed, "record")
    assert rc == 1 and env == []
    assert stop.startswith("TB-CODE-COMMIT-REFUSED: the record names its code by the installed release's commit")
    assert named in stop and named in notes and "TB-CODE-COMMIT-REFUSED: " in log


def test_a_measurement_without_evidence_runs_on_named_by_the_image(tmp_path: Path) -> None:
    """Validation mode without evidence (and G-10): the refusal is noted; qualify runs with TB_CODE_IMAGE alone."""
    rc, env, stop, notes, _ = _driver(tmp_path, _installed(tmp_path, {"commit": SHA, "dirty": True}), "")
    assert (rc, env, stop) == (0, [], "") and "code_commit_refused\t" in notes and "dirty: true" in notes


def test_the_driver_wires_it_where_qualify_runs() -> None:
    text = DRIVER.read_text(encoding="utf-8")
    d_qualify = text[text.index("d_qualify() {") : text.index("\n}\n", text.index("d_qualify() {"))]
    beside = d_qualify[d_qualify.index("TB_CODE_IMAGE=") :]
    assert beside.index('${CODE_ENV[@]+"${CODE_ENV[@]}"}') < beside.index("trialbox eval qualify")
    step = text[text.index("step_qualify() {") : text.index("\n}\n", text.index("step_qualify() {"))]
    assert 'if [ "$MODE" = validation ] && [ -z "$QEVIDENCE" ]; then code_commit; else code_commit record' in step
    assert step.index("code_commit") < step.index("d_qualify")
    g10 = text[text.index("step_g10_qualify() {") : text.index("\n}\n", text.index("step_g10_qualify() {"))]
    assert g10.index("code_commit") < g10.index("d_qualify")


# ---------------------------------------------------------------- the code identity qualify reads in the image
@pytest.mark.parametrize("bad", ["abc", SHA.upper(), SHA + "0", "image:" + IMAGE_ID])
def test_code_identity_takes_only_a_40_hex_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.delenv("TB_RELEASE_TREE", raising=False)
    monkeypatch.setenv("TB_CODE_IMAGE", IMAGE_ID)
    monkeypatch.setenv("TB_CODE_COMMIT", SHA)
    assert ci.head(tmp_path) == (SHA, False)
    monkeypatch.setenv("TB_CODE_COMMIT", bad)
    assert ci.head(tmp_path) == ("unknown", True)
    monkeypatch.delenv("TB_CODE_COMMIT")
    assert ci.head(tmp_path) == (f"image:{IMAGE_ID}", False)  # D-881's route, as before


# ---------------------------------------------------------------- the route, end to end at function level
def _ctx(evidence: dict[str, Path], tmp: Path) -> q.Ctx:
    opts = q.Options(profile="rtxpro6000", stub=False, operator="lane-g-box-run", sources=("synthetic",),
                     evidence=evidence)  # fmt: skip
    return q.Ctx(opts, cast(q.Target, None), {}, cast(q.QClient, None), cast(q.QClient, None), tmp, io.StringIO())


def test_a_driver_route_record_passes_the_three_evidence_gates_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The box: installed.json as the installer writes it (D-994); /app with no git and no release tree. The driver's
    ``code_commit`` reads it; qualify gets CODE_ENV beside the image id and the poc profile, as d_qualify passes them.
    The evidence: n12 as ``tools.n12_screen`` writes it on that commit, public_e2e and goldens naming it. The gates
    (``step_evidence``) and ``git_head`` run as they are; only ROOT is the image's /app."""
    installed = _installed(tmp_path, {"release_seq": 3, "bundle_id": "2026.11-r", "commit": SHA, "dirty": False})
    rc, env, stop, _, _ = _driver(tmp_path, installed, "record")
    assert rc == 0 and stop == ""
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(q, "ROOT", app)
    monkeypatch.delenv("TB_RELEASE_TREE", raising=False)
    monkeypatch.setenv("TB_HOST_PROFILE", "poc")
    monkeypatch.setenv("TB_CODE_IMAGE", IMAGE_ID)
    for i in range(0, len(env), 2):
        assert env[i] == "-e"
        k, v = env[i + 1].split("=", 1)
        monkeypatch.setenv(k, v)

    head, dirty = q.git_head()
    assert (head, dirty) == (SHA, False) and q.code_problems(head, {"TB_HOST_PROFILE": "poc"}) == []
    assert q.code_problems(head, {}) == [] and q.code_note(head) == ""  # a commit, not an image: no poc exception

    score = tmp_path / "score.json"
    run = {"head": SHA, "models": {"judge": "j-build-1", "verifier": "v-build-1"}, "stub": False}
    score.write_text(json.dumps({"set": "trec", "pairs": {"rows": BIG}, "run": run}), "utf-8")
    ev: dict[str, Path] = {"n12": tmp_path / "n12.json"}
    ev["n12"].write_text(json.dumps(n12.evidence([score], head=SHA)), "utf-8")
    for name in ("public_e2e", "goldens"):
        ev[name] = tmp_path / f"{name}.json"
        ev[name].write_text(json.dumps({"passed": True, "head": SHA}), "utf-8")

    for name in ("n12", "public_e2e", "goldens"):
        r = q.step_evidence(name)(_ctx(ev, tmp_path))
        assert r.status == "passed", (name, r.reason)
        assert r.detail["head"] == SHA

    # the same route named by the image alone (before H-19) fails every one of them: the evidence is from a commit
    monkeypatch.delenv("TB_CODE_COMMIT")
    for name in ("n12", "public_e2e", "goldens"):
        r = q.step_evidence(name)(_ctx(ev, tmp_path))
        assert r.status == "failed" and "not this HEAD" in r.reason


def test_the_serving_record_keeps_the_image_id_beside_the_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """serving_record on the driver's route: git_head is the commit, ``code_image`` the image id, no code problem."""
    monkeypatch.setattr(ci, "_git", lambda *_a: (128, ""))  # the image's /app: no git
    monkeypatch.delenv("TB_RELEASE_TREE", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setenv("TB_HOST_GPU", json.dumps({"driver": "580.65.06", "cuda": "13.0", "gpu": "synthetic"}))
    monkeypatch.setenv("TB_HOST_PROFILE", "poc")
    monkeypatch.setenv("TB_CODE_IMAGE", IMAGE_ID)
    monkeypatch.setenv("TB_CODE_COMMIT", SHA)
    ctx = _ctx({}, Path("."))
    ctx.builds["judge"] = cast(q.Build, type("B", (), {"build_id": "synthetic-judge"})())
    r = q.step_serving_record(ctx)
    assert r.detail["git_head"] == SHA and r.detail["git_dirty"] is False and r.detail["code_image"] == IMAGE_ID
    assert "code" not in r.detail and "release tree" not in r.reason and "git" not in r.reason
    monkeypatch.delenv("TB_CODE_COMMIT")  # D-881's route as before: the image names the code, no code_image
    r = q.step_serving_record(ctx)
    assert r.detail["git_head"] == f"image:{IMAGE_ID}" and "code_image" not in r.detail
