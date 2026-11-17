"""H-22 (D-1136): the install runbook, followed alone.

``tools/runbook_install.py`` reads RUNBOOK §1 and the hub, extracts the commands a reader is told to run, and follows
the install path on a machine with only the bundle and what the runbook tells the reader to bring. These tests hold:

* the extraction rule, on a fixture and on §1 (the same list ``test_runbook_install_commands.commands()`` covers, now
  with each command's place and the sentence that introduces it);
* the install path: every quote that makes a step is still in the runbook, and every other command of §1 has a reason
  it is not on the path;
* the committed findings file (``docs/plan/measurements/runbook-install-2026-11-17/findings.json``): every finding
  quotes the runbook as it is; every static finding is still shown by the text and no new one is; the follower, run here
  on the unit machine (a folder for ``/opt``, a stand-in ``docker`` that serves nothing past the host checks, a signed
  bundle holding this checkout's host tree), shows exactly the committed findings of the machine ``unit`` for the steps
  it reached. A runbook fix makes this fail until the file says the finding is gone; a new silence makes it fail until
  the file holds it. The container run (``make runbook-install``) is compared the same way to the machine
  ``container``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_runbook_install_commands as t632
from tools import host_tree as ht
from tools import runbook_install as ri
from tools.sign_bundle import build, keygen, sign_file

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "docs/plan/measurements/runbook-install-2026-11-17/run-container.json"

STAND_IN_DOCKER = """import sys
a = sys.argv[1:]
if a[:1] in (["info"], ["version"]) or a[:2] == ["compose", "version"]:
    print("29.0.0")
    sys.exit(0)
if "ls" in a or "ps" in a:
    sys.exit(0)
print("runbook-follower stand-in: docker " + " ".join(a[:3]) + " is not served here", file=sys.stderr)
sys.exit(1)
"""


# ------------------------------------------------------------------------------------------------ extraction
FIXTURE = """# 9. X

**Reader:** hospital IT.

**One thing.** Run `sudo deploy/x.sh a.tar
--yes` first. The file `deploy/x.yaml` is a path, not a command. Then `--mode b` for another case.

1. **Step.** `python -m tools.y --z` or
   ```sh
   make q \\
     R=1
   # a comment
   docker compose up
   ```
2. **Other.** `cd deploy && docker compose ps`; nothing else.
"""


def test_the_extraction_rule_on_a_fixture(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text(FIXTURE, encoding="utf-8")
    got = ri.extract("x.md", tmp_path)
    assert [(c.line, c.text) for c in got] == [
        (5, "sudo deploy/x.sh a.tar --yes"),  # wraps a line; placed at its opening backtick
        (6, "--mode b"),  # a fragment
        (8, "python -m tools.y --z"),
        (10, "make q R=1"),  # a fenced logical line joined at the backslash
        (13, "docker compose up"),  # the comment line is not a command
        (15, "cd deploy && docker compose ps"),
    ]
    assert [c.fragment for c in got] == [False, True, False, False, False, False]
    assert got[0].block == "One thing" and got[0].step is None
    assert got[0].prose == "Run `sudo deploy/x.sh a.tar --yes` first."
    assert got[2].block == "One thing / 1. Step" and got[2].step == 1
    assert got[5].step == 2 and got[5].prose == "`cd deploy && docker compose ps`;"


def test_the_extraction_matches_the_section_1_commands_test() -> None:
    """The same rule as T-632's ``commands()``: one list, now with places."""
    assert [c.text for c in ri.all_commands()] == t632.commands()


def test_every_command_is_placed_on_its_own_line() -> None:
    lines = (ROOT / ri.SECTION).read_text(encoding="utf-8").splitlines()
    for c in ri.all_commands():
        first = c.text.split()[0]
        assert f"`{first}" in lines[c.line - 1], (c.place, c.text)
        assert c.text.split()[0] in c.prose or c.prose == "(fenced block)", (c.place, c.prose)


def test_the_hub_says_where_and_as_whom() -> None:
    assert ri.convention() == ("/opt/trialbox", "root")


