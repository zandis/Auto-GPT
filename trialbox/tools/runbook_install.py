"""H-22 (D-1136): install from the bundle by the install runbook alone; record where the runbook was wrong or silent.

    python -m tools.runbook_install extract [--json]            # the runbook's commands, in order, with their place
    python -m tools.runbook_install plan                        # the install path the follower walks (D-1136)
    python -m tools.runbook_install static                      # the findings the runbook's text alone shows
    python -m tools.runbook_install follow --bundle B --vendor-pub K --out run.json [--machine container|local ...]
    python -m tools.runbook_install compare run.json            # the run against the committed findings file

**What is followed.** The install runbook of a site's IT on Linux: the RUNBOOK hub's opening (it says where commands run
and as whom) and section 1, ``docs/runbook/01-install-a-new-site.md``. Nothing else is read by the follower; the
Windows pages, the box form (§16) and the hand-over sheets are not the IT reader's install path.

**The extraction rule** (``extract``). A command is

* an inline code span (one pair of backticks; it may wrap onto the next line) outside a fenced block, or one logical
  line (a trailing backslash joins the next) of a fenced block,
* whose text, with whitespace folded to single spaces, starts with one of ``HEADS`` (``sudo``, ``python``,
  ``deploy/``, ``tools/``, ``make``, ``docker``, ``cd``, ``TB_``, ``--``, ``systemctl``)
* and holds a space or ends in ``.py`` or ``.sh`` (so a bare path in prose is not a command).

This is the rule ``tests/unit/test_runbook_install_commands.py`` applies to §1 (its ``commands()``); the test of this
tool holds the two to the same list. Each command keeps its place (file, line of its opening backtick), the block it is
in (the bold lead of its paragraph, or ``N. Title`` of a numbered step) and the sentence that introduces it. A command
that starts ``--`` is a fragment: an option to a command named before it. The extractor runs nothing.

**The install path** (``PLAN``, D-1136). The hub's convention (``/opt/trialbox``, as root); step 1's prerequisites,
checked on the machine, never installed; the **One command.** paragraph's command; then, in the runbook's order, each
numbered step the **One command.** paragraph does not say the installer does (4: the mapping check, 6: the vendor key,
7: the first ingest and its report). Steps 2, 3, 5 and 8 are the installer's by the runbook's own words (quoted in
``PLAN``); 9 and 10 point at other sections and carry no command. Every other command of §1 is listed as one the
install path never needed, with the reason the runbook gives.

**What the follower may supply** (D-1136): only what the runbook tells the reader to bring. The bundle; the vendor key
"received out of band" (placed only where the runbook says, step 6); the site's folder of "What the site brings"
(``site.yaml`` and ``mapping/``), whose values are the hospital's and so come from the box rehearsal's documented
synthetic answers (``tools/rehearse_box/site_answers.yaml`` and its mapping), plus any answer the runbook itself names
as required, with a synthetic value (each one is recorded); the feed folder's content (the hospital's export: the
synthetic site A export); and an Enter at a prompt, which is what a reader at the terminal gives (each prompt the
runbook does not mention is a finding). ``sudo`` is dropped when the follower is already root (the hub's "as root").

**What it may not supply.** Anything else: no directory made, no package installed, no environment variable, no
reordered step, no option added. When the runbook's text does not get the box installed, the verdict is "the runbook
alone does not install the box: stopped at <step> because <evidence>", which is a valid, reported outcome.

**Lifts.** After the verdict the follower may go on to find the next place the runbook is silent, but only by a lift
named in ``LIFTS``: the smallest remedy that the stop's own message or another repository page states, applied once,
recorded, and marking every later result "after lifts". A lift never changes the verdict. A machine stand-in (no TPM, no
GPU in a container) is a lift of kind ``machine``: it says the machine lacks what step 1 names, not that the runbook
is wrong, and its stop is not a finding.

**Findings.** Static findings are read from the runbook's text by a named check (``STATIC``); run findings come from the
follower's record (``detect``). ``compare`` fails when a committed finding no longer reproduces on a machine that
reached its step, or when the run shows a finding the committed file does not hold: the test is a check, not a
stamp. The committed file is ``docs/plan/measurements/runbook-install-2026-11-17/findings.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
HUB = "docs/RUNBOOK.md"
SECTION = "docs/runbook/01-install-a-new-site.md"
FINDINGS = "docs/plan/measurements/runbook-install-2026-11-17/findings.json"
HEADS = ("sudo ", "python", "deploy/", "tools/", "make ", "docker ", "cd ", "TB_", "--", "systemctl ")
OPT = "/opt/trialbox"
# the run's work folder (the bundle, the logs): outside the checkout, as the box rehearsal's, so no scan of the tree
# reads the media; the same path is mounted in the machine container
WORK_DEFAULT = os.path.join(os.environ.get("TMPDIR") or "/tmp", "tb-runbook-install")
# the rehearsal's documented synthetic answers and mapping (D-176): the values the runbook leaves to the hospital
SYNTHETIC_ANSWERS = "tools/rehearse_box/site_answers.yaml"
SYNTHETIC_MAPPING = "tools/rehearse_box/mapping"
SYNTHETIC_FEED = "tests/fixtures/synthetic_patients/site-a"
# answers the runbook names as required that the rehearsal's answers (a VALIDATION box) do not hold
REQUIRED_ANSWERS = {"sae_office_mailbox": "trial-office@hospa.test"}


# ------------------------------------------------------------------------------------------------ extraction
@dataclass(frozen=True)
class Command:
    file: str
    line: int
    text: str
    block: str
    step: int | None
    prose: str

    @property
    def fragment(self) -> bool:
        return self.text.startswith("--")

    @property
    def place(self) -> str:
        return f"{self.file}:{self.line}"


def _fold(s: str) -> str:
    return " ".join(s.split())


def is_command(text: str) -> bool:
    t = _fold(text)
    return t.startswith(HEADS) and (" " in t or t.endswith((".py", ".sh")))


def _blank_fences(text: str) -> tuple[str, list[tuple[int, str]]]:
    """The text with fenced blocks blanked (same length, newlines kept), and the fenced logical lines with their
    line numbers."""
    out, fenced, inside, pending, start = [], [], False, "", 0
    for n, ln in enumerate(text.split("\n"), 1):
        if ln.lstrip().startswith("```"):
            inside = not inside
            out.append(" " * len(ln))
            continue
        if inside:
            body = ln.strip()
            if pending:
                pending += " " + body.rstrip("\\").strip()
            elif body and not body.startswith("#"):
                pending, start = body.rstrip("\\").strip(), n
            if pending and not body.endswith("\\"):
                fenced.append((start, pending))
                pending = ""
            out.append(" " * len(ln))
        else:
            out.append(ln)
    return "\n".join(out), fenced


def _blocks(lines: list[str]) -> list[tuple[str, int | None]]:
    """For each line (0-based), the block it is in: the bold lead of its paragraph or the numbered step."""
    res: list[tuple[str, int | None]] = []
    block, step, parent = "", None, ""
    for i, ln in enumerate(lines):
        m = re.match(r"^(\d+)\. \*\*(.+?)\*\*", ln)
        lead = re.match(r"^\*\*(.+?)\*\*", ln)
        if m:
            step, block = int(m.group(1)), f"{parent} / {m.group(1)}. {m.group(2).rstrip('.')}"
        elif lead and (i == 0 or not lines[i - 1].strip()):
            parent = block = lead.group(1).rstrip(".")
            step = None
        elif ln.startswith("#"):
            parent = block = ln.lstrip("# ").strip()
            step = None
        res.append((block, step))
    return res


def _sentence(para: str, start: int, end: int) -> str:
    """The sentence of ``para`` holding [start, end): from after the last '. ' outside backticks before it to the
    next one after it."""
    ticks = [m.start() for m in re.finditer("`", para)]

    def outside(i: int) -> bool:
        return sum(1 for t in ticks if t < i) % 2 == 0

    stops = [m.end() - 1 for m in re.finditer(r"[.:;]\**\s", para) if outside(m.start())]
    s = max([p for p in stops if p <= start], default=0)
    e = min([p for p in stops if p >= end], default=len(para))
    return _fold(para[s:e])


def extract(rel: str, root: Path = ROOT) -> list[Command]:
    """Every command of one runbook file, in the order written."""
    text = (root / rel).read_text(encoding="utf-8")
    blank, fenced = _blank_fences(text)
    lines = text.split("\n")
    blocks = _blocks(lines)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)

    def line_of(off: int) -> int:
        lo = 0
        while lo + 1 < len(starts) and starts[lo + 1] <= off:
            lo += 1
        return lo + 1

    def para_of(n: int) -> tuple[str, int]:
        a = n - 1
        while a > 0 and lines[a - 1].strip() and not re.match(r"^\d+\. ", lines[a]):
            a -= 1
        b = n - 1
        while b + 1 < len(lines) and lines[b + 1].strip() and not re.match(r"^\d+\. ", lines[b + 1]):
            b += 1
        return "\n".join(lines[a : b + 1]), starts[a]

    found: list[tuple[int, Command]] = []
    for m in re.finditer(r"`([^`]+)`", blank):
        span = m.group(1)
        if "\n\n" in span or not is_command(span):
            continue
        n = line_of(m.start())
        para, base = para_of(n)
        block, step = blocks[n - 1]
        prose = _sentence(para, m.start() - base, m.end() - base)
        found.append((m.start(), Command(rel, n, _fold(span), block, step, prose)))
    for n, body in fenced:
        if is_command(body):
            block, step = blocks[n - 1]
            found.append((starts[n - 1], Command(rel, n, _fold(body), block, step, "(fenced block)")))
    return [c for _, c in sorted(found, key=lambda x: x[0])]


def convention(root: Path = ROOT) -> tuple[str, str]:
    """The hub's rule for where commands run and as whom, or ('', '') when it says none."""
    hub = _fold((root / HUB).read_text(encoding="utf-8").split("<!-- index:", 1)[0])
    m = re.search(r"Commands run on the box from `([^`]+)` as (\w+)", hub)
    return (m.group(1), m.group(2)) if m else ("", "")


