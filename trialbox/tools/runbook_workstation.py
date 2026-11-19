"""W-2: install from the version tag by runbook §27 alone, on a GPU host, by someone who did not write it.

    python3 -m tools.runbook_workstation extract [--json]   # §27's commands, in order, each with its step and line
    python3 -m tools.runbook_workstation plan               # what the follower does with each of them
    python3 -m tools.runbook_workstation diff               # §27's commands the follower does not know, and back
    python3 -m tools.runbook_workstation follow --tag T --out run.json --work DIR [--strict | --rerun] [--raw-dir R]
                                                            [--mail]

**What is followed.** ``docs/runbook/27-workstation-rtx-pro-6000.md``, the step table (steps 1 to 15) and nothing
else: the PoC with the real model pair, installed from a checkout of the version tag (root review 23, section 4.1:
W-2 is "the tag, and one person who did not write it following runbook 27 once on a GPU host"). §27 has no signed
bundle and no vendor key; RUNBOOK §1, the site box's install from the stick, is ``tools/runbook_install.py``'s.

**The extraction rule** (``extract``). In each row of the step table, every inline code span of every cell whose
text, whitespace folded, starts with one of ``HEADS`` (or is exactly ``nvidia-smi``), and every span that starts
``--`` (a fragment: an option of the command before it). Each keeps its step, its column (``do``, ``see`` or
``else``) and its line. The follower knows every one of them (``KNOWN``): the test fails when §27 gains, loses or
changes a command until ``KNOWN`` says what the follower does with it.

**The roles** (``KNOWN``). ``run``: the follower runs it as written (a ``sudo`` command included; the guide's reader
is a user with sudo, not root). ``check``: run as written to see the step's result. ``host``: a command of steps 2 to
7 that changes the machine (a package, a group, a reboot); the launcher runs it by the guide before the follow,
and the follower checks its result with the step's ``check`` command; a step whose install the guide gives only as
an outside page (step 5: Docker's page; step 7: NVIDIA's apt steps) is ``host`` too, and the record says so.
``else``: what the guide says to run when a step fails; the follower runs it then. ``manual``: a browser or the
network cable (steps 12 to 15); the launcher does it by hand and writes it on the sheet's form. ``fragment``: an
option named for the command before it.

**What the follower may supply.** The tag (``<tag>`` in step 8: "the version tag we send you"), the composed command
of step 10 ("the same without ``--dry-run``"), a working folder for step 8's clone, and the environment it was
started with (an ``HF_TOKEN`` the guide asks for in its weights section passes through and is never recorded).
Nothing else: no package, no option, no reordered step.

**Strict and rerun.** ``--strict``: no lift; the first step whose result is not the guide's "You should see" ends the
follow with the verdict "the guide alone does not install: stopped at step N because <evidence>". ``--rerun``: the
guide says steps 10 and 11 may be run again; the follower reuses the checkout of step 8 (it must be at the tag) and
may apply the lifts of ``LIFTS``, each once, recorded, and marking every later result "after lifts". A lift never
changes the strict verdict. ``--mail`` (rerun only) does steps 13 and 14 by the start's own printed alternative to the
console's Test mailbox page (``tools/send_test_mail.py``) and reads the replies from the web mail's API.

**The tag.** After step 8 the follower checks that the checkout's ``HEAD`` is the tag's commit and the tree is
clean, and records the commit; it records its own checkout's commit beside it (the follower should run from the
same tag). Python 3.10 or newer, standard library only.

**The record** holds no secret: every output passes ``redact`` (the start prints the administrator's password once:
"password (shown once): ..."), and ``--raw-dir`` keeps each command's unredacted output, mode 0600, never in the
record.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.runbook_install import redact as _redact_install

ROOT = Path(__file__).resolve().parents[1]
GUIDE = "docs/runbook/27-workstation-rtx-pro-6000.md"
REPO_URL = "https://github.com/zandis/Auto-GPT.git"
HEADS = ("sudo ", "python3 ", "sh ", "git ", "cd ", "docker ", "nvidia-smi ", "lsb_release", "TB_", "deploy/", "make ")
DB_IMAGE = "trialbox-postgres:16-1"
MAILHOG = "http://127.0.0.1:8025/api/v2/messages"
ADMIN_MAIL = "admin@hospa.test"


# ------------------------------------------------------------------------------------------------ extraction
@dataclass(frozen=True)
class Command:
    step: int
    column: str  # do | see | else
    line: int
    text: str

    @property
    def fragment(self) -> bool:
        return self.text.startswith("--")


def _fold(s: str) -> str:
    return " ".join(s.split())


def is_command(text: str) -> bool:
    t = _fold(text)
    return t == "nvidia-smi" or t.startswith("--") or t.startswith(HEADS)


def _cells(row: str) -> list[str]:
    """The cells of one table row, split on '|' outside code spans."""
    cells, cur, tick = [], "", False
    for ch in row.strip().strip("|"):
        if ch == "`":
            tick = not tick
        if ch == "|" and not tick:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


COLUMNS = {2: "do", 3: "see", 4: "else"}  # 0 number, 1 step, 2 "Type or click", 3 "You should see", 4 "If not"


def extract(rel: str = GUIDE, root: Path = ROOT) -> list[Command]:
    """Every command of §27's step table, in the order written."""
    out: list[Command] = []
    for n, ln in enumerate((root / rel).read_text(encoding="utf-8").splitlines(), 1):
        if not re.match(r"^\|\s*\d+\s*\|", ln):
            continue
        cells = _cells(ln)
        step = int(cells[0])
        for i, col in COLUMNS.items():
            if i >= len(cells):
                continue
            for span in re.findall(r"`([^`]+)`", cells[i]):
                if is_command(span):
                    out.append(Command(step, col, n, _fold(span)))
    return out