# ------------------------------------------------------------------------------------------------ the path
@pytest.mark.parametrize("key", [s.key for s in ri.PLAN])
def test_each_step_of_the_path_is_the_runbook_s_own(key: str) -> None:
    s = next(s for s in ri.PLAN if s.key == key)
    text = ri._fold((ROOT / s.file).read_text(encoding="utf-8"))
    assert ri._fold(s.quote) in text, f"{key}: the runbook no longer says {s.quote!r}: re-read the path (D-1136)"
    if s.action == "run":
        assert s.command in [c.text for c in ri.all_commands()], key
    if s.in_block:  # the installer's step: the one command's paragraph says the installer does it
        assert ri._fold(s.quote) in ri._block(ROOT, s.in_block), f"{key}: the quote is not in {s.in_block}"
    elif s.step is not None:
        assert ri._fold(s.quote) in ri._step(ROOT, s.step), f"{key}: the quote is not in step {s.step}"


def test_every_command_off_the_path_has_the_runbook_s_reason() -> None:
    off = ri.not_needed(ri.all_commands())
    assert off and not [o for o in off if o["why"] == "no reason in the runbook"]
    assert len(off) + len(ri.path_commands(ri.all_commands())) == len(ri.all_commands())


# ------------------------------------------------------------------------------------------------ findings
def test_the_committed_findings_quote_the_runbook_as_it_is() -> None:
    committed = ri.load_findings()
    assert committed and len({f["id"] for f in committed}) == len(committed)
    assert ri.quote_problems(committed) == []
    for f in committed:
        assert f["kind"] in ("wrong", "silent") and f["severity"] in (
            "stops the install",
            "slows the reader",
            "cosmetic",
        ), f["id"]
        assert set(f["seen_on"]) <= {"unit", "container", "vm"}, f["id"]


def test_the_static_findings_are_the_committed_ones() -> None:
    held = {f["id"] for f in ri.load_findings() if f.get("static")}
    assert set(ri.static_findings()) == held, "a runbook change moved a finding: update the findings file (D-1136)"