# ------------------------------------------------------------------------------------------------ the path
@dataclass(frozen=True)
class Step:
    """One step of the install path. ``quote`` is the runbook's text that makes it a step (held by the test)."""

    key: str
    action: str  # convention | prereq | run | place | expect | installer | other-section
    file: str
    quote: str
    command: str = ""
    step: int | None = None
    in_block: str = ""  # the quote is in this bold-lead paragraph, not in the step itself


PLAN: list[Step] = [
    Step("convention", "convention", HUB, "Commands run on the box from `/opt/trialbox` as root unless noted"),
    Step(
        "1-host",
        "prereq",
        SECTION,
        "Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+, nftables",
        step=1,
    ),
    Step(
        "one-command",
        "run",
        SECTION,
        "With the vendor's signed bundle on a USB stick",
        command="sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml",
    ),
    Step("2-images", "installer", SECTION, "It verifies and loads the bundle", step=2, in_block="One command."),
    Step("3-settings", "installer", SECTION, "runs the settings wizard", step=3, in_block="One command."),
    Step(
        "4-mapping-check",
        "run",
        SECTION,
        "It must report 0 missing columns",
        step=4,
        command="python tools/mapping_check.py --mapping deploy/site/mapping/tw_core/<site>.yaml --source csv "
        "--path <export dir>",
    ),
    Step("5-start", "installer", SECTION, "`install.sh` does both and enables the systemd units", step=5),
    Step(
        "6-vendor-key",
        "place",
        SECTION,
        "Install `deploy/keys/vendor_ed25519.pub`, received out of band",
        step=6,
        command="deploy/keys/vendor_ed25519.pub",
    ),
    Step(
        "7-first-ingest",
        "run",
        SECTION,
        "or wait for 02:00",
        step=7,
        command="docker compose exec adapter python -m adapter.cli run",
    ),
    Step(
        "7-ingest-report",
        "expect",
        SECTION,
        "`passed: true`, validator errors under 0.5 %",
        step=7,
        command="/data/lake/ndjson/<date>/ingest_report.json",
    ),
    Step("8-host-check", "installer", SECTION, "runs the host check", step=8, in_block="One command."),
    Step("9-backup-key", "other-section", SECTION, "With hospital IT, once (§5)", step=9),
    Step("10-acceptance", "other-section", SECTION, "before go-live (§6)", step=10),
]

# commands of §1 the install path does not run, and why (the runbook's own reason)
NOT_ON_PATH: list[tuple[str, str]] = [
    (r"tools/serving_config\.py measured", "names the check the installer runs"),
    (r"deploy/install\.sh --tier large --tier-check", "only asks (the runbook: 'only asks')"),
    (r"TB_COMPOSE_OVERRIDE= .*--rehearsal", "measuring a new card on a rehearsal box"),
    (r"python3 tools/serving_config\.py capture .*", "measuring a new card on a rehearsal box"),
    (r"python -m tools\.gpu_sizing", "an estimate, not an install step"),
    (r"--mode stub", "a box without a GPU (used by the follower only on such a machine; D-1136)"),
    (r"python -m tools\.trialbox\.memcaps .*", "re-measuring or re-sizing the memory caps (the installer sizes them)"),
    (r"tools/make_bundle\.sh", "the vendor builds the bundle"),
    (r"make release-bundle", "the vendor builds the bundle"),
    (r"tools/apply_update\.sh trialbox-<version>\.tar", "step 2: the installer loads the bundle"),
    (r"make images(-multiarch)?", "step 2: a development host builds instead"),
    (r"docker compose exec criteria-compiler .*", "step 2: a synthetic run on a PRODUCTION box, optional"),
    (r"python -m tools\.settings_wizard .*", "step 3: the installer runs the wizard"),
    (r"--answers site\.yaml", "step 3: the installer runs the wizard with the answers"),
    (r"--check deploy/settings\.yaml", "step 3: re-checking an edited file"),
    (r"sudo python3 -m tools\.trialbox secrets init", "step 5: the installer does it"),
    (r"cd deploy && docker compose .*", "step 5: the installer does it"),
    (r"--profile stub", "step 5: the installer does it"),
    (r"deploy/network\.sh apply", "step 5: the installer does it"),
    (r"systemctl enable .*", "step 5: by hand only; the installer does it"),
    (r"deploy/check_host\.sh \[--gb10\]", "step 8: the installer runs the host check"),
]


def path_commands(cmds: list[Command]) -> list[str]:
    return [s.command for s in PLAN if s.action == "run"]