def step_titles(rel: str = GUIDE, root: Path = ROOT) -> dict[int, str]:
    out = {}
    for ln in (root / rel).read_text(encoding="utf-8").splitlines():
        if re.match(r"^\|\s*\d+\s*\|", ln):
            c = _cells(ln)
            out[int(c[0])] = c[1]
    return out


# ------------------------------------------------------------------------------------------------ the plan
# (step, text) -> role. Every command extract() finds must be here, and nothing else (the test holds the two equal).
KNOWN: dict[tuple[int, str], str] = {
    (1, "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv"): "check",
    (2, "lsb_release -rs"): "check",
    (3, "sudo apt update && sudo apt install -y git make curl python3-yaml python3-venv"): "run",
    (4, "sudo ubuntu-drivers list"): "check",
    (4, "sudo apt install -y nvidia-driver-580-open"): "host",
    (4, "sudo reboot"): "host",
    (4, "nvidia-smi"): "check",
    (5, "docker compose version"): "check",
    (6, "sudo usermod -aG docker $USER"): "host",
    (6, "docker info"): "check",
    (7, "sudo nvidia-ctk runtime configure --runtime=docker"): "host",
    (7, "sudo systemctl restart docker"): "host",
    (7, "docker run --rm --gpus all ubuntu:24.04 nvidia-smi"): "check",
    (8, "git clone https://github.com/zandis/Auto-GPT.git"): "run",
    (8, "cd Auto-GPT/trialbox"): "run",
    (8, "git checkout <tag>"): "run",
    (9, "sh deploy/gpu_profile.sh"): "check",
    (9, "python3 tools/tiers.py check --tier large"): "check",
    (10, "python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run"): "run",
    (10, "--dry-run"): "fragment",
    (10, "python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only"): "check",
    (11, "TB_LLM_MODE=gpu deploy/poc.sh"): "run",
    (11, "deploy/poc.sh status"): "else",
    (12, "deploy/poc.sh reset"): "manual",
    (13, "deploy/poc.sh status"): "manual",
    (15, "deploy/poc.sh down"): "manual",
    (15, "deploy/poc.sh status"): "manual",
}