def _unit_machine(tmp: Path) -> tuple[ri.LocalMachine, Path, Path]:
    """The stick as the vendor hands it over (D-996): the bundle (this checkout's host tree, a throwaway key), its
    .sha256 naming each file bare as make_bundle.sh writes it, the bootstrap and its raw signature."""
    priv, pub = keygen(tmp / "vendor")
    stick = tmp / "stick"
    stick.mkdir()
    ht.pack(ROOT, tmp / "host.tar")
    bundle = stick / "trialbox-2026.11-runbook.tar"
    build(priv, "2026.11-runbook", [("host", tmp / "host.tar", ht.HOST_TAR)], bundle, release_seq=1)
    shutil.copy(ROOT / "deploy/bootstrap.sh", stick / "trialbox-bootstrap.sh")
    sign_file(priv, stick / "trialbox-bootstrap.sh")
    names = [bundle.name, "trialbox-bootstrap.sh", "trialbox-bootstrap.sh.sig"]
    sums = "".join(f"{hashlib.sha256((stick / n).read_bytes()).hexdigest()}  {n}\n" for n in names)
    (stick / f"{bundle.name}.sha256").write_text(sums, encoding="utf-8")
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(f"#!{sys.executable}\n{STAND_IN_DOCKER}", encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    (tmp / "opt").mkdir()
    path = f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin"
    m = ri.LocalMachine(
        tmp / "opt",
        path,
        name="unit",
        stand_in_markers=("runbook-follower stand-in", "the bundle carried no trialbox-py"),
    )
    return m, bundle, pub


@pytest.fixture(autouse=True)
def _the_real_machine_is_untouched() -> Iterator[None]:
    """The unit machine is a folder: nothing the follower runs may reach this machine's own /opt/trialbox (an inner
    `sudo` resets the environment and would take the bootstrap there; the follower drops it, as root)."""
    real = [Path(p).exists() for p in ("/opt/trialbox", "/root/site", "/srv/his-export")]
    yield
    assert [Path(p).exists() for p in ("/opt/trialbox", "/root/site", "/srv/his-export")] == real


def test_the_follower_on_the_unit_machine_shows_the_committed_findings(tmp_path: Path) -> None:
    m, bundle, pub = _unit_machine(tmp_path)
    rec = ri.Follower(m, bundle=bundle, vendor_pub=pub, work=tmp_path / "work").follow()
    run = json.loads(json.dumps(asdict(rec)))
    # it ran and recorded: the one command as written (with --mode stub in place of --tier: no GPU here, §1:44)
    one = [s for s in rec.steps if s.get("step") == "one-command"]
    assert len(one) == 1 and one[0]["as_written"] == ri.ONE_COMMAND and one[0]["after_lifts"] == []
    assert "--mode stub" in one[0]["ran"] and "--tier" not in one[0]["ran"] and not one[0]["ran"].startswith("sudo")
    out = one[0]["out"]
    assert "Signature Verified Successfully" in out and "unpacked: the release's host tree" in out
    assert "placed: the vendor key" in out and "running: " in out and "==> bundle: verify and load" in out
    assert (tmp_path / "opt/trialbox/deploy/keys/vendor_ed25519.pub").read_bytes() == pub.read_bytes()
    assert {x["to"] for x in rec.supplied} >= {ri.KEY_AT, f"{ri.SITE_AT}/", ri.FEED_AT}
    assert rec.verdict == (
        "the runbook alone does not install the box: stopped at the one command (§1:32) because this machine's "
        "stand-in serves no more (a machine stop)"
    )
    assert rec.machine_stop and rec.lifts == []  # the stand-in docker ends the unit run; it is never a finding
    assert ri.compare(run, ri.load_findings()) == []


def test_strict_follow_needs_no_lift_on_the_unit_machine(tmp_path: Path) -> None:
    """H-22's lifts host-tree and vendor-key-first went with D-996: the strict run goes as far as the lifted one."""
    m, bundle, pub = _unit_machine(tmp_path)
    rec = ri.Follower(m, bundle=bundle, vendor_pub=pub, work=tmp_path / "work", lifts=False).follow()
    assert rec.lifts == [] and rec.findings == [] and rec.machine_stop
    assert [s["step"] for s in rec.steps if "rc" in s] == ["one-command"]


def test_compare_fails_on_a_vanished_and_on_a_new_finding() -> None:
    committed: list[dict[str, Any]] = [
        {"id": "a", "step": "one-command", "seen_on": ["unit"]},
        {"id": "b", "step": "7-first-ingest", "seen_on": ["unit"]},
        {"id": "c", "step": "one-command", "seen_on": ["container"]},
        {"id": "s", "step": None, "seen_on": [], "static": True},
    ]
    run = {"machine": "unit", "reached": ["convention", "one-command"], "findings": [{"id": "a"}]}
    assert ri.compare(run, committed) == []  # b's step was not reached; c is another machine's
    assert ri.compare({**run, "findings": []}, committed) == [
        "committed finding no longer reproduces on unit: a (step one-command was reached)"
    ]
    assert ri.compare({**run, "findings": [{"id": "a"}, {"id": "z"}, {"id": "c"}]}, committed) == [
        "finding c now shows on unit: add unit to its seen_on",
        f"new finding, not in {ri.FINDINGS}: z",
    ]
    assert ri.compare(run, committed, static=[]) == ["static finding no longer shows in the runbook's text: s"]
    assert ri.compare(run, committed, static=["s", "t"]) == [f"static finding not in {ri.FINDINGS}: t"]


def test_the_committed_container_run_matches_the_findings() -> None:
    if not RUN.is_file():
        pytest.fail(f"{RUN} is missing: the container run's record is part of the measurement")
    run = json.loads(RUN.read_text(encoding="utf-8"))
    assert run["machine"] == "container" and run["commands_run"] > 0
    assert ri.compare(run, ri.load_findings()) == []
    for s in run["steps"]:  # the record was written through redact(): nothing it would change is left
        assert ri.redact(s.get("out", "")) == s.get("out", "") and ri.redact(s.get("err", "")) == s.get("err", "")


def test_the_record_keeps_no_secret() -> None:
    text = "==> first console administrator\n  admin: s3cr3t-pass\n  code 123456\n    hand the enrolment code\nTB_LLM_API_KEY=abc"
    got = ri.redact(text)
    assert "s3cr3t" not in got and "123456" not in got and "abc" not in got
    assert "TB_LLM_API_KEY=[redacted]" in got