def not_needed(cmds: list[Command]) -> list[dict[str, str]]:
    """Every command of §1 the install path never ran, with its reason; a command with no reason is listed as such."""
    on_path = set(path_commands(cmds))
    out = []
    for c in cmds:
        if c.text in on_path:
            continue
        why = next((w for p, w in NOT_ON_PATH if re.fullmatch(p, c.text)), "no reason in the runbook")
        out.append({"place": c.place, "command": c.text, "why": why})
    return out


# ------------------------------------------------------------------------------------------------ static findings
def _sec(root: Path) -> str:
    return (root / SECTION).read_text(encoding="utf-8")


def _block(root: Path, lead: str) -> str:
    text = _sec(root)
    i = text.index(f"**{lead}**")
    return _fold(text[i : text.find("\n\n", i)])


def _step(root: Path, n: int) -> str:
    m = re.search(rf"^{n}\. \*\*.*?(?=^\d+\. \*\*|^\*\*|\Z)", _sec(root), flags=re.M | re.S)
    return _fold(m.group(0)) if m else ""


def s_no_host_tree(root: Path) -> bool:
    """§1 and the hub never say how /opt/trialbox gets deploy/install.sh (the bundle's host tree) before the one
    command."""
    text = _fold(_sec(root) + (root / HUB).read_text(encoding="utf-8").split("<!-- index:", 1)[0])
    return not re.search(r"trialbox-host\.tar|host tree|unpack|tar -x", text)


def s_vendor_key_after(root: Path) -> bool:
    """The vendor key is step 6, after step 5's start, and the one command never names it; the installer needs it
    at its first step."""
    one = _block(root, "One command.")
    s6 = _step(root, 6)
    return "vendor_ed25519.pub" not in one and "vendor_ed25519.pub" in s6


def s_no_yes(root: Path) -> bool:
    """The one command has no --yes and §1 names no question the installer asks."""
    one = _block(root, "One command.")
    return "--yes" not in one and not re.search(r"\[Y/n\]|asks whether|answer the question", _sec(root))


def s_python_not_python3(root: Path) -> bool:
    """Step 4's check is `python tools/...` on the host: Ubuntu 24.04 has `python3` and no `python`, and the tool
    needs the repository's Python packages, which step 1 does not name."""
    return "`python tools/mapping_check.py" in _fold(_sec(root)).replace("` python", "`python")


def s_host_packages(root: Path) -> bool:
    """Step 1 names Docker Engine and nftables only; the installer also needs the compose plugin and python3 with
    PyYAML (its own HOST-PYTHON check), and the rehearsal's clean host installs them."""
    s1 = _step(root, 1)
    return not re.search(r"compose", s1) or not re.search(r"python3", s1)


def s_tier_vs_stub(root: Path) -> bool:
    """`--mode stub` is given as a fragment next to the one command, whose --tier the installer refuses with it."""
    one = _block(root, "One command.")
    return "`--mode stub`" in one and "--tier large" in one and "drop `--tier`" not in one


def s_compose_cwd(root: Path) -> bool:
    """Step 7's `docker compose exec` names no project folder; only step 5's by-hand line does `cd deploy`."""
    s7 = _step(root, 7)
    return "docker compose exec adapter" in s7 and "--project-directory" not in s7 and "cd deploy" not in s7


def s_report_in_volume(root: Path) -> bool:
    """Step 7's report path `/data/lake/...` is inside a container's volume, not on the host the reader is on."""
    s7 = _step(root, 7)
    return "/data/lake/ndjson/<date>/ingest_report.json" in s7 and "docker compose exec" not in s7.split("Check", 1)[-1]


def s_site_folder_place(root: Path) -> bool:
    """The site's folder (site.yaml beside mapping/) is named, but not where it goes on the box: the one command's
    `--answers site.yaml` is relative to /opt/trialbox."""
    brings = _block(root, "What the site brings")
    return "/opt/trialbox" not in brings and "where" not in brings.split("beside it", 1)[0]


def s_feed_folder_content(root: Path) -> bool:
    """The feed folder must exist at install (a PRODUCTION install stops without it), but §1 never says it must hold
    an export before the one command, nor who puts it there."""
    brings = _block(root, "What the site brings")
    return "data_source_host_dir" in brings and not re.search(r"before the (one command|install)", brings)


STATIC: dict[str, Callable[[Path], bool]] = {
    "no-host-tree": s_no_host_tree,
    "vendor-key-after-start": s_vendor_key_after,
    "unmentioned-questions": s_no_yes,
    "python-not-python3": s_python_not_python3,
    "host-packages-unnamed": s_host_packages,
    "stub-fragment-vs-tier": s_tier_vs_stub,
    "compose-cwd-unstated": s_compose_cwd,
    "ingest-report-in-volume": s_report_in_volume,
    "site-folder-place-unstated": s_site_folder_place,
    "feed-folder-content-unstated": s_feed_folder_content,
}


def static_findings(root: Path = ROOT) -> list[str]:
    return sorted(k for k, fn in STATIC.items() if fn(root))


# ------------------------------------------------------------------------------------------------ machines
@dataclass
class Result:
    rc: int
    out: str
    err: str
    seconds: float


class Machine(Protocol):
    name: str
    has_gpu: bool
    is_root: bool

    def sh(
        self, command: str, *, cwd: str, env: dict[str, str] | None = None, stdin: str = "", timeout: int = 3600
    ) -> Result: ...

    def put(self, src: Path, dest: str) -> None: ...

    def exists(self, path: str) -> bool: ...


def _clip(s: str, n: int = 6000) -> str:
    return s if len(s) <= n else s[: n // 3] + f"\n... ({len(s) - n} characters cut) ...\n" + s[-2 * n // 3 :]


class LocalMachine:
    """A folder standing for the machine's ``/opt`` (the unit test's machine): ``/opt/...`` and ``/media/...`` in a
    command or a cwd are under that folder's parent; PATH is given (the test's stand-ins). It is not a clean machine."""

    def __init__(
        self,
        opt: Path,
        path: str,
        *,
        has_gpu: bool = False,
        extra_env: dict[str, str] | None = None,
        name: str = "local",
        stand_in_markers: tuple[str, ...] = (),
    ) -> None:
        # it stands for root (the hub's "as root"): ``sudo`` is dropped as on a root shell, whoever runs the test
        self.name, self.opt, self.path, self.has_gpu, self.is_root = name, opt, path, has_gpu, True
        # text in the installer's output that means the machine's stand-ins serve no more (a machine stop, never a
        # finding): the unit test's machine has a stand-in docker and a bundle with the host tree only
        self.extra_env, self.stand_in_markers = extra_env or {}, stand_in_markers

    def _map(self, p: str) -> str:
        if self.opt == Path("/opt"):  # the machine itself (a clean VM): the paths are the real ones
            return p
        for top in ("/opt/", "/media/"):
            p = re.sub(rf"(?<![\w./-]){top}", f"{self.opt.parent}{top}", p)
        return p

    def sh(
        self, command: str, *, cwd: str, env: dict[str, str] | None = None, stdin: str = "", timeout: int = 3600
    ) -> Result:
        t0 = time.monotonic()
        d = Path(self._map(cwd))
        if not d.is_dir():
            return Result(1, "", f"cd: {cwd}: No such file or directory", 0.0)
        e = {"PATH": self.path, "HOME": str(self.opt), "LANG": "C.UTF-8", **self.extra_env, **(env or {})}
        p = subprocess.run(
            ["bash", "-c", self._map(command)],
            cwd=d,
            input=stdin,
            capture_output=True,
            text=True,
            env=e,
            timeout=timeout,
            check=False,
        )
        return Result(p.returncode, p.stdout, p.stderr, time.monotonic() - t0)

    def put(self, src: Path, dest: str) -> None:
        to = Path(self._map(dest))
        to.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, to, dirs_exist_ok=True)
        else:
            shutil.copy2(src, to)

    def exists(self, path: str) -> bool:
        return Path(self._map(path)).exists()