# what the launcher does by hand for a step, and why the follower does not (the sheet's stage 2 and stage 6)
LAUNCHER: dict[int, str] = {
    2: "the VM's image is Ubuntu 24.04 LTS (the step's install from a USB stick is the VM's creation)",
    4: "the driver install and the reboot (a reboot ends the follower's session)",
    5: "Docker Engine from docs.docker.com's page: the guide gives no command, only the page",
    6: "the group change, then sign out and in (a new SSH session)",
    7: "the NVIDIA Container Toolkit by NVIDIA's apt steps: the guide gives no command for the install, only the name",
    12: "a browser through an SSH tunnel to 127.0.0.1:8090; the second factor on a phone",
    13: "the console's Test mailbox page (or --mail on a rerun)",
    14: "the console's Test mailbox page (or --mail on a rerun)",
    15: "unplug the network: a VM has no cable (the sheet says what stands for it); then deploy/poc.sh down",
}
MANUAL_STEPS = (12, 13, 14, 15)
SLOW = {10: 3 * 3600, 11: 3 * 3600}  # seconds; every other command 1800


@dataclass
class Lift:
    key: str
    step: int
    source: str  # the repository page that states the remedy
    command: str
    when: str


LIFTS = [
    Lift(
        "db-image",
        11,
        "docs/runbook/28-igx-orin-a6000-without-a-model.md step 6 (the start forgets the database image on a machine "
        "without Java build tools)",
        f"docker build -f deploy/docker/db.Dockerfile -t {DB_IMAGE} deploy/docker",
        f"step 11 stopped and the image {DB_IMAGE} is not on the machine",
    ),
]


# ------------------------------------------------------------------------------------------------ checks
SHOWN_ONCE = re.compile(r"(?i)(shown once\)?\s*:\s*)\S+")
TOKENISH = re.compile(r"\bhf_[A-Za-z0-9]{8,}\b")


def redact(text: str) -> str:
    """The install follower's redaction, plus the start's own once-shown password line and any hub token."""
    text = SHOWN_ONCE.sub(r"\1[not recorded]", text)
    text = TOKENISH.sub("[redacted]", text)
    return _redact_install(text)


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def check_card(out: str) -> str:
    """Step 1 (and 7): '' when the line is the guide's card, else why not."""
    if "6000 Ada" in out:
        return "the card is an RTX 6000 Ada (the guide: stop and send the line)"
    if "RTX PRO 6000" not in out:
        return "no RTX PRO 6000 in the output"
    mib = [int(m) for m in re.findall(r"(\d{4,6})\s*MiB", out)]
    if mib and max(mib) < 90000:
        return f"{max(mib)} MiB (the guide: about 97,000 MiB; about 49,000 is the 48 GB card)"
    return ""


def check_driver(out: str) -> str:
    m = re.search(r"Driver Version:\s*([\d.]+)", out) or re.search(r",\s*(\d{3}\.\d+(?:\.\d+)?)\s*$", out, re.M)
    if not m:
        return "no driver version in the output"
    return "" if _ver(m.group(1)) >= (580, 65) else f"driver {m.group(1)} (the guide: 580.65 or newer)"


def check_compose(out: str) -> str:
    m = re.search(r"v?(\d+)\.(\d+)\.\d+", out)
    return "" if m else "no version in the output"


def compose_note(out: str) -> str:
    """The guide says v2.x; a newer major version is recorded, not a stop (the start only needs the plugin)."""
    m = re.search(r"v?(\d+)\.(\d+)\.\d+", out)
    return f"the guide says v2.x; this machine shows v{m.group(1)}.{m.group(2)}" if m and m.group(1) != "2" else ""


def no_error_line(out: str) -> str:
    bad = [ln for ln in out.splitlines() if ln.startswith("E:")]
    return f"an 'E:' line: {bad[0][:200]}" if bad else ""