class DockerMachine:
    """The box rehearsal's clean Ubuntu 24.04 host (tools/rehearse_box/host.Dockerfile) as a running container that
    uses the Docker host's daemon through its socket: every path a container is started on must be the same on both
    sides, so ``/opt/trialbox`` and the work folder are bind-mounted at their own paths (as the rehearsal does)."""

    def __init__(self, container: str, *, has_gpu: bool = False):
        self.name, self.container, self.has_gpu, self.is_root = "container", container, has_gpu, True

    def sh(
        self, command: str, *, cwd: str, env: dict[str, str] | None = None, stdin: str = "", timeout: int = 3600
    ) -> Result:
        t0 = time.monotonic()
        args = ["docker", "exec", "-i"]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        script = f"cd {shlex.quote(cwd)} && {command}"
        p = subprocess.run(
            [*args, self.container, "bash", "-c", script],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return Result(p.returncode, p.stdout, p.stderr, time.monotonic() - t0)

    def put(self, src: Path, dest: str) -> None:
        subprocess.run(["docker", "exec", self.container, "mkdir", "-p", str(Path(dest).parent)], check=True)
        subprocess.run(
            ["docker", "cp", f"{src}{'/.' if src.is_dir() else ''}", f"{self.container}:{dest}"],
            check=True,
            capture_output=True,
        )

    def exists(self, path: str) -> bool:
        return subprocess.run(["docker", "exec", self.container, "test", "-e", path], check=False).returncode == 0


# ------------------------------------------------------------------------------------------------ lifts
@dataclass(frozen=True)
class Lift:
    key: str
    kind: str  # runbook (a finding's remedy) | bundle (the vendor's media) | machine (lacks what step 1 names)
    source: str  # where the remedy is written
    what: str


LIFTS: dict[str, Lift] = {
    "host-tree": Lift(
        "host-tree",
        "runbook",
        "docs/handover/OFFLINE-MEDIA.md:34 (the Windows media page)",
        "unpack the bundle's own host tree (files/trialbox-host.tar) into /opt/trialbox",
    ),
    "vendor-key-first": Lift(
        "vendor-key-first",
        "runbook",
        "the installer's own message; §1 step 6",
        "place the out-of-band vendor key at deploy/keys/vendor_ed25519.pub before the one command",
    ),
    "drop-tier": Lift(
        "drop-tier",
        "runbook",
        "the installer's own message ('--tier needs the GPU: drop --mode stub')",
        "run the one command with --mode stub in place of --tier large",
    ),
    "no-tpm": Lift(
        "no-tpm",
        "machine",
        "the installer's own message; docs/security/01-the-host.md",
        "TB_KEK_BACKEND=passphrase with a throwaway TB_KEK_PASSPHRASE: the machine has no TPM",
    ),
    "sidecar-name": Lift(
        "sidecar-name",
        "bundle",
        "deploy/install.sh (checks <bundle>.sha256 from the bundle's folder by its bare name)",
        "the stick's <bundle>.sha256 written with the bundle's bare name, as make_bundle.sh writes it for a bare --out",
    ),
    "python3": Lift(
        "python3",
        "runbook",
        "Ubuntu 24.04 names its interpreter python3",
        "run step 4's check as python3 with the release's libs on PYTHONPATH",
    ),
    "compose-dir": Lift(
        "compose-dir",
        "runbook",
        "§1 step 5 ('cd deploy && docker compose ...')",
        "run step 7's compose command from deploy/",
    ),
}


# ------------------------------------------------------------------------------------------------ the follower
@dataclass
class Record:
    """What the follower did, in order; ``findings`` are ids of the committed file's vocabulary."""

    machine: str
    started: str
    runbook_commit: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    lifts: list[str] = field(default_factory=list)
    supplied: list[dict[str, str]] = field(default_factory=list)
    verdict: str = ""
    installed: bool = False
    reached: list[str] = field(default_factory=list)
    seconds: float = 0.0
    commands_run: int = 0
    machine_stop: str = ""

    def find(self, fid: str, step: str, evidence: str) -> None:
        if fid not in {f["id"] for f in self.findings}:
            self.findings.append({"id": fid, "step": step, "evidence": _clip(evidence, 600)})

    def stop(self, step: str, why: str) -> None:
        if not self.verdict:
            self.verdict = f"the runbook alone does not install the box: stopped at {step} because {why}"


PROMPTS = re.compile(r"(\[[YyNn]/[YyNn]\]|\[offline\]:|\(e\.g\. [^)]*\): )")


def _git_head(root: Path) -> str:
    p = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return p.stdout.strip() or "unknown"


class Follower:
    def __init__(
        self,
        machine: Machine,
        *,
        bundle: Path,
        vendor_pub: Path,
        work: Path,
        root: Path = ROOT,
        lifts: bool = True,
        kek_pass: str = "",
        sidecar_fix: Callable[[], None] | None = None,
    ) -> None:
        self.m, self.bundle, self.pub, self.work, self.root, self.allow_lifts = (
            machine,
            bundle,
            vendor_pub,
            work,
            root,
            lifts,
        )
        self.kek_pass = kek_pass
        self.sidecar_fix = sidecar_fix  # rewrites the stick's <bundle>.sha256 (the vendor's media, not the box)
        self.cwd, self.user = convention(root)
        self.rec = Record(machine.name, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), _git_head(root))
        self.env: dict[str, str] = {}

    # -- bookkeeping
    def _lift(self, key: str) -> bool:
        if not self.allow_lifts:
            return False
        self.rec.lifts.append(key)
        return True

    def _run(
        self,
        step: str,
        place: str,
        command: str,
        *,
        stdin: str = "",
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        as_written: str | None = None,
    ) -> Result:
        run = command
        if run.startswith("sudo ") and self.m.is_root:
            run = run[5:]
        r = self.m.sh(run, cwd=cwd or self.cwd, env={**self.env, **(env or {})}, stdin=stdin)
        self.rec.commands_run += 1
        self.rec.seconds += r.seconds
        prompts = sorted(set(PROMPTS.findall(r.out + r.err)))
        self.rec.steps.append(
            {
                "step": step,
                "place": place,
                "as_written": as_written or command,
                "ran": run,
                "cwd": cwd or self.cwd,
                "env": sorted((env or {}) | self.env),
                "rc": r.rc,
                "seconds": round(r.seconds, 1),
                "after_lifts": list(self.rec.lifts),
                "prompts": prompts,
                "out": _clip(redact(r.out)),
                "err": _clip(redact(r.err)),
            }
        )
        return r

    def _note(self, step: str, place: str, what: str) -> None:
        self.rec.steps.append({"step": step, "place": place, "note": what, "after_lifts": list(self.rec.lifts)})

    def _supply(self, what: str, src: str, dest: str, why: str) -> None:
        self.rec.supplied.append({"what": what, "from": src, "to": dest, "why": why})

    # -- the site's kit and the feed: what the runbook tells the reader to bring
    def _site_kit(self) -> None:
        kit = self.work / "site-kit"
        shutil.rmtree(kit, ignore_errors=True)
        kit.mkdir(parents=True)
        text = (self.root / SYNTHETIC_ANSWERS).read_text(encoding="utf-8")
        for k, v in REQUIRED_ANSWERS.items():
            if not re.search(rf"^{k}:", text, flags=re.M):
                text += f"{k}: {v}  # added by the runbook follower: the runbook names it as required (D-1136)\n"
                self._supply(
                    f"answer {k}",
                    "a synthetic value",
                    "site.yaml",
                    "§1 names it as required for a PRODUCTION install; the rehearsal's answers lack it",
                )
        (kit / "site.yaml").write_text(text, encoding="utf-8")
        shutil.copytree(self.root / SYNTHETIC_MAPPING, kit / "mapping")
        dest = f"{self.cwd}"
        self.m.put(kit / "site.yaml", f"{dest}/site.yaml")
        self.m.put(kit / "mapping", f"{dest}/mapping")
        self._supply(
            "the site's folder (site.yaml, mapping/)",
            SYNTHETIC_ANSWERS,
            f"{dest}/",
            "'What the site brings'; values are the hospital's: the rehearsal's synthetic answers; placed where "
            "the one command's relative --answers site.yaml finds it",
        )

    def _feed(self) -> None:
        dest = f"{self.cwd}/deploy/site/feed-a"
        self.m.put(self.root / SYNTHETIC_FEED, dest)
        self._supply(
            "the feed folder's content (the hospital's export)",
            SYNTHETIC_FEED,
            dest,
            "the answers' data_source_host_dir (./site/feed-a); the export is the hospital's",
        )

    # -- the steps
    def follow(self) -> Record:
        self.rec.reached.append("convention")
        if not self.cwd:
            self.rec.find("no-convention", "convention", "the hub names no folder and user for commands")
            self.rec.stop("the convention", "the hub does not say where commands run")
            return self.rec
        self._prereq()
        self._bundle_place()
        self._one_command()
        if self.rec.installed:
            self._mapping_check()
            self._vendor_key_step()
            self._first_ingest()
        self.rec.verdict = self.rec.verdict or "the runbook alone installs the box"
        return self.rec

    def _prereq(self) -> None:
        self.rec.reached.append("1-host")
        checks = {
            "Ubuntu 24.04": "grep -q 'VERSION_ID=\"24.04\"' /etc/os-release",
            "Docker Engine 27+": "v=$(docker version --format '{{.Server.Version}}') && [ \"${v%%.*}\" -ge 27 ]",
            "nftables": "command -v nft",
            "swap off": '[ "$(tail -n +2 /proc/swaps | wc -l)" = 0 ]',
            "TPM2": "[ -e /dev/tpmrm0 ]",
            "LUKS2": "lsblk -o TYPE 2>/dev/null | grep -q crypt",
        }
        got = {k: self.m.sh(v, cwd="/", stdin="").rc == 0 for k, v in checks.items()}
        self._note(
            "1-host",
            f"{SECTION}:73",
            "machine has: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in got.items()),
        )
        self.machine_lacks = [k for k, v in got.items() if not v]

    def _bundle_place(self) -> None:
        # the reader has the bundle "on a USB stick": the follower names it by its path on the machine, as the reader
        # would (trialbox-<version>.tar is the placeholder of the one command)
        self.bundle_on_machine = f"/media/usb/{self.bundle.name}"
        if not self.m.exists(self.bundle_on_machine):  # the container machine has the stick mounted read-only
            self.m.put(self.bundle, self.bundle_on_machine)
        self._supply(
            "the signed bundle", str(self.bundle.name), self.bundle_on_machine, "the one command's <version>.tar"
        )

    def _one_command_text(self, *, stub: bool) -> str:
        cmd = next(s.command for s in PLAN if s.key == "one-command")
        cmd = cmd.replace("trialbox-<version>.tar", self.bundle_on_machine)
        return cmd.replace("--tier large", "--mode stub") if stub else cmd

    def _one_command(self) -> None:
        self.rec.reached.append("one-command")
        place = f"{SECTION}:28"
        as_written = next(s.command for s in PLAN if s.key == "one-command")
        # the cwd of the convention, as the reader finds it
        if not self.m.exists(f"{self.cwd}/deploy/install.sh"):
            r = self._run("one-command", place, self._one_command_text(stub=False), as_written=as_written)
            self.rec.find("no-host-tree", "one-command", f"rc {r.rc}: {r.err.strip()[-300:]}")
            self.rec.stop(
                "the one command (§1:28)",
                "deploy/install.sh is not on the machine: the runbook never says "
                "how /opt/trialbox gets the release's host tree",
            )
            if not self._lift("host-tree"):
                return
            self._unpack_host_tree()
        self._site_kit()
        self._feed()
        stub = False
        stdin = "\n" * 20  # a reader at the terminal presses Enter at a question
        for _attempt in range(8):
            r = self._run("one-command", place, self._one_command_text(stub=stub), stdin=stdin, as_written=as_written)
            text = r.out + r.err
            if r.rc == 0 or self._looks_installed(text):
                self.rec.installed = self._looks_installed(text)
                if r.rc != 0:
                    self.rec.find("exit-1-host-fails", "one-command", _fails(text))
                self._prompts(r)
                if not self.rec.installed:
                    self.rec.stop("the one command (§1:28)", f"the installer exited {r.rc} without the console URL")
                return
            if (
                "bundle checksum mismatch" in text
                and self.sidecar_fix is not None
                and "sidecar-name" not in self.rec.lifts
            ):
                self.rec.find("bundle-sidecar-path", "one-command", _last(text))
                self.rec.stop("the one command (§1:28)", "the bundle's .sha256 beside it names the vendor's path")
                if not self._lift("sidecar-name"):
                    return
                self.sidecar_fix()
                continue
            if "vendor public key missing" in text:
                self.rec.find("vendor-key-after-start", "one-command", _last(text))
                self.rec.stop(
                    "the one command (§1:28)",
                    "the installer needs the vendor key, which the runbook places at step 6, after the start",
                )
                if not self._lift("vendor-key-first"):
                    return
                self.m.put(self.pub, f"{self.cwd}/deploy/keys/vendor_ed25519.pub")
                continue
            if r.rc == 3 and not self.m.has_gpu and not stub:
                # the runbook's own words for a machine without the tier's card: `--mode stub`. Added as written...
                self._note(
                    "one-command",
                    f"{SECTION}:35",
                    "exit 3: this machine has no RTX PRO 6000 (the runbook says "
                    "the installer stops); a box without a GPU: '`--mode stub` installs a box without a GPU'",
                )
                frag = self._one_command_text(stub=False) + " --mode stub"
                r2 = self._run(
                    "one-command", f"{SECTION}:35", frag, stdin=stdin, as_written=f"{as_written} --mode stub"
                )
                if r2.rc != 0 and "drop --mode" in (r2.out + r2.err):
                    self.rec.find("stub-fragment-vs-tier", "one-command", _last(r2.out + r2.err))
                    self.rec.stop(
                        "the one command with `--mode stub` (§1:35)",
                        "the installer refuses --mode stub beside --tier, and the runbook does not say to drop --tier",
                    )
                    if not self._lift("drop-tier"):
                        return
                    stub = True
                    continue
                return
            if "the site keys are not sealed" in text and "TPM" in text and "TB_KEK_BACKEND" not in self.env:
                self.rec.stop("the one command (§1:28)", "the machine has no TPM (step 1 names TPM2): a machine stop")
                if not self._lift("no-tpm"):
                    return
                self.env |= {"TB_KEK_BACKEND": "passphrase", "TB_KEK_PASSPHRASE": self.kek_pass or "rehearsal-only"}
                continue
            if "lacks what the installer needs" in text or "compose plugin is missing" in text:
                self.rec.find("host-packages-unnamed", "one-command", _last(text))
                self.rec.stop("the one command (§1:28)", "the host lacks a package step 1 does not name")
                return
            markers = getattr(self.m, "stand_in_markers", ())
            if any(mk in text for mk in markers):
                self.rec.machine_stop = f"the one command: {_last(text, 300)}"
                self.rec.stop("the one command (§1:28)", "this machine's stand-in serves no more (a machine stop)")
                return
            self._prompts(r)
            self.rec.find("one-command-failed", "one-command", _last(text))
            self.rec.stop("the one command (§1:28)", f"the installer exited {r.rc}: {_last(text, 300)}")
            return

    def _prompts(self, r: Result) -> None:
        seen = PROMPTS.findall(r.out + r.err)
        if seen:
            self.rec.find("unmentioned-questions", "one-command", "; ".join(sorted(set(seen))))

    @staticmethod
    def _looks_installed(text: str) -> bool:
        """The installer's own last words (deploy/install.sh: "TrialBox is running." and the console line)."""
        return "TrialBox is running." in text and bool(re.search(r"Console: +https?://\S+", text))

    def _unpack_host_tree(self) -> None:
        b = self.bundle_on_machine
        r = self._run(
            "lift:host-tree",
            LIFTS["host-tree"].source,
            f"mkdir -p {OPT} && tar -xOf {shlex.quote(b)} files/trialbox-host.tar | tar -x -C {OPT}",
            cwd="/",
            as_written="(lift) unpack the bundle's host tree",
        )
        if r.rc != 0:
            self.rec.stop("the lift host-tree", f"the bundle's host tree did not unpack: {_last(r.err)}")

    def _mapping_check(self) -> None:
        self.rec.reached.append("4-mapping-check")
        step = next(s for s in PLAN if s.key == "4-mapping-check")
        cmd = step.command.replace("<site>", "rehearsal_a").replace("<export dir>", "deploy/site/feed-a")
        self._supply(
            "step 4's <site> and <export dir>",
            "the site kit",
            "rehearsal_a, deploy/site/feed-a",
            "the runbook's placeholders",
        )
        r = self._run("4-mapping-check", f"{SECTION}:101", cmd, as_written=step.command)
        if r.rc == 0 and "missing" in r.out:
            return
        self.rec.find("python-not-python3", "4-mapping-check", f"rc {r.rc}: {_last(r.out + r.err)}")
        if self._lift("python3"):
            r2 = self._run(
                "4-mapping-check",
                f"{SECTION}:101",
                "PYTHONPATH=libs:services:. python3 " + cmd[len("python ") :],
                as_written=step.command,
            )
            if r2.rc != 0:
                self.rec.find("mapping-check-needs-repo-python", "4-mapping-check", _last(r2.out + r2.err))

    def _vendor_key_step(self) -> None:
        self.rec.reached.append("6-vendor-key")
        dest = f"{self.cwd}/deploy/keys/vendor_ed25519.pub"
        if not self.m.exists(dest):
            self.m.put(self.pub, dest)
            self._note("6-vendor-key", f"{SECTION}:111", f"placed the out-of-band key at {dest}")
        else:
            self._note("6-vendor-key", f"{SECTION}:111", "already there (the lift vendor-key-first placed it)")

    def _first_ingest(self) -> None:
        self.rec.reached.append("7-first-ingest")
        step = next(s for s in PLAN if s.key == "7-first-ingest")
        r = self._run("7-first-ingest", f"{SECTION}:112", step.command)
        if r.rc != 0:
            self.rec.find("compose-cwd-unstated", "7-first-ingest", f"rc {r.rc}: {_last(r.err)}")
            if self._lift("compose-dir"):
                r = self._run("7-first-ingest", f"{SECTION}:112", step.command, cwd=f"{self.cwd}/deploy")
        if r.rc != 0:
            self.rec.find("first-ingest-failed", "7-first-ingest", _last(r.out + r.err))
            return
        self.rec.reached.append("7-ingest-report")
        host = self.m.sh("ls /data/lake/ndjson/*/ingest_report.json", cwd="/", stdin="")
        self.rec.commands_run += 1
        if host.rc != 0:
            self.rec.find("ingest-report-in-volume", "7-ingest-report", "/data/lake/ndjson is not on the host")