def _want(s: str) -> Callable[[str], str]:
    return lambda out: "" if s in out else f"no '{s}' in the output"


CHECKS: dict[str, Callable[[str], str]] = {
    "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv": check_card,
    "lsb_release -rs": lambda out: "" if out.strip() == "24.04" else f"'{out.strip()[:40]}', not 24.04",
    "sudo apt update && sudo apt install -y git make curl python3-yaml python3-venv": no_error_line,
    "nvidia-smi": check_driver,
    "docker compose version": check_compose,
    "docker run --rm --gpus all ubuntu:24.04 nvidia-smi": check_card,
    "sh deploy/gpu_profile.sh": lambda out: "" if out.strip() == "rtxpro6000" else f"'{out.strip()[:40]}'",
    "python3 -m tools.fetch_weights --profile rtxpro6000": _want("Next step"),
    "python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only": _want("All present and pinned."),
    "TB_LLM_MODE=gpu deploy/poc.sh": lambda out: (
        "the start says the ingest did not pass" if "ingest did not pass" in out else ""
    ),
}


# ------------------------------------------------------------------------------------------------ running
@dataclass
class Result:
    rc: int
    out: str
    seconds: float


Runner = Callable[[str, Path, int], Result]


def shell_runner(cmd: str, cwd: Path, timeout: int) -> Result:
    t0 = time.monotonic()
    try:
        p = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        out, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired as e:
        parts = [x.decode(errors="replace") if isinstance(x, bytes) else (x or "") for x in (e.stdout, e.stderr)]
        out, rc = "".join(parts) + f"\nrunbook-workstation: stopped after {timeout} s", 124
    return Result(rc, out, round(time.monotonic() - t0, 1))


@dataclass
class Record:
    card: str = "W-2"
    guide: str = GUIDE
    tag: str = ""
    mode: str = "strict"
    machine: dict[str, Any] = field(default_factory=dict)
    follower_commit: str = ""
    checkout_commit: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    lifts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    manual: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = ""
    stopped_at: int | None = None
    after_lifts_verdict: str = ""


class StepFailed(Exception):
    def __init__(self, step: int, why: str):
        super().__init__(f"step {step}: {why}")
        self.step, self.why = step, why


class Follower:
    def __init__(
        self,
        tag: str,
        work: Path,
        *,
        strict: bool = True,
        rerun: bool = False,
        mail: bool = False,
        raw_dir: Path | None = None,
        run: Runner = shell_runner,
        fetch: Callable[[str], bytes] | None = None,
        root: Path = ROOT,
        sleep: Callable[[float], None] = time.sleep,
        mail_wait: int = 600,
    ):
        self.tag, self.work, self.strict, self.rerun, self.mail = tag, work, strict, rerun, mail
        self.raw_dir, self.run, self.root, self.sleep, self.mail_wait = raw_dir, run, root, sleep, mail_wait
        self.fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=10).read())  # localhost only
        self.cwd = work
        self.rec = Record(tag=tag, mode="strict" if strict else "rerun")
        self.n = 0
        self.lifted = False

    # one command, as written (or with the tag put in), recorded
    def cmd(self, step: int, text: str, role: str, as_run: str | None = None) -> Result:
        self.n += 1
        r = self.run(as_run or text, self.cwd, SLOW.get(step, 1800))
        if self.raw_dir:
            p = self.raw_dir / f"{self.n:02d}-step{step}.txt"
            p.write_text(f"$ {as_run or text}\n(cwd {self.cwd})\n{r.out}", encoding="utf-8")
            os.chmod(p, 0o600)
        entry: dict[str, Any] = {
            "step": step,
            "role": role,
            "command": text,
            "rc": r.rc,
            "seconds": r.seconds,
            "tail": " | ".join(ln for ln in redact(r.out).strip().splitlines()[-6:] if ln.strip())[-700:],
        }
        if as_run and as_run != text:
            entry["as_run"] = as_run
        if self.lifted:
            entry["after_lifts"] = True
        self.rec.steps.append(entry)
        return r

    def expect(self, step: int, text: str, r: Result) -> None:
        if r.rc != 0:
            raise StepFailed(step, f"`{text}` exited {r.rc}: {_tail(r.out)}")
        check = CHECKS.get(text)
        why = check(r.out) if check else ""
        if why:
            raise StepFailed(step, f"`{text}`: {why}")

    def host_step(self, step: int, check: list[str]) -> None:
        if step in LAUNCHER:
            self.rec.notes.append(f"step {step}: by the launcher before the follow: {LAUNCHER[step]}")
        for text in check:
            r = self.cmd(step, text, KNOWN[(step, text)])
            if text == "docker compose version" and compose_note(r.out):
                self.rec.notes.append(
                    f"step 5: {compose_note(r.out)} (recorded, not a stop: the start needs only the plugin)"
                )
            if text == "docker info" and r.rc != 0 and "permission denied" in r.out.lower():
                raise StepFailed(
                    step, "docker info: permission denied (step 6: sign out and in after the group change)"
                )
            self.expect(step, text, r)

    # ---------------------------------------------------------------------------------- the steps
    def steps_1_to_7(self) -> None:
        self.host_step(1, ["nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv"])
        self.host_step(2, ["lsb_release -rs"])
        t = "sudo apt update && sudo apt install -y git make curl python3-yaml python3-venv"
        self.expect(3, t, self.cmd(3, t, "run"))
        self.host_step(4, ["sudo ubuntu-drivers list", "nvidia-smi"])
        self.host_step(5, ["docker compose version"])
        self.host_step(6, ["docker info"])
        self.host_step(7, ["docker run --rm --gpus all ubuntu:24.04 nvidia-smi"])

    def step_8(self) -> None:
        repo = self.work / "Auto-GPT"
        if self.rerun and repo.is_dir():
            self.rec.notes.append("step 8: the checkout of the first follow is reused (--rerun)")
        else:
            if repo.exists():
                raise StepFailed(8, f"{repo} exists: a first follow needs an empty working folder (or --rerun)")
            t = f"git clone {REPO_URL}"
            self.expect(8, t, self.cmd(8, t, "run"))
        self.cwd = repo / "trialbox"  # `cd Auto-GPT/trialbox`: the follower's own working folder from here on
        self.rec.steps.append({"step": 8, "role": "run", "command": "cd Auto-GPT/trialbox", "cwd": str(self.cwd)})
        if not self.cwd.is_dir():
            raise StepFailed(8, "no Auto-GPT/trialbox after the clone")
        r = self.cmd(8, "git checkout <tag>", "run", as_run=f"git checkout {_q(self.tag)}")
        if r.rc != 0:
            raise StepFailed(8, f"git checkout {self.tag} exited {r.rc}: {_tail(r.out)}")
        self.verify_tag()

    def verify_tag(self) -> None:
        head = self.run("git rev-parse HEAD", self.cwd, 60).out.strip()
        tagc = self.run(f"git rev-list -n 1 {_q(self.tag)}", self.cwd, 60).out.strip()
        dirty = self.run("git status --porcelain", self.cwd, 60).out.strip()
        self.rec.checkout_commit = head
        if not re.fullmatch(r"[0-9a-f]{40}", head) or head != tagc:
            raise StepFailed(8, f"the checkout is not the tag {self.tag}'s commit (HEAD {head[:12]}, tag {tagc[:12]})")
        if dirty:
            raise StepFailed(8, "the checkout is not clean: " + _tail(dirty, 200))
        if self.rec.follower_commit and self.rec.follower_commit != head:
            self.rec.notes.append(
                f"the follower ran from {self.rec.follower_commit[:12]}, not the tag's commit "
                f"{head[:12]}: run it from a checkout of the tag"
            )

    def step_9(self) -> None:
        for t in ("sh deploy/gpu_profile.sh", "python3 tools/tiers.py check --tier large"):
            self.expect(9, t, self.cmd(9, t, "check"))

    def step_10(self) -> None:
        dry = "python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run"
        self.expect(10, dry, self.cmd(10, dry, "run"))
        full = "python3 -m tools.fetch_weights --profile rtxpro6000"  # "then the same without --dry-run"
        self.expect(10, full, self.cmd(10, full, "run (the guide's words: the same without --dry-run)"))
        ver = "python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only"
        self.expect(10, ver, self.cmd(10, ver, "check"))

    def step_11(self) -> None:
        t = "TB_LLM_MODE=gpu deploy/poc.sh"
        r = self.cmd(11, t, "run")
        try:
            self.expect(11, t, r)
        except StepFailed:
            self.cmd(11, "deploy/poc.sh status", "else")  # the guide: copy the poc: line and the status
            raise

    def mail_steps(self) -> None:
        for step, subject, exts, n in (
            (13, "FEAS GZQO", (".pdf", ".xlsx"), 1),
            (14, "SCREEN GZQO version=1.0.0", (".xlsx", ".pdf"), 2),
        ):
            before = self.mailbox()
            send = f'python3 tools/send_test_mail.py "{subject}" --sender {ADMIN_MAIL}'
            r = self.cmd(step, f"(lift: the start's printed alternative) {send}", "lift", as_run=send)
            if r.rc != 0:
                raise StepFailed(step, f"the test mail was not sent: {_tail(r.out)}")
            got = self.wait_replies(before, n)
            names = [a for m in got for a in m["attachments"]]
            entry = {"step": step, "role": "lift", "replies": len(got), "attachments": names, "after_lifts": True}
            self.rec.steps.append(entry)
            missing = [e for e in exts if not any(a.lower().endswith(e) for a in names)]
            if len(got) < n or missing:
                raise StepFailed(
                    step,
                    f"{len(got)} repl(ies) in {self.mail_wait} s, missing {missing or 'none'} "
                    f"(the guide: no reply in 10 min: send deploy/poc.sh status)",
                )

    def mailbox(self) -> set[str]:
        return {m["id"] for m in self._messages()}

    def _messages(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.fetch(MAILHOG))
        except Exception:  # the web mail not up yet: an empty mailbox
            return []
        out = []
        for it in data.get("items") or []:
            to = json.dumps((it.get("Content") or {}).get("Headers", {}).get("To", []))
            if ADMIN_MAIL not in to:
                continue
            names = [
                n
                for t in _strings(it.get("MIME") or it.get("Raw") or {})
                for n in re.findall(r'(?i)\bfilename="?([^";\r\n]+)"?', t)
            ]
            out.append({"id": it.get("ID", ""), "attachments": sorted(set(names))})
        return out

    def wait_replies(self, before: set[str], n: int) -> list[dict[str, Any]]:
        t0, got = time.monotonic(), []
        while True:
            got = [m for m in self._messages() if m["id"] not in before]
            if len(got) >= n or time.monotonic() - t0 >= self.mail_wait:
                return got
            self.sleep(10)

    def apply_lifts(self, failed: StepFailed) -> bool:
        if self.strict or failed.step != 11:
            return False
        lift = LIFTS[0]
        if self.run(f"docker image inspect {DB_IMAGE}", self.cwd, 60).rc == 0:
            return False
        self.lifted = True
        self.rec.lifts.append({**asdict(lift), "applied_after": failed.why[:300]})
        r = self.cmd(11, f"(lift {lift.key}) {lift.command}", "lift", as_run=lift.command)
        return r.rc == 0

    # ---------------------------------------------------------------------------------- the whole follow
    def follow(self) -> Record:
        self.rec.machine = machine_facts(self.run, self.work)
        self.rec.follower_commit = self.run("git rev-parse HEAD", self.root, 60).out.strip()
        order: list[Callable[[], None]] = [self.steps_1_to_7, self.step_8, self.step_9, self.step_10, self.step_11]
        try:
            for f in order:
                try:
                    f()
                except StepFailed as e:
                    if not self.apply_lifts(e):
                        raise
                    self.rec.notes.append("step 11 again after the lift (the guide: running step 11 again is safe)")
                    self.step_11()
            self.rec.verdict = "the guide alone installs the box: steps 1 to 11 as written"
        except StepFailed as e:
            self.rec.stopped_at = e.step
            words = "after lifts, " if self.lifted else ""
            self.rec.verdict = (
                f"{words}the guide alone does not install the box: stopped at step {e.step} because {e.why}"
            )
            if self.lifted:
                self.rec.after_lifts_verdict = self.rec.verdict
            return self.finish()
        if self.lifted:
            self.rec.after_lifts_verdict = "after lifts, steps 1 to 11 passed"
            self.rec.verdict = "the guide alone does not install the box: a lift was needed (see lifts)"
        if self.mail and not self.strict:
            self.lifted = True
            try:
                self.mail_steps()
            except StepFailed as e:
                self.rec.after_lifts_verdict = f"after lifts, stopped at step {e.step} because {e.why}"
        return self.finish()

    def finish(self) -> Record:
        titles = step_titles(root=self.root) if (self.root / GUIDE).exists() else {}
        done = {s["step"] for s in self.rec.steps if s.get("role") == "lift" and "replies" in s}
        for n in MANUAL_STEPS:
            if n not in done:
                self.rec.manual.append(
                    {"step": n, "title": titles.get(n, ""), "by": LAUNCHER[n], "result": "write it on the sheet's form"}
                )
        return self.rec