SECRET_VALUE = re.compile(r"(?i)(\w*(?:password|passphrase|code|token|key|secret)\w*)(\s*[:=]\s*)\S+")


def redact(text: str) -> str:
    """The record never keeps what the installer prints once (the first administrator's password and enrolment
    code) nor any value after a secret's name: the lines of the "first console administrator" step up to its hand-over
    line are dropped, and ``name: value`` of a secret's name keeps the name only."""
    out, skip = [], False
    for ln in text.splitlines():
        if skip:
            if "hand the enrolment code" in ln or "==>" in ln:
                skip = False
                out.append("    [the administrator's password and enrolment code: not recorded]")
                if "==>" in ln:
                    out.append(ln)
            continue
        if "first console administrator" in ln:
            skip = True
        out.append(SECRET_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", ln))
    if skip:
        out.append("    [the administrator's password and enrolment code: not recorded]")
    return "\n".join(out)


def _last(text: str, n: int = 400) -> str:
    lines = [ln for ln in redact(text).strip().splitlines() if ln.strip()]
    return " | ".join(lines[-4:])[-n:]


def _fails(text: str) -> str:
    return " | ".join(ln.strip() for ln in text.splitlines() if ln.strip().startswith("FAIL"))[:600]


# ------------------------------------------------------------------------------------------------ compare
def load_findings(root: Path = ROOT) -> list[dict[str, Any]]:
    return json.loads((root / FINDINGS).read_text(encoding="utf-8"))["findings"]


def compare(run: dict[str, Any], committed: list[dict[str, Any]], static: list[str] | None = None) -> list[str]:
    """Problems between a run's record and the committed findings. Fails on: a run finding the file does not hold
    for this machine; a committed finding of this machine whose step the run reached and did not show; a static
    finding the runbook's text no longer shows, or one it shows that the file does not hold."""
    machine, got, reached = run["machine"], {f["id"] for f in run["findings"]}, set(run["reached"])
    by_id = {f["id"]: f for f in committed}
    out = []
    for i in sorted(got):
        if i not in by_id:
            out.append(f"new finding, not in {FINDINGS}: {i}")
        elif machine not in by_id[i].get("seen_on", []):
            out.append(f"finding {i} now shows on {machine}: add {machine} to its seen_on")
    for f in committed:
        if machine in f.get("seen_on", []) and f.get("step") in reached and f["id"] not in got:
            out.append(f"committed finding no longer reproduces on {machine}: {f['id']} (step {f['step']} was reached)")
    if static is not None:
        held = {f["id"] for f in committed if f.get("static")}
        out += [f"static finding no longer shows in the runbook's text: {i}" for i in sorted(held - set(static))]
        out += [f"static finding not in {FINDINGS}: {i}" for i in sorted(set(static) - held)]
    return out


def quote_problems(committed: list[dict[str, Any]], root: Path = ROOT) -> list[str]:
    """Each committed finding quotes the runbook: the quote must still be in its file."""
    out = []
    for f in committed:
        file = f["place"].split(":", 1)[0]
        if _fold(f["says"]) not in _fold((root / file).read_text(encoding="utf-8")):
            out.append(f"{f['id']}: the runbook no longer says {f['says']!r} ({file})")
    return out


# ------------------------------------------------------------------------------------------------ CLI
def all_commands(root: Path = ROOT) -> list[Command]:
    return extract(SECTION, root)


def _cmd_extract(a: argparse.Namespace) -> int:
    cmds = all_commands()
    if a.json:
        print(json.dumps([asdict(c) | {"fragment": c.fragment} for c in cmds], ensure_ascii=False, indent=1))
    else:
        for i, c in enumerate(cmds, 1):
            print(f"{i:2d} {c.place:48s} [{c.block}] {c.text}")
    return 0


def _cmd_plan(a: argparse.Namespace) -> int:
    for s in PLAN:
        print(f"{s.key:18s} {s.action:13s} {s.command or s.quote}")
    for n in not_needed(all_commands()):
        print(f"  not on the path: {n['place']} {n['command']} ({n['why']})")
    return 0


def _cmd_static(a: argparse.Namespace) -> int:
    for k in static_findings():
        print(k)
    return 0


def _container_up(name: str, image: str, work: Path, usb: Path) -> DockerMachine:
    """The rehearsal's clean host image, started as the rehearsal starts it (tools/rehearse_box/rehearse.sh host_up)."""
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    droot = subprocess.run(
        ["docker", "info", "--format", "{{.DockerRootDir}}"], capture_output=True, text=True, check=True
    ).stdout.strip()
    Path(OPT).mkdir(parents=True, exist_ok=True)
    Path("/run/trialbox").mkdir(parents=True, exist_ok=True)
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--hostname",
        "trialbox-runbook",
        "--network",
        "host",
        "--add-host",
        "trialbox.hospa.test:127.0.0.1",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{OPT}:{OPT}",
        "-v",
        f"{work}:{work}",
        "-v",
        f"{droot}/volumes:{droot}/volumes",
        "-v",
        "/run/trialbox:/run/trialbox",
        "-v",
        f"{usb}:/media/usb:ro",
        image,
        "sleep",
        "infinity",
    ]
    subprocess.run(args, check=True, capture_output=True)
    return DockerMachine(name)