def _strings(obj: Any) -> Iterable[str]:
    """Every text value inside a parsed JSON value (the web mail's MIME tree)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _q(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._/+-]+", s):
        raise ValueError(f"not a tag name: {s!r}")
    return s


def _tail(s: str, n: int = 300) -> str:
    return " | ".join(ln.strip() for ln in redact(s).strip().splitlines()[-3:] if ln.strip())[-n:]


def machine_facts(run: Runner, work: Path) -> dict[str, Any]:
    def one(cmd: str) -> str:
        return run(cmd, work, 60).out.strip()[:200]

    return {
        "arch": platform.machine(),
        "python": platform.python_version(),
        "os": one("lsb_release -ds"),
        "cpus": os.cpu_count(),
        "memory": one("free -g | sed -n 2p"),
        "disk_free_work": one(f"df -h --output=avail {work} | tail -1"),
        "gpu": one("nvidia-smi -L 2>&1 | head -1"),
    }


def timings(rec: Record) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in rec.steps:
        if "seconds" not in s:
            continue
        if out and out[-1]["step"] == s["step"]:
            out[-1]["commands"] += 1
            out[-1]["seconds"] = round(out[-1]["seconds"] + s["seconds"], 1)
            out[-1]["rc"] = s["rc"]
        else:
            out.append({"step": s["step"], "commands": 1, "seconds": s["seconds"], "rc": s["rc"]})
    return out


def preflight(a: argparse.Namespace, run: Runner = shell_runner) -> list[str]:
    """Why the follow cannot start, before anything is changed ([] when it can)."""
    why = []
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        why.append("run as the user who follows the guide (it uses sudo), not as root")
    if not a.tag:
        why.append("--tag (the version tag the guide's step 8 checks out)")
    else:
        try:
            _q(a.tag)
        except ValueError as e:
            why.append(str(e))
    if a.strict and a.rerun:
        why.append("--strict or --rerun, not both")
    if a.mail and not a.rerun:
        why.append("--mail is a lift: only with --rerun")
    if shutil.which("sudo") and run("sudo -n true", Path.cwd(), 30).rc != 0:
        why.append("sudo asks for a password: the follower cannot type it (use a user with sudo without a password)")
    work = Path(a.work)
    if not a.rerun and (work / "Auto-GPT").exists():
        why.append(f"{work}/Auto-GPT exists: a first follow starts with an empty working folder")
    if platform.machine() not in ("x86_64", "AMD64"):
        why.append(f"this machine is {platform.machine()}: W-2 is the x86 GPU VM (the Arm path is not W-2's)")
    return why


# ------------------------------------------------------------------------------------------------ the CLI
def diff(root: Path = ROOT) -> tuple[list[Command], list[tuple[int, str]]]:
    """§27's commands the follower does not know, and the follower's commands §27 no longer has."""
    got = extract(root=root)
    keys = {(c.step, c.text) for c in got}
    return [c for c in got if (c.step, c.text) not in KNOWN], [k for k in KNOWN if k not in keys]


def _cmd_extract(a: argparse.Namespace) -> int:
    cmds = extract()
    if a.json:
        print(json.dumps([asdict(c) for c in cmds], indent=1))
    else:
        for c in cmds:
            print(f"{GUIDE}:{c.line}  step {c.step:>2} [{c.column}]  {c.text}")
    return 0


def _cmd_plan(a: argparse.Namespace) -> int:
    titles = step_titles()
    for n in sorted(titles):
        print(f"step {n:>2}. {titles[n]}" + (f"   (launcher: {LAUNCHER[n]})" if n in LAUNCHER else ""))
        for (s, text), role in KNOWN.items():
            if s == n:
                print(f"           {role:<9} {text}")
    for lift in LIFTS:
        print(f"lift {lift.key} (rerun only, step {lift.step}): {lift.command}   [{lift.source}]")
    return 0


def _cmd_diff(a: argparse.Namespace) -> int:
    unknown, gone = diff()
    for c in unknown:
        print(f"the guide has, the follower does not know: {GUIDE}:{c.line} step {c.step}: {c.text}")
    for s, text in gone:
        print(f"the follower knows, the guide no longer has: step {s}: {text}")
    if not unknown and not gone:
        print(f"the follower knows every command of {GUIDE}'s step table ({len(KNOWN)})")
    return 1 if unknown or gone else 0


def _cmd_follow(a: argparse.Namespace) -> int:
    why = preflight(a)
    if why:
        for w in why:
            print(f"runbook-workstation: refused: {w}", file=sys.stderr)
        return 2
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    raw = None
    if a.raw_dir:
        raw = Path(a.raw_dir).resolve()
        raw.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(raw, 0o700)
    f = Follower(a.tag, work, strict=not a.rerun, rerun=a.rerun, mail=a.mail, raw_dir=raw)
    rec = f.follow()
    out = asdict(rec)
    out["timings"] = timings(rec)
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(rec.verdict)
    if rec.after_lifts_verdict:
        print(rec.after_lifts_verdict)
    for m in rec.manual:
        print(f"by hand: step {m['step']} ({m['by']})")
    return 0 if rec.stopped_at is None and not rec.lifts else 1


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="runbook_workstation", description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--json", action="store_true")
    sub.add_parser("plan")
    sub.add_parser("diff")
    f = sub.add_parser("follow")
    f.add_argument("--tag", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--work", required=True, help="the folder step 8 clones into")
    f.add_argument("--strict", action="store_true", help="no lifts (the default for a first follow)")
    f.add_argument("--rerun", action="store_true", help="steps 10 and 11 again on the same checkout, with lifts")
    f.add_argument("--mail", action="store_true", help="rerun only: steps 13 and 14 by tools/send_test_mail.py")
    f.add_argument("--raw-dir", default="", help="each command's unredacted output, 0600, never in the record")
    a = ap.parse_args(list(argv) if argv is not None else None)
    return {"extract": _cmd_extract, "plan": _cmd_plan, "diff": _cmd_diff, "follow": _cmd_follow}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