def _cmd_follow(a: argparse.Namespace) -> int:
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if a.machine == "container":
        m: Machine = _container_up(a.container, a.image, work, Path(a.bundle).resolve().parent)
    elif a.machine == "vm":  # a clean VM, as root: the commands run on it, at the runbook's own paths
        if os.geteuid() != 0 or (Path(OPT).exists() and any(Path(OPT).iterdir())):
            raise SystemExit(f"--machine vm runs as root on a machine whose {OPT} is absent or empty")
        m = LocalMachine(Path("/opt"), os.environ.get("PATH", ""), name="vm")
    else:
        opt = work / "opt"
        opt.mkdir(exist_ok=True)
        m = LocalMachine(opt, os.environ.get("PATH", ""))
    t0 = time.monotonic()
    bundle = Path(a.bundle).resolve()
    sidecar = Path(f"{bundle}.sha256")

    def sidecar_fix() -> None:  # the vendor's media: its checksum line with the bundle's bare name
        digest = sidecar.read_text(encoding="utf-8").split()[0]
        sidecar.write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")

    f = Follower(
        m,
        bundle=bundle,
        vendor_pub=Path(a.vendor_pub).resolve(),
        work=work,
        lifts=not a.strict,
        kek_pass=os.environ.get("TB_RUNBOOK_KEK_PASSPHRASE", ""),
        sidecar_fix=sidecar_fix if sidecar.is_file() else None,
    )
    rec = f.follow()
    out = asdict(rec) | {
        "wall_seconds": round(time.monotonic() - t0, 1),
        "not_needed": not_needed(all_commands()),
        "static": static_findings(),
        "machine_lacks": getattr(f, "machine_lacks", []),
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(rec.verdict)
    print(f"commands run: {rec.commands_run}, command time {rec.seconds:.0f} s, wall {out['wall_seconds']} s")
    for x in rec.findings:
        print(f"  finding {x['id']} at {x['step']}: {x['evidence'][:160]}")
    return 0


def _sh(args: list[str], log: Path, *, env: dict[str, str] | None = None, check: bool = True) -> int:
    """One vendor-side or teardown command, its output appended to ``log``."""
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(args)}\n")
        fh.flush()
        rc = subprocess.run(
            args, stdout=fh, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})}, cwd=ROOT, check=False
        ).returncode
    if check and rc != 0:
        raise SystemExit(f"runbook_install run: {args[0]} {' '.join(args[1:3])} failed (exit {rc}); see {log}")
    return rc


# the images a box without a GPU runs (the box's compose files, profile stub) and the nightly backup's job image
OUR_IMAGES = ["trialbox-py:1.0.0", "trialbox-jvm:1.0.0", "trialbox-postgres:16-1", "trialbox-embed:1.0.0"]
JOB_IMAGES = ["trialbox-backup:1.0.0"]


def vendor_bundle(work: Path, py: str) -> tuple[Path, Path, list[tuple[str, str]]]:
    """A site bundle made the vendor's way (as the box rehearsal's media step makes its own, but not ``--rehearsal``:
    a site box refuses a rehearsal bundle): a throwaway vendor key, the release gates over exactly these images,
    ``tools/make_bundle.sh`` with the reference data pack. Returns the bundle, the public key, and (ref, id) of each
    image."""
    v, log = work / "vendor", work / "logs" / "vendor.log"
    shutil.rmtree(v, ignore_errors=True)
    (v / "cfg").mkdir(parents=True)
    _sh([py, "tools/sign_bundle.py", "keygen", "--out", str(v / "keys")], log)
    _sh([py, "tools/refdata_fetch.py", "sample", "--out", str(v / "refdata")], log)
    pack = next((v / "refdata").glob("trialbox-refdata-*.tar"))
    answers = (ROOT / SYNTHETIC_ANSWERS).read_text(encoding="utf-8")
    tz = re.search(r"^tz: *['\"]?([A-Za-z0-9_+/-]+)", answers, flags=re.M)
    host = re.search(r"^tls_hostname: *['\"]?([A-Za-z0-9._-]+)", answers, flags=re.M)
    if not tz or not host:
        raise SystemExit(f"{SYNTHETIC_ANSWERS} names no tz or tls_hostname")
    (v / "cfg" / ".env").write_text(f"TB_TZ={tz.group(1)}\nTB_TLS_HOSTNAME={host.group(1)}\n", encoding="utf-8")
    listed = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(v / "cfg"),
            "-f",
            "deploy/docker-compose.yml",
            "-f",
            "deploy/docker-compose.secrets.yml",
            "-f",
            "deploy/docker-compose.identity.yml",
            "--profile",
            "stub",
            "config",
            "--images",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    third = sorted({i for i in listed if not i.startswith("trialbox-")})
    imgs = OUR_IMAGES + JOB_IMAGES + third
    pairs = []
    for i in imgs:
        if subprocess.run(["docker", "image", "inspect", i], capture_output=True, check=False).returncode != 0:
            _sh(["docker", "pull", "-q", i], log)
        iid = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", i], capture_output=True, text=True, check=True
        ).stdout.strip()
        pairs.append((i, iid))
    _sh(
        [
            "make",
            "release-gates",
            f"PY={py}",
            "SC_LOCAL_IMAGES=1",
            f"SC_DIR={v / 'gates'}",
            f"SC_IMAGES={' '.join(imgs)}",
        ],
        log,
    )
    stamp = time.strftime("%Y%m%d", time.gmtime())
    bundle = work / "media" / f"trialbox-runbook-{stamp}.tar"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "tools/make_bundle.sh",
        "--allow-dirty",
        "the runbook follower's measurement (H-22)",
        "--key",
        str(v / "keys" / "vendor_ed25519.key"),
        "--id",
        f"runbook-{stamp}",
        "--release-seq",
        "1",
        "--out",
        str(bundle),
        "--gates",
        str(v / "gates" / "gates.json"),
        "--sbom-dir",
        "dist/sbom",
        "--refdata",
        str(pack),
    ]
    for i in imgs:
        args += ["--job-image" if i in JOB_IMAGES else "--image", i]
    _sh(args, log)
    # the images the bundle carries, by id, beside it (as the rehearsal's bundle-images.txt): --bundle reads it
    Path(f"{bundle}.images").write_text("".join(f"{r} {i}\n" for r, i in pairs), encoding="utf-8")
    return bundle, v / "keys" / "vendor_ed25519.pub", pairs


def _restore(bundle: Path, pairs: list[tuple[str, str]], log: Path) -> None:
    for ref, _ in pairs:
        if subprocess.run(["docker", "image", "inspect", ref], capture_output=True, check=False).returncode == 0:
            continue
        member = "files/" + ref.replace("/", "_").replace(":", "_") + ".tar"
        with log.open("a", encoding="utf-8") as fh:
            tar = subprocess.Popen(["tar", "-xOf", str(bundle), member], stdout=subprocess.PIPE)
            subprocess.run(["docker", "load"], stdin=tar.stdout, stdout=fh, stderr=subprocess.STDOUT, check=False)
            tar.wait()


def _cmd_run(a: argparse.Namespace) -> int:
    """The whole container run: the clean host image, a site bundle, the box images cleared from the Docker host,
    the follower, the comparison, the teardown."""
    work = Path(a.work).resolve()
    (work / "logs").mkdir(parents=True, exist_ok=True)
    log = work / "logs" / "run.log"
    py = a.py or sys.executable
    build = ["docker", "build", "-f", "tools/rehearse_box/host.Dockerfile", "-t", a.image, "tools/rehearse_box/shims"]
    if os.environ.get("HTTPS_PROXY"):
        build[2:2] = ["--network", "host", "--build-arg", f"https_proxy={os.environ['HTTPS_PROXY']}"]
    if os.environ.get("TB_EXTRA_CA"):
        build[2:2] = ["--secret", f"id=extra_ca,src={os.environ['TB_EXTRA_CA']}"]
    _sh(build, log)
    if a.bundle:
        bundle, pub = Path(a.bundle).resolve(), Path(a.vendor_pub).resolve()
        listed = Path(f"{bundle}.images")
        pairs: list[tuple[str, str]] = []
        if listed.is_file():
            pairs = [(r, i) for r, i in (ln.split() for ln in listed.read_text(encoding="utf-8").splitlines() if ln)]
    else:
        bundle, pub, pairs = vendor_bundle(work, py)
    # the USB stick: the bundle and its .sha256 as the vendor handed them over, in a folder of their own (mounted
    # read-only at /media/usb in the machine); a lift may rewrite the stick's checksum file, never the vendor's copy
    usb = work / "usb"
    shutil.rmtree(usb, ignore_errors=True)
    usb.mkdir(parents=True)
    os.link(bundle, usb / bundle.name)
    if Path(f"{bundle}.sha256").is_file():
        shutil.copy2(f"{bundle}.sha256", usb / f"{bundle.name}.sha256")
    bundle = usb / bundle.name
    if subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=trialbox"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip():
        raise SystemExit("a TrialBox compose project already exists on this Docker host: take it down first")
    if any(Path(OPT).iterdir()) if Path(OPT).is_dir() else False:
        raise SystemExit(f"{OPT} is not empty on the Docker host: the follower needs it empty")
    for _ref, iid in pairs:  # only the bundle may bring them back (as the box rehearsal clears them)
        _sh(["docker", "image", "rm", "-f", iid], log, check=False)
    try:
        args = argparse.Namespace(**{**vars(a), "machine": "container", "bundle": str(bundle), "vendor_pub": str(pub)})
        _cmd_follow(args)
    finally:
        if not a.keep:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    a.container,
                    "sh",
                    "-c",
                    f"cd {OPT} && [ -f deploy/.env ] && docker compose --project-directory deploy down -v "
                    "--remove-orphans",
                ],
                capture_output=True,
                check=False,
            )
            subprocess.run(["docker", "rm", "-f", a.container], capture_output=True, check=False)
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{OPT}:/t",
                    "-v",
                    "/run/trialbox:/k",
                    "ubuntu:24.04",
                    "sh",
                    "-c",
                    "rm -rf /t/* /t/.[!.]* /k/kek",
                ],
                capture_output=True,
                check=False,
            )
            if pairs:
                _restore(bundle, pairs, log)
    return _cmd_compare(argparse.Namespace(run=a.out))


def _cmd_compare(a: argparse.Namespace) -> int:
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    probs = compare(run, load_findings(), static_findings()) + quote_problems(load_findings())
    for p in probs:
        print(p)
    if not probs:
        print(f"ok: {len(run['findings'])} run findings, every committed finding of {run['machine']} reproduced")
    return 1 if probs else 0


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.runbook_install", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--json", action="store_true")
    sub.add_parser("plan")
    sub.add_parser("static")
    f = sub.add_parser("follow")
    f.add_argument("--bundle", required=True)
    f.add_argument("--vendor-pub", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--work", default=WORK_DEFAULT)
    f.add_argument("--machine", choices=["container", "vm", "local"], default="container")
    f.add_argument("--image", default="trialbox-runbook-host:24.04")
    f.add_argument("--container", default="tb-runbook-host")
    f.add_argument("--strict", action="store_true", help="no lifts: stop at the verdict")
    r = sub.add_parser("run", help="the whole container run (make runbook-install)")
    r.add_argument("--out", default="docs/plan/measurements/runbook-install-2026-11-17/run-container.json")
    r.add_argument("--work", default=WORK_DEFAULT)
    r.add_argument("--image", default="trialbox-runbook-host:24.04")
    r.add_argument("--container", default="tb-runbook-host")
    r.add_argument("--bundle", default="", help="a site bundle already made (else one is made the vendor's way)")
    r.add_argument("--vendor-pub", default="")
    r.add_argument("--py", default="")
    r.add_argument("--strict", action="store_true")
    r.add_argument("--keep", action="store_true", help="leave the box and the machine running")
    c = sub.add_parser("compare")
    c.add_argument("run")
    a = ap.parse_args(list(argv) if argv is not None else None)
    return {
        "extract": _cmd_extract,
        "plan": _cmd_plan,
        "static": _cmd_static,
        "follow": _cmd_follow,
        "compare": _cmd_compare,
        "run": _cmd_run,
    }[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
