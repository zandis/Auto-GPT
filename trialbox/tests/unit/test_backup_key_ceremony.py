"""10K-13 (D-1379): the backup-key ceremony in four resumable steps (the owner's design of 2026-11-20).

Step 1 the key file and the sheet on the stick, step 2 both read back, step 3 the event through the orchestrator's
journal, step 4 ``backup.pub`` made new, last. Nothing is undone or deleted; a run cut short is finished by the same
command with the same stick; "once" is ``backup.pub``. The journal is a stand-in for ``docker compose exec
orchestrator`` (``bkc.COMPOSE``; ``TB_COMPOSE`` is set to ``true`` and must be ignored) that runs the command's own journal code against a stub writer and keeps every call's
arguments and environment, so the tests can look for the key in them. The stick's removable-media check is replaced
by a stub (H2 is tested on its own, on a made-up ``/sys``). Every key is made in the test's tmp folder; the tests pass
as root and as any other user (the ownership checks compare with the user running them).
"""

from __future__ import annotations

import ast
import base64
import errno
import fcntl
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest

from tools import backup_key_ceremony as bkc
from tools import core_words
from tools.trialbox import backup as bk

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
OP, WIT, SITE = "IT Person One", "Witness Two", "site-test-01"
SWAPS_HEAD = "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"

FAKE_COMPOSE = r"""
import json, os, signal, sys, types
state, rest = sys.argv[1], sys.argv[2:]
with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv, "env": dict(os.environ)}) + "\n")
assert rest[:5] == ["exec", "-T", "orchestrator", "python", "-c"], rest[:5]
code, args = rest[5], rest[6:]
flag = lambda n: os.path.exists(os.path.join(state, n))
if args[:1] == ["record"] and flag("fail_record"):  # the container answers non-zero before the code runs
    sys.exit(1)
if args[:1] == ["record"] and flag("silent"):  # a no-op that answers success and stores nothing
    sys.exit(0)
journal = os.path.join(state, "journal.jsonl")
class DbAuditWriter:
    _dsn = "stand-in"
    def append(self, event, **fields):
        if flag("append_raises"):  # the journal refuses inside append (AuditUnavailable is an OSError)
            raise OSError("the audit journal cannot be reached")
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, **fields}) + "\n")
        with open(journal, encoding="utf-8") as f:
            return {"event": event, "journal": {"seq": len(f.read().splitlines())}}
class FileWriter:
    def append(self, event, **fields):
        raise AssertionError("a file-mode writer must never be appended to")
class Con:
    def execute(self, sql):
        assert "audit" in sql and "append" in sql
        return types.SimpleNamespace(fetchone=lambda: (not flag("no_schema"),))
    def close(self):
        pass
def connect(dsn, connect_timeout):
    if flag("db_down"):
        raise OSError("connection refused")
    return Con()
mod = types.ModuleType("tb_common.audit_writer")
mod.DbAuditWriter = DbAuditWriter
mod._psycopg = lambda: types.SimpleNamespace(connect=connect)
mod.open_audit = lambda: FileWriter() if flag("file_mode") else DbAuditWriter()
sys.modules.update({"tb_common": types.ModuleType("tb_common"), "tb_common.audit_writer": mod})
sys.argv = ["-c", *args]
exec(compile(code, "<orchestrator>", "exec"), {"__name__": "__main__"})
"""

DRIVER = r"""
import json, os, signal, sys
from pathlib import Path
from tools import backup_key_ceremony as b
cfg = json.loads(sys.argv[1])
b.DEPLOY = Path(cfg["deploy"]); b.PUB_DIR = b.DEPLOY / "secrets"
b.COMPOSE = cfg["compose"]
b.is_root = lambda: True
b.stick_problem = lambda dev, devs: False
def after(name, when=lambda *a: True):
    real = getattr(b, name)
    def wrapped(*a, **k):
        out = real(*a, **k)
        if when(*a):
            os.kill(os.getpid(), signal.SIGKILL)
        return out
    setattr(b, name, wrapped)
stop = cfg.get("stop")
if stop == "pending":
    after("_pending")
elif stop == "key-temp":
    after("_write_temp", lambda fd, data, name: name == b.KEY_FILE)
elif stop == "key-file":
    after("_rename_into", lambda dfd, tmp, name: name == b.KEY_FILE)
elif stop == "sheet-temp":
    after("_write_temp", lambda fd, data, name: name == b.PAPER_FILE)
elif stop == "step1":
    after("_sync_dir", lambda dfd, n: n == 1 and not os.path.samestat(os.fstat(dfd), os.stat(b.PUB_DIR)))
elif stop == "step2":
    after("_on_stick")
elif stop == "step3":
    after("record")
elif stop == "step4-link":
    after("_link_pub")
# the host-safety probe's swap list, injected: the steps are driven on any host (a CI runner that is not root and has
# swap on included); the real refusal on such a host is test_h_5's own process
b.SWAPS = Path(cfg["swaps"] or cfg["no_swap"])
if cfg.get("spy"):
    real_new = b.new_key
    def spied():
        import ctypes, resource
        locked = [ln for ln in open("/proc/self/status") if ln.startswith("VmLck:")][0].split()[1]
        seen = {"dumpable": ctypes.CDLL(None).prctl(3, 0, 0, 0, 0), "core": list(resource.getrlimit(resource.RLIMIT_CORE)),
                "locked_kb": int(locked), "swap_on": b._swap_on()}
        Path(cfg["spy"]).write_text(json.dumps(seen))
        return real_new()
    b.new_key = spied
sys.exit(b.main(cfg["argv"]))
"""


# ------------------------------------------------------------------------------------------------ the box
class Box:
    def __init__(self, tmp: Path) -> None:
        self.tmp, self.deploy, self.state = tmp, tmp / "deploy", tmp / "orchestrator"
        self.pub_dir, self.pub = self.deploy / "secrets", self.deploy / "secrets" / "backup.pub"
        for d in (self.pub_dir, self.state):
            d.mkdir(parents=True, mode=0o700)
        os.chmod(self.deploy, 0o755)
        (tmp / "fake_compose.py").write_text(FAKE_COMPOSE, encoding="utf-8")
        (tmp / "driver.py").write_text(DRIVER, encoding="utf-8")
        self.compose = [sys.executable, str(tmp / "fake_compose.py"), str(self.state)]
        self.out: list[str] = []
        self.no_swap = tmp / "no-swaps"  # a swap list with no swap area in it
        self.no_swap.write_text(SWAPS_HEAD)

    def stick(self, name: str = "usb") -> Path:
        s = self.tmp / name
        s.mkdir(mode=0o700)
        return s

    def flag(self, name: str, on: bool = True) -> None:
        f = self.state / name
        f.write_text("") if on else f.unlink()

    def pending(self) -> list[str]:
        return sorted(p.name for p in self.pub_dir.glob("backup-ceremony-*.pending"))

    def journal(self) -> list[dict[str, Any]]:
        f = self.state / "journal.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []

    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUNBUFFERED", "TB_BACKUP_PUBKEY")}
        env.update(PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")),
                   TB_COMPOSE="true", TB_SITE_ID=SITE)  # fmt: skip
        return env

    def drive(
        self, stick: Path, stop: str | None = None, spy: Path | None = None, swaps: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """The command in a process of its own; ``stop``: SIGKILL right after that point."""
        argv = ["--stick", str(stick), "--operator", OP, "--witness", WIT]
        cfg = {"deploy": str(self.deploy), "stop": stop, "argv": argv, "spy": str(spy) if spy else None,
               "compose": self.compose, "swaps": str(swaps) if swaps else None,
               "no_swap": str(self.no_swap)}  # fmt: skip
        r = subprocess.run([sys.executable, str(self.tmp / "driver.py"), json.dumps(cfg)], cwd=ROOT, env=self.env(),
                           capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
        self.out += [r.stdout, r.stderr]
        return r


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    b = Box(tmp_path)
    monkeypatch.setattr(bkc, "DEPLOY", b.deploy)
    monkeypatch.setattr(bkc, "PUB_DIR", b.pub_dir)
    monkeypatch.setattr(bkc, "COMPOSE", b.compose)
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    monkeypatch.setattr(bkc, "stick_problem", lambda dev, devs: False)
    monkeypatch.setattr(bkc, "harden", lambda: None)  # H1 runs for real in the processes of the driver
    for k, v in b.env().items():
        if k.startswith("TB_"):
            monkeypatch.setenv(k, v)
    monkeypatch.delenv("TB_BACKUP_PUBKEY", raising=False)
    monkeypatch.delenv("TB_BACKUP_TARGETS", raising=False)
    return b


def _main(box: Box, stick: Path, capsys: pytest.CaptureFixture[str], *more: str) -> tuple[int, str, str]:
    code = bkc.main(["--stick", str(stick), "--operator", OP, "--witness", WIT, *more])
    out, err = capsys.readouterr()
    box.out += [out, err]
    return code, out, err


def _tree(root: Path) -> dict[str, bytes | str]:
    out: dict[str, bytes | str] = {}
    for p in sorted(root.rglob("*")):
        if p.name == "calls.jsonl":  # the journal stand-in's own log of each call (the check call is made)
            continue
        if p.is_symlink():
            out[str(p)] = f"-> {os.readlink(p)}"
        elif p.is_file():
            out[str(p)] = p.read_bytes()
        elif not p.is_dir():
            out[str(p)] = "special"
    return out


def _stick_key(stick: Path) -> bytes | None:
    f = stick / bkc.KEY_FILE
    return bkc.read_key(f.read_bytes()) if f.is_file() else None


# ------------------------------------------------------------------------------------------------ the leak scan (M8)
def leaks(blob: bytes, raw: bytes) -> list[str]:
    """Each form of the private key ``raw`` found in ``blob``: the bytes, hex, base64, base32, and base32 in any
    grouping (the text with every character outside the base32 alphabet removed, searched for each full line of the
    sheet), so the key file and the sheet themselves are found (M8 of the last review)."""
    text = blob.decode("latin-1")
    b32 = base64.b32encode(raw).decode().rstrip("=")
    forms = {"raw": raw.decode("latin-1"), "hex": raw.hex(), "HEX": raw.hex().upper(),
             "b64": base64.b64encode(raw).decode().rstrip("="), "b64url": base64.urlsafe_b64encode(raw).decode()[:40],
             "b32": b32}  # fmt: skip
    found = [k for k, v in forms.items() if v in text]
    squeezed = re.sub(r"[^A-Z2-7]", "", text.upper())
    found += [f"b32 line {i // 16 + 1}" for i in range(0, len(b32) - 15, 16) if b32[i : i + 16] in squeezed]
    return found


def _off_stick_leaks(box: Box, raws: list[bytes], sticks: list[Path]) -> list[str]:
    blobs = {f"output {i}": s.encode() for i, s in enumerate(box.out)}
    for p in box.tmp.rglob("*"):
        if p.is_file() and not p.is_symlink() and not any(p.is_relative_to(s) for s in sticks):
            blobs[str(p)] = p.read_bytes()
    return [f"{name}: {form}" for raw in raws for name, b in blobs.items() for form in leaks(b, raw)]


def test_the_leak_scan_finds_the_key_in_the_key_file_and_in_the_sheet_m8() -> None:
    raw = bkc.new_key()
    assert leaks(bkc.key_text(raw), raw) and leaks(bkc.paper_sheet(raw, SITE, "now"), raw)
    grouped = "-".join(base64.b32encode(raw).decode()[i : i + 2] for i in range(0, 52, 2))
    assert leaks(f"printed: {grouped.lower()}".encode(), raw)
    assert leaks(b"x" + raw + b"y", raw) and leaks(raw.hex().encode(), raw)
    assert not leaks(bkc.key_text(bkc.new_key()), raw)


# ------------------------------------------------------------------------------------------------ THE INVARIANT
def _invariant(box: Box, sticks: list[Path]) -> None:
    """backup.pub exists only if the journal holds the ceremony event for its key, the box holds that key's record from
    before the stick did, and the stick's key file and sheet read back equal to that key; and no private key byte is in
    the journal, the outputs or any file off the stick."""
    raws = [k for s in sticks if (k := _stick_key(s)) is not None]
    if box.pub.exists():
        fp = bk.fingerprint(bk.load_public(box.pub).public_bytes_raw())
        events = [e for e in box.journal() if e["event"] == bkc.EVENT and e["detail"]["fingerprint"] == fp]
        assert events and all(e["detail"]["operator"] == OP and e["detail"]["witness"] == WIT for e in events)
        assert bkc.pending_name(fp) in box.pending()
        holder = [s for s in sticks if (k := _stick_key(s)) is not None and bkc.fingerprint(bkc.public_of(k)) == fp]
        assert holder, "backup.pub names a key no stick holds"
        s = holder[0]
        sheet = bkc.read_sheet((s / bkc.PAPER_FILE).read_bytes())
        assert sheet is not None and sheet[0] == _stick_key(s) and sheet[1] == SITE
        pub = bk.load_public(box.pub).public_bytes_raw()
        assert bk.load_private(s / bkc.KEY_FILE).public_key().public_bytes_raw() == pub
    assert _off_stick_leaks(box, raws, sticks) == []


KILLS = ["pending", "key-temp", "key-file", "sheet-temp", "step1", "step2", "step3", "step4-link"]
NEW_KEY_ON_RERUN = ("pending", "key-temp")  # the stick has no key file yet: the rerun makes a new key
JOURNAL_FAILS = ["fail_record", "append_raises", "silent"]


@pytest.mark.parametrize("stop", KILLS + JOURNAL_FAILS)
def test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point(box: Box, stop: str) -> None:
    """Killed (SIGKILL) right after each point, or stopped by a journal that fails (the container answers non-zero,
    the journal refuses inside append, or a no-op answers success and stores nothing), then the same command again
    with the same stick: the invariant holds in the state left and after the rerun, which finishes the run with the
    same key (or a new one when the stick was still empty), or says it is done."""
    stick = box.stick()
    if stop in JOURNAL_FAILS:
        box.flag(stop)
    r = box.drive(stick, stop=None if stop in JOURNAL_FAILS else stop)
    if stop in JOURNAL_FAILS:
        assert r.returncode == 1 and r.stderr.strip() == bkc.JOURNAL_UNSURE["en"], r.stdout + r.stderr
        box.flag(stop, on=False)
    else:
        assert r.returncode == -signal.SIGKILL, r.stdout + r.stderr
    _invariant(box, [stick])
    assert box.pub.exists() == (stop == "step4-link")
    assert (stick / bkc.PAPER_FILE).exists() == (stop not in ("pending", "key-temp", "key-file", "sheet-temp"))
    key = _stick_key(stick)
    assert (key is None) == (stop in NEW_KEY_ON_RERUN) and len(box.pending()) == 1
    assert all(p.name in (bkc.KEY_FILE, bkc.PAPER_FILE) or p.name.endswith(".part") for p in stick.iterdir())
    r = box.drive(stick)
    if stop == "step4-link":
        assert r.returncode == 1 and "the ceremony is done already" in r.stderr
    else:
        assert r.returncode == 0, r.stdout + r.stderr
        assert "done: backup key" in r.stdout
    if key is not None:
        assert _stick_key(stick) == key  # the rerun finished the run cut short, with its key
    assert len(box.pending()) == (2 if stop in NEW_KEY_ON_RERUN else 1)  # an abandoned key's record stays
    finals = sorted(p.name for p in stick.iterdir() if not p.name.endswith(".part"))
    assert finals == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])  # a temporary file a cut run left is never read again
    assert len(box.journal()) == (2 if stop == "step3" else 1)  # a rerun after step 3 records the event again
    _invariant(box, [stick])
    assert box.drive(stick).returncode == 1  # once: backup.pub
    _invariant(box, [stick])


# ------------------------------------------------------------------------------------------------ the whole run
def test_the_ceremony_writes_the_stick_reads_it_back_records_and_then_makes_backup_pub(box: Box, capsys: Any) -> None:
    stick = box.stick()
    old = os.umask(0o077)  # backup.pub and the record are 0644 whatever root's umask (A-L3)
    try:
        code, out, err = _main(box, stick, capsys)
    finally:
        os.umask(old)
    assert code == 0 and err == "", err
    raw = _stick_key(stick)
    assert raw is not None
    pub = bk.load_private(stick / bkc.KEY_FILE).public_key().public_bytes_raw()  # restore --key reads it
    assert bk.load_public(box.pub).public_bytes_raw() == pub
    fp = bk.fingerprint(pub)
    [ev] = box.journal()
    assert ev == {"event": bkc.EVENT, "actor": bkc.ACTOR, "detail": {"fingerprint": fp, "operator": OP, "witness": WIT,
                  "site": SITE, "stick": "key file and sheet file read back after sync"}}  # fmt: skip
    assert bkc.read_sheet((stick / bkc.PAPER_FILE).read_bytes()) == (raw, SITE)
    assert sorted(p.name for p in stick.iterdir()) == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])  # every temporary renamed
    for name in (bkc.KEY_FILE, bkc.PAPER_FILE):
        assert stat.S_IMODE((stick / name).stat().st_mode) == 0o600
    assert out.strip() == bkc.DONE["en"].format(fp=fp, key=bkc.KEY_FILE, paper=bkc.PAPER_FILE, operator=OP,
                                               witness=WIT, pub=box.pub, seq=1)  # fmt: skip
    assert sorted(p.name for p in box.pub_dir.iterdir()) == [bkc.pending_name(fp), "backup.pub"]
    for p in box.pub_dir.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o644
    assert (box.pub_dir / bkc.pending_name(fp)).read_text().splitlines()[:2] == [
        f"fingerprint {fp}", f"public {base64.b64encode(pub).decode()}"]  # fmt: skip
    calls = [json.loads(x) for x in (box.state / "calls.jsonl").read_text().splitlines()]
    assert [c["argv"][8] for c in calls] == ["check", "record"]  # the stand-in reached, TB_COMPOSE=true ignored
    _invariant(box, [stick])
    code, _, err = _main(box, stick, capsys, "--lang", "ja")
    assert code == 1 and err.strip() == bkc.ALREADY["ja"].format(pub=box.pub, fp=fp)


def test_the_paper_sheet_restores_by_its_printed_instruction(box: Box, capsys: Any) -> None:
    """B-M4: the sheet says to type only the letters between the two bars of each numbered line into a file and give
    it to restore --key; doing exactly that gives the key (master's backup.load_private, unchanged)."""
    stick = box.stick()
    assert _main(box, stick, capsys)[0] == 0
    sheet = (stick / bkc.PAPER_FILE).read_text(encoding="utf-8")
    assert "type only the letters between the two bars of each numbered line" in sheet
    typed = [ln.split("|")[1].strip() for ln in sheet.splitlines() if re.match(r"\d+ \|", ln)]
    (stick / "typed.txt").write_text("\n".join(typed) + "\n", encoding="utf-8")
    assert (
        bk.load_private(stick / "typed.txt").public_key().public_bytes_raw()
        == bk.load_public(box.pub).public_bytes_raw()
    )


def test_h1_not_dumpable_and_no_core_before_the_key_exists(box: Box) -> None:
    """H1: in the command's own process, the key is made only once it is not dumpable and has no core limit; and
    ``harden()`` is the first statement of ``main()``."""
    spy = box.tmp / "spy.json"
    r = box.drive(box.stick(), spy=spy)
    assert r.returncode == 0, r.stderr
    seen = json.loads(spy.read_text())
    assert (seen["dumpable"], seen["core"]) == (0, [0, 0])
    main = next(n for n in ast.parse(Path(bkc.__file__).read_text()).body if getattr(n, "name", "") == "main")
    first = main.body[0]  # type: ignore[attr-defined]
    assert isinstance(first, ast.Try) and ast.unparse(first.body[0]) == "harden()"


# ------------------------------------------------------------------------------------------------ refusals
REFUSALS = ["not-root", "no-witness", "bad-name", "same-person", "pub-dir-missing", "pub-dir-shared",
            "pub-parent-shared", "pub-elsewhere", "busy", "no-tmpfile", "file-mode-journal", "journal-db-down",
            "journal-without-schema", "no-orchestrator", "a-no-op-orchestrator", "socket-not-roots", "no-stick",
            "not-a-stick", "stick-folder-shared"]  # fmt: skip


@pytest.mark.parametrize("case", REFUSALS)
def test_a_refusal_writes_nothing(box: Box, case: str, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    stick, args, want = box.stick(), ["--operator", OP, "--witness", WIT], ""
    if case == "not-root":
        monkeypatch.setattr(bkc, "is_root", lambda: False)
        want = bkc.NOT_ROOT["en"]
    elif case == "no-witness":
        args, want = ["--operator", OP], bkc.NO_NAMES["en"]
    elif case == "bad-name":
        args, want = ["--operator", "a\nb", "--witness", WIT], bkc.BAD_NAME["en"]
    elif case == "same-person":
        args, want = ["--operator", OP, "--witness", "ｉｔ　ｐｅｒｓｏｎ  ONE"], bkc.SAME_PERSON["en"]
    elif case == "pub-dir-missing":
        box.pub_dir.rmdir()
        want = bkc.PUB_DIR_UNSAFE["en"].format(path=box.pub_dir)
    elif case == "pub-dir-shared":
        os.chmod(box.pub_dir, 0o777)
        want = bkc.PUB_DIR_UNSAFE["en"].format(path=box.pub_dir)
    elif case == "pub-parent-shared":  # A-L5: a folder above it that others may write (no sticky bit)
        os.chmod(box.deploy, 0o777)
        want = bkc.PUB_DIR_UNSAFE["en"].format(path=box.pub_dir)
    elif case == "pub-elsewhere":
        monkeypatch.setenv("TB_BACKUP_PUBKEY", str(box.tmp / "other.pub"))
        want = bkc.PUB_ELSEWHERE["en"].format(path=box.tmp / "other.pub", pub=box.pub)
    elif case == "busy":  # A-M1: another run holds the folder's lock
        held = os.open(box.pub_dir, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(held, fcntl.LOCK_EX)
        want = bkc.BUSY["en"]
    elif case == "no-tmpfile":  # A-L2: found before step 1, not after the journal
        real_open = os.open

        def no_tmpfile(path: Any, flags: int, *a: Any, **k: Any) -> int:
            if flags & os.O_TMPFILE == os.O_TMPFILE:
                raise OSError(errno.EOPNOTSUPP, "Operation not supported")
            return real_open(path, flags, *a, **k)

        monkeypatch.setattr(os, "open", no_tmpfile)
        want = bkc.NO_TMPFILE["en"].format(path=box.pub_dir)
    elif case == "file-mode-journal":
        box.flag("file_mode")
        want = bkc.NO_JOURNAL["en"]
    elif case == "journal-db-down":  # B-M2: the journal's database does not answer: refused before any key
        box.flag("db_down")
        want = bkc.NO_JOURNAL["en"]
    elif case == "journal-without-schema":  # review of 36c97bd1, M-6: a database without the journal is no journal
        box.flag("no_schema")
        want = bkc.NO_JOURNAL["en"]
    elif case == "socket-not-roots":  # H-1: only the local daemon's socket, root's, is used
        sock = box.tmp / "docker.sock"
        sock.write_text("")
        monkeypatch.setattr(bkc, "COMPOSE", None)
        monkeypatch.setattr(bkc, "DOCKER_SOCK", str(sock))
        want = bkc.NO_JOURNAL["en"]
    elif case == "no-orchestrator":
        monkeypatch.setattr(bkc, "COMPOSE", [str(box.tmp / "no-such-docker")])
        want = bkc.NO_JOURNAL["en"]
    elif case == "a-no-op-orchestrator":  # B-M3: a command that answers success and does nothing
        monkeypatch.setattr(bkc, "COMPOSE", ["true"])
        want = bkc.NO_JOURNAL["en"]
    elif case == "no-stick":
        stick.rmdir()
        want = bkc.NO_STICK["en"].format(path=stick)
    elif case == "not-a-stick":
        monkeypatch.setattr(bkc, "stick_problem", lambda dev, devs: True)
        want = bkc.NOT_A_STICK["en"].format(path=stick)
    elif case == "stick-folder-shared":
        os.chmod(stick, 0o777)
        want = bkc.STICK_UNSAFE["en"].format(path=stick, name=bkc.KEY_FILE)
    before = _tree(box.tmp)
    code = bkc.main(["--stick", str(stick), *args])
    out, err = capsys.readouterr()
    assert code == 1 and out == "" and err.strip() == want
    assert _tree(box.tmp) == before and box.journal() == []


@pytest.mark.parametrize("kind", ["symlink", "dangling", "hardlink", "fifo", "folder", "huge"])
def test_a_hostile_name_on_the_stick_is_refused_and_never_followed(box: Box, kind: str, capsys: Any) -> None:
    stick, target = box.stick(), box.tmp / "outside.txt"
    target.write_bytes(b"")
    os.chmod(target, 0o600)
    name = stick / bkc.KEY_FILE
    if kind == "symlink":
        name.symlink_to(target)
    elif kind == "dangling":
        name.symlink_to(box.tmp / "nowhere")
    elif kind == "hardlink":
        (stick / "x").write_bytes(b"")
        os.link(stick / "x", name)
    elif kind == "fifo":
        os.mkfifo(name, 0o600)
    elif kind == "folder":
        name.mkdir(mode=0o700)
    else:  # A-L7: a planted large (sparse) file is refused, never read whole
        with name.open("wb") as f:
            f.truncate(1 << 30)
        os.chmod(name, 0o600)
    before = _tree(box.tmp) if kind != "huge" else None
    code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_BROKEN["en"].format(name=bkc.KEY_FILE)
    assert kind == "huge" or _tree(box.tmp) == before
    assert not box.pub.exists() and box.journal() == [] and box.pending() == []
    assert not (box.tmp / "nowhere").exists()


def test_a_planted_whole_key_file_is_never_adopted(box: Box, capsys: Any) -> None:
    """A-HIGH: a stick that already holds a whole, self-consistent key file (from a vendor, another box, an attacker)
    is refused: the box has no record of that key; nothing is written; the planted key is in no journal event."""
    stick, raw = box.stick(), bkc.new_key()
    (stick / bkc.KEY_FILE).write_bytes(bkc.key_text(raw))
    os.chmod(stick / bkc.KEY_FILE, 0o600)
    before = _tree(box.tmp)
    code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_FOREIGN["en"].format(name=bkc.KEY_FILE, path=box.pub_dir)
    assert _tree(box.tmp) == before and box.journal() == [] and not box.pub.exists()
    assert _main(box, box.stick("usb-empty"), capsys)[0] == 0  # an empty stick then works
    assert bkc.fingerprint(bkc.public_of(raw)) not in json.dumps(box.journal())


def test_a_sheet_without_a_key_file_is_refused_before_a_key_is_made(box: Box, capsys: Any) -> None:
    """B-M5: a sheet (of some key) and no key file: refused before any key is made or written; true: nothing written."""
    stick = box.stick()
    (stick / bkc.PAPER_FILE).write_bytes(bkc.paper_sheet(bkc.new_key(), SITE, "earlier"))
    os.chmod(stick / bkc.PAPER_FILE, 0o600)
    before = _tree(box.tmp)
    code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_FOREIGN["en"].format(name=bkc.PAPER_FILE, path=box.pub_dir)
    assert _tree(box.tmp) == before and box.pending() == []


def test_a_stick_that_shows_its_files_to_others_is_refused_then_finished_after_a_remount(box: Box, capsys: Any) -> None:
    """A FAT stick mounted with a wide mask shows a new file as 0644: refused before any key exists (no record, the
    temporary file empty); the empty file is kept, and once the stick is mounted right the same command finishes."""
    stick = box.stick()
    real_open = os.open

    def wide(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if str(path).startswith(f".{bkc.KEY_FILE}.") and flags & os.O_CREAT:
            os.fchmod(fd, 0o644)
        return fd

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "open", wide)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_UNSAFE["en"].format(path=stick, name=bkc.KEY_FILE)
    assert not (stick / bkc.KEY_FILE).exists() and box.pending() == [] and box.journal() == []
    [part] = list(stick.iterdir())
    assert part.name.endswith(".part") and part.read_bytes() == b""  # empty, kept, never read again
    assert _main(box, stick, capsys)[0] == 0  # "mounted with umask=077": the same command finishes
    _invariant(box, [stick])


def test_a_key_file_shown_to_others_after_step_1_says_the_key_is_exposed(box: Box, capsys: Any) -> None:
    """B-M6: the whole key is in the file, then the stick is mounted with a wide mask: never "nothing was written"."""
    stick = box.stick()
    box.flag("fail_record")
    assert _main(box, stick, capsys)[0] == 1
    box.flag("fail_record", on=False)
    os.chmod(stick / bkc.KEY_FILE, 0o644)
    code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.KEY_EXPOSED["en"].format(path=stick, name=bkc.KEY_FILE)
    assert "nothing" not in err and not box.pub.exists()


def test_another_owner_of_a_stick_file_is_refused_before_any_key_exists(box: Box, capsys: Any) -> None:
    """The uid check (review B, mutation C): a file shown as another account's is refused, as root and as any user
    (the owner seen by fstat is changed, since only root could chown)."""
    stick, real = box.stick(), os.fstat

    def other_owner(fd: int) -> os.stat_result:
        st = real(fd)
        if not stat.S_ISREG(st.st_mode):
            return st
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid + 1, *tuple(st)[5:10]))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "fstat", other_owner)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_UNSAFE["en"].format(path=stick, name=bkc.KEY_FILE)
    assert box.pending() == [] and not (stick / bkc.KEY_FILE).exists()


def test_a_key_file_swapped_for_a_copy_before_the_read_back_is_refused(box: Box, capsys: Any) -> None:
    """The inode check (review B, mutation B): between step 1 and step 2 the key file is replaced by a copy with the
    same bytes (another inode): step 2 refuses, saying this run's files stay."""
    stick, real = box.stick(), bkc._sync_dir

    def swap(dfd: int, n: int) -> None:
        real(dfd, n)
        if os.path.samestat(os.fstat(dfd), os.stat(stick)):
            copy = stick / "copy"
            copy.write_bytes((stick / bkc.KEY_FILE).read_bytes())
            os.chmod(copy, 0o600)
            os.replace(copy, stick / bkc.KEY_FILE)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bkc, "_sync_dir", swap)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_FAULTY["en"].format(name=bkc.KEY_FILE)
    assert box.journal() == [] and not box.pub.exists()


def test_a_write_that_reads_back_wrong_on_its_own_descriptor_is_refused(box: Box, capsys: Any) -> None:
    """The same-descriptor read-back (review B, mutation D): the first read of the key file after its write gives other
    bytes: refused at once, on the writing descriptor, before the sheet is written (a later read would be right)."""
    stick, real, seen = box.stick(), os.pread, list[int]()

    def first_read_wrong(fd: int, n: int, off: int) -> bytes:
        data = real(fd, n, off)
        if not seen:
            seen.append(1)
            return data[:-2] + b"X\n"
        return data

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "pread", first_read_wrong)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_FAULTY["en"].format(name=bkc.KEY_FILE)
    assert box.journal() == [] and not box.pub.exists() and not (stick / bkc.PAPER_FILE).exists()


# ------------------------------------------------------------------------------------------------ reruns
def test_a_rerun_with_another_empty_stick_abandons_the_first_and_says_so(box: Box, capsys: Any) -> None:
    first, second = box.stick("usb-a"), box.stick("usb-b")
    box.flag("fail_record")
    code, _, err = _main(box, first, capsys)
    assert code == 1 and err.strip() == bkc.JOURNAL_UNSURE["en"] and not box.pub.exists()
    kept = _tree(first)
    box.flag("fail_record", on=False)
    code, out, _ = _main(box, second, capsys)
    assert code == 0 and "the key on that stick never became the box's key: it stays there until IT wipes" in out
    assert _tree(first) == kept  # nothing of the abandoned run is deleted
    assert _stick_key(first) != _stick_key(second) and len(box.pending()) == 2  # its record stays too
    _invariant(box, [first, second])
    assert bk.fingerprint(bkc.public_of(_stick_key(second) or b"")) == box.journal()[-1]["detail"]["fingerprint"]
    assert _main(box, first, capsys)[0] == 1  # done: backup.pub


@pytest.mark.parametrize("damage", ["torn-key", "other-site", "sheet-of-another-key", "sheet-line-swapped"])
def test_a_stick_that_cannot_finish_a_run_is_refused_unchanged(box: Box, damage: str, capsys: Any) -> None:
    """A run of this box cut short (its record is here) whose stick then cannot finish: refused, nothing written."""
    stick, raw = box.stick(), bkc.new_key()
    (box.pub_dir / bkc.pending_name(bkc.fingerprint(bkc.public_of(raw)))).write_text("record\n")
    key, sheet = bkc.key_text(raw), bkc.paper_sheet(raw, SITE, "earlier")
    name = bkc.PAPER_FILE
    if damage == "torn-key":
        key, sheet, name = key[:40], b"", bkc.KEY_FILE
    elif damage == "other-site":
        sheet = bkc.paper_sheet(raw, "another-site", "earlier")
    elif damage == "sheet-of-another-key":
        sheet = bkc.paper_sheet(bkc.new_key(), SITE, "earlier")
    else:
        lines = sheet.decode().split("\n")
        i = next(n for n, ln in enumerate(lines) if ln.startswith("1 | "))
        lines[i], lines[i + 1] = lines[i + 1], lines[i]
        sheet = "\n".join(lines).encode()
    for n, data in ((bkc.KEY_FILE, key), (bkc.PAPER_FILE, sheet)):
        if data:
            (stick / n).write_bytes(data)
            os.chmod(stick / n, 0o600)
    before = _tree(box.tmp)
    code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STICK_BROKEN["en"].format(name=name)
    assert _tree(box.tmp) == before and not box.pub.exists() and box.journal() == []
    assert _off_stick_leaks(box, [raw], [stick]) == []


# ------------------------------------------------------------------------------------------------ the journal step
def test_a_journal_that_does_not_answer_in_time_stops_step_3(box: Box, capsys: Any) -> None:
    stick, real = box.stick(), subprocess.run

    def slow(argv: list[str], **k: Any) -> Any:
        if "record" in argv:
            raise subprocess.TimeoutExpired(argv, bkc.JOURNAL_WAIT_S)
        return real(argv, **k)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(subprocess, "run", slow)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.JOURNAL_UNSURE["en"] and not box.pub.exists()


def test_a_backup_pub_that_appears_during_the_run_is_not_called_this_runs(box: Box, capsys: Any) -> None:
    """B-L4: backup.pub made by someone else between the checks and step 4: kept as it is, and said so."""
    stick, real = box.stick(), bkc.record

    def record_then_planted(detail: Any) -> int:
        seq = real(detail)
        box.pub.write_text(base64.b64encode(bkc.public_of(bkc.new_key())).decode() + "\n")
        return seq

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bkc, "record", record_then_planted)
        code, _, err = _main(box, stick, capsys)
    fp = bk.fingerprint(bk.load_public(box.pub).public_bytes_raw())
    assert code == 1 and err.strip() == bkc.PUB_TAKEN["en"].format(pub=box.pub, fp=fp)


# ------------------------------------------------------------------------------------------------ M6: folder syncs
def test_m6_a_stick_folder_sync_that_fails_with_einval_stops_before_the_journal(box: Box, capsys: Any) -> None:
    stick, real = box.stick(), os.fsync

    def fsync(fd: int) -> None:
        if os.path.samestat(os.fstat(fd), os.stat(stick)):
            raise OSError(errno.EINVAL, "Invalid argument")
        real(fd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "fsync", fsync)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STEP_FAILED["en"].format(n=1, why="EINVAL")
    assert not box.pub.exists() and box.journal() == []
    key = _stick_key(stick)
    assert _main(box, stick, capsys)[0] == 0 and _stick_key(stick) == key
    _invariant(box, [stick])


def test_m6_a_public_folder_sync_that_fails_says_backup_pub_is_not_confirmed(box: Box, capsys: Any) -> None:
    stick, real = box.stick(), os.fsync

    def fsync(fd: int) -> None:
        if os.path.samestat(os.fstat(fd), os.stat(box.pub_dir)) and box.pub.exists():
            raise OSError(errno.ENOTSUP, "Not supported")
        real(fd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "fsync", fsync)
        code, _, err = _main(box, stick, capsys)
    why = errno.errorcode[errno.ENOTSUP]
    assert code == 1 and err.strip() == bkc.PUB_UNSURE["en"].format(pub=box.pub, why=why)
    _invariant(box, [stick])
    assert _main(box, stick, capsys)[0] == 1  # backup.pub is there: done


# ------------------------------------------------------------------------------------------------ H2: whole disks
def _sysfs(tmp: Path) -> Path:
    sys_root = tmp / "sys"
    dev = sys_root / "devices"
    usb = dev / "pci0" / "usb1" / "1-1" / "block"
    disks = (("sda", ("sda2", "sda3"), "1", dev), ("sdb", ("sdb1", "sdb2"), "1", dev), ("sdc", ("sdc1",), "0", dev),
             ("sdd", ("sdd1",), "0", usb))  # fmt: skip
    for disk, parts, removable, under in disks:
        (under / disk).mkdir(parents=True)
        (under / disk / "removable").write_text(removable + "\n")
        for p in parts:
            (under / disk / p).mkdir()
            (under / disk / p / "partition").write_text("1\n")
    (dev / "dm-0" / "slaves").mkdir(parents=True)
    (dev / "dm-0" / "slaves" / "sda2").symlink_to(dev / "sda" / "sda2")
    (sys_root / "dev" / "block").mkdir(parents=True)
    (sys_root / "block").mkdir()
    nodes = {(8, 2): dev / "sda/sda2", (8, 3): dev / "sda/sda3", (8, 17): dev / "sdb/sdb1", (8, 18): dev / "sdb/sdb2",
             (8, 33): dev / "sdc/sdc1", (8, 49): usb / "sdd/sdd1", (253, 0): dev / "dm-0"}  # fmt: skip
    for (ma, mi), node in nodes.items():
        (sys_root / "dev" / "block" / f"{ma}:{mi}").symlink_to(node)
    for disk, _, _, under in disks:
        (sys_root / "block" / disk).symlink_to(under / disk)
    return sys_root


def _mountinfo(tmp: Path, *lines: str) -> Path:
    f = tmp / "mountinfo"
    f.write_text("".join(f"{20 + i} 1 {ln}\n" for i, ln in enumerate(lines)))
    return f


def test_h2_another_partition_of_the_system_disk_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H2: whole disks are compared, never filesystem ids: a USB-booted box (its system disk removable) with ``/`` on
    sda2 refuses sda3; an LVM ``/`` over sda2 refuses sda3 too; another removable disk is taken, and a USB disk shown
    as not removable is taken by its USB path; a fixed disk, a device whose disk cannot be told, or a box whose disk
    cannot be told is refused."""
    monkeypatch.setattr(bkc, "SYS", _sysfs(tmp_path))
    monkeypatch.setattr(bkc, "MOUNTINFO", _mountinfo(tmp_path, "8:2 / / rw - ext4 /dev/sda2 rw"))
    dev = os.makedev
    assert bkc.whole_disks(dev(8, 3)) == {"sda"} and bkc.whole_disks(dev(253, 0)) == {"sda"}
    assert bkc.stick_problem(dev(8, 3), [dev(8, 2)]) is True
    assert bkc.stick_problem(dev(8, 3), [dev(253, 0)]) is True
    assert bkc.stick_problem(dev(8, 17), [dev(8, 2), dev(253, 0)]) is False
    assert bkc.stick_problem(dev(8, 49), [dev(8, 2)]) is False  # on USB by its path
    assert bkc.stick_problem(dev(8, 33), [dev(8, 2)]) is True  # not removable
    assert bkc.stick_problem(dev(8, 99), [dev(8, 2)]) is True  # its disk cannot be told
    assert bkc.stick_problem(dev(8, 17), [dev(8, 99)]) is True  # the box's disk cannot be told


def test_a2_a_usb_disk_that_holds_another_mount_is_not_a_stick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A-M2: the stick's disk may hold no other mounted filesystem (a USB backup disk with its share mounted)."""
    monkeypatch.setattr(bkc, "SYS", _sysfs(tmp_path))
    monkeypatch.setattr(bkc, "MOUNTINFO", _mountinfo(tmp_path, "8:2 / / rw - ext4 /dev/sda2 rw",
                        "8:17 / /media/usb rw - vfat /dev/sdb1 rw", "8:18 / /backup rw - ext4 /dev/sdb2 rw"))  # fmt: skip
    assert bkc.stick_problem(os.makedev(8, 17), [os.makedev(8, 2)]) is True
    monkeypatch.setattr(bkc, "MOUNTINFO", _mountinfo(tmp_path, "8:2 / / rw - ext4 /dev/sda2 rw",
                        "8:17 / /media/usb rw - vfat /dev/sdb1 rw", "8:17 / /bind rw - vfat /dev/sdb1 rw"))  # fmt: skip
    assert bkc.stick_problem(os.makedev(8, 17), [os.makedev(8, 2)]) is False  # a second view of the stick itself


def test_l1_an_anonymous_device_is_told_only_by_an_absolute_dev_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-L1: a FUSE filesystem (its user names its source) and a relative source are never resolved to a disk."""
    node = tmp_path / "sdb1"
    node.write_text("")  # a name in the working folder that a relative source would find
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bkc, "SYS", _sysfs(tmp_path))
    lines = ("0:51 / /media/fuse rw - fuse.sshfs /dev/sdb1 rw", "0:52 / /media/tmp rw - tmpfs sdb1 rw")
    monkeypatch.setattr(bkc, "MOUNTINFO", _mountinfo(tmp_path, *lines))
    assert bkc.whole_disks(os.makedev(0, 51)) == set() and bkc.whole_disks(os.makedev(0, 52)) == set()


# ------------------------------------------------------------------------------------------------ the parts
def test_the_journal_code_refuses_a_file_mode_writer_checks_the_database_and_prints_the_number(
    monkeypatch: Any, capsys: Any
) -> None:
    got: list[tuple[str, dict[str, Any]]] = []
    connected: list[str] = []

    class DbAuditWriter:
        _dsn = "dsn"

        def append(self, event: str, **fields: Any) -> dict[str, Any]:
            got.append((event, fields))
            return {"journal": {"seq": 7}}

    class Con:
        def execute(self, sql: str) -> Any:
            assert sql == bkc.HAS_APPEND
            return types.SimpleNamespace(fetchone=lambda: (True,))

        def close(self) -> None:
            connected.append("closed")

    mod = types.ModuleType("tb_common.audit_writer")
    mod.DbAuditWriter = DbAuditWriter  # type: ignore[attr-defined]
    mod._psycopg = lambda: types.SimpleNamespace(connect=lambda dsn, connect_timeout: Con())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tb_common.audit_writer", mod)
    mod.open_audit = object  # type: ignore[attr-defined]
    monkeypatch.setattr(sys, "argv", ["-c", "check"])
    with pytest.raises(SystemExit) as e:
        exec(bkc.JOURNAL_CODE, {})
    assert e.value.code == 3 and got == []
    mod.open_audit = DbAuditWriter  # type: ignore[attr-defined]
    exec(bkc.JOURNAL_CODE, {})
    assert connected == ["closed"] and capsys.readouterr().out == "journal ok\n"
    monkeypatch.setattr(sys, "argv", ["-c", "record", bkc.EVENT, bkc.ACTOR, '{"fingerprint": "f"}'])
    exec(bkc.JOURNAL_CODE, {})
    assert got == [(bkc.EVENT, {"actor": bkc.ACTOR, "detail": {"fingerprint": "f"}})]
    assert capsys.readouterr().out == "journal 7\n"
    monkeypatch.delitem(sys.modules, "tb_common.audit_writer")
    from tb_common.audit_writer import DbAuditWriter as Real
    from tb_common.audit_writer import _psycopg, foreign  # what the code imports exists in the real module

    assert callable(_psycopg) and hasattr(Real, "append")
    assert foreign("tb_orchestrator", bkc.EVENT) == ""  # the orchestrator's database role may send the backup family


def test_the_key_forms_match_backup_keygen() -> None:
    raw = bkc.new_key()
    assert bkc.KEY_HEADER == bk.KEY_HEADER
    assert bkc.fingerprint(bkc.public_of(raw)) == bk.fingerprint(bkc.public_of(raw))
    assert bkc.read_key(bkc.key_text(raw)) == raw and bkc.read_sheet(bkc.paper_sheet(raw, "", "t")) == (raw, "-")
    assert bkc.read_key(bkc.key_text(raw).replace(b"fingerprint ", b"fingerprint 0")) is None


def test_every_text_is_in_three_languages_with_the_same_fields() -> None:
    texts = bkc.all_texts()
    names = {n for n, _, _ in texts}
    assert len(names) >= 25
    en = {n: t for n, lg, t in texts if lg == "en"}
    for name, lg, t in texts:
        assert t.strip(), (name, lg)
        if lg != "en":
            assert t != en[name] and not t.isascii(), (name, lg)
    for name in names:
        fields = {lg: sorted(re.findall(r"\{(\w+)\}", t)) for n, lg, t in texts if n == name}
        assert len({tuple(v) for v in fields.values()}) == 1, (name, fields)
    rel = "tools/backup_key_ceremony.py"
    rows = core_words._module_texts(rel, ast.parse((ROOT / rel).read_text(encoding="utf-8")))
    assert [str(r) for r in core_words.refused(rows)] == []


def test_the_command_line_refuses_before_it_writes(tmp_path: Path) -> None:
    """The command's main with the arguments a person types (run without PYTHONUNBUFFERED; the host probe's swap list
    injected empty): not root, refused first; as root, a TB_BACKUP_PUBKEY that names another file is refused before
    anything is opened; in Japanese."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update(PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")),
               TB_BACKUP_PUBKEY=str(tmp_path / "other.pub"))  # fmt: skip
    no_swap = tmp_path / "no-swaps"  # the host probe's swap list, injected (H-5 is shown on its own)
    no_swap.write_text(SWAPS_HEAD)
    code = ("import sys; from pathlib import Path; from tools import backup_key_ceremony as b\n"
            "b.SWAPS = Path(sys.argv.pop(1)); sys.argv[0] = 'tools/backup_key_ceremony.py'\n"
            "sys.exit(b.main(sys.argv[1:]))\n")  # fmt: skip
    r = subprocess.run([sys.executable, "-c", code, str(no_swap), "--stick", str(tmp_path / "usb"), "--operator", OP,
                        "--witness", WIT, "--lang", "ja"], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=120, check=False)  # fmt: skip
    want = (
        bkc.NOT_ROOT["ja"]
        if os.geteuid()
        else bkc.PUB_ELSEWHERE["ja"].format(path=tmp_path / "other.pub", pub=bkc.PUB_DIR / "backup.pub")
    )
    assert r.returncode == 1 and r.stdout == "" and r.stderr.strip() == want
    assert list(tmp_path.iterdir()) == [no_swap]


# ------------------------------------------------------------------------------------------------ review of 36c97bd1
def test_h_1_the_journal_is_asked_on_the_local_socket_whatever_docker_context_is_set(
    box: Box, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """H-1: a DOCKER_HOST, DOCKER_CONTEXT, DOCKER_CONFIG or TLS setting naming another box reaches no call: the call
    gets the local socket, an empty config folder and no other Docker or Compose setting; the command line names the
    local socket too."""
    hostile = {"DOCKER_HOST": "tcp://site-b.example:2376", "DOCKER_CONTEXT": "site-b", "DOCKER_TLS_VERIFY": "1",
               "DOCKER_CONFIG": str(box.tmp / "site-b-config"), "COMPOSE_FILE": str(box.tmp / "site-b.yml")}  # fmt: skip
    for k, v in hostile.items():
        monkeypatch.setenv(k, v)
    assert _main(box, box.stick(), capsys)[0] == 0
    for call in (json.loads(x) for x in (box.state / "calls.jsonl").read_text().splitlines()):
        env = call["env"]
        assert env["DOCKER_HOST"] == "unix:///var/run/docker.sock"
        assert {"DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "COMPOSE_FILE"}.isdisjoint(env)
        assert Path(env["DOCKER_CONFIG"]).name.startswith("tb-ceremony-docker-")
    call = bkc.local_compose("trialbox")
    assert call[:4] == ["docker", "-H", "unix:///var/run/docker.sock", "compose"] and call[-2:] == ["-p", "trialbox"]


def test_h_2_a_stick_that_is_not_one_removable_block_device_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-2: a filesystem on an anonymous device (btrfs, which may mirror onto an internal disk, even when mountinfo
    names the USB member), a mapped device, and a partition that is a member of a mapped device (md, LVM) are refused;
    a plain partition of one removable disk is taken."""
    sys_root = _sysfs(tmp_path)
    monkeypatch.setattr(bkc, "SYS", sys_root)
    monkeypatch.setattr(bkc, "MOUNTINFO", _mountinfo(tmp_path, "8:2 / / rw - ext4 /dev/sda2 rw",
                        "0:61 / /media/usb rw - btrfs /dev/sdb1 rw"))  # fmt: skip
    dev = os.makedev
    assert bkc.stick_problem(dev(0, 61), [dev(8, 2)]) is True
    assert bkc.stick_problem(dev(253, 0), [dev(8, 3)]) is True  # a mapped device
    assert bkc.stick_problem(dev(8, 17), [dev(8, 2)]) is False
    holder = sys_root / "devices" / "sdb" / "sdb1" / "holders"
    holder.mkdir()
    (holder / "md0").symlink_to(tmp_path)
    assert bkc.stick_problem(dev(8, 17), [dev(8, 2)]) is True  # a member of an md array


def test_h_3_a_rerun_syncs_the_files_a_run_cut_short_left(box: Box, capsys: Any) -> None:
    """H-3: a run stopped after step 2; the rerun calls fsync on the key file and the sheet it takes up again."""
    stick, real = box.stick(), os.fsync
    box.flag("fail_record")
    assert _main(box, stick, capsys)[0] == 1
    box.flag("fail_record", on=False)
    inodes = {(stick / n).stat().st_ino: n for n in (bkc.KEY_FILE, bkc.PAPER_FILE)}
    synced: set[str] = set()

    def fsync(fd: int) -> None:
        st = os.fstat(fd)
        if stat.S_ISREG(st.st_mode) and st.st_ino in inodes:
            synced.add(inodes[st.st_ino])
        real(fd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "fsync", fsync)
        assert _main(box, stick, capsys)[0] == 0
    assert synced == {bkc.KEY_FILE, bkc.PAPER_FILE}


def test_h_4_a_write_cut_short_never_leaves_part_of_a_file_at_its_final_name(box: Box, capsys: Any) -> None:
    """H-4: the key file's write fails after 40 bytes: the final name is not there, only the temporary file (kept);
    the same command with the same stick then finishes."""
    stick, real = box.stick(), os.write

    def short(fd: int, data: Any) -> int:
        if os.fstat(fd).st_size == 0 and bytes(data).startswith(b"-----BEGIN"):
            real(fd, bytes(data)[:40])
            raise OSError(errno.EIO, "Input/output error")
        return real(fd, data)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "write", short)
        code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.STEP_FAILED["en"].format(n=1, why="EIO")
    assert not (stick / bkc.KEY_FILE).exists() and [p.name.endswith(".part") for p in stick.iterdir()] == [True]
    assert _main(box, stick, capsys)[0] == 0
    _invariant(box, [stick])


def test_h_5_no_key_is_made_while_swap_is_on_and_memory_cannot_be_locked(box: Box) -> None:
    """H-5, the real refusal: the command in a process of its own, as a user that may not lock memory (uid 65534 when
    the tests run as root, else the user running them) with RLIMIT_MEMLOCK 0, so the real mlockall is denied, and a
    swap list showing a swap area: refused before any key, in three languages, nothing made. Then, with the probe's
    swap list injected empty, the run goes on and the spy sees the memory locked or no swap in the list."""
    fd, name = tempfile.mkstemp(prefix="k10k13-swaps-", dir=os.environ.get("TB_TEST_ROOT") or None)
    swaps = Path(name)
    try:
        os.write(fd, (SWAPS_HEAD + "/swapfile\t\t\t\tfile\t\t1048572\t\t0\t\t-2\n").encode())
        os.close(fd)
        os.chmod(swaps, 0o644)  # readable by uid 65534
        code = ("import sys; from pathlib import Path; from tools import backup_key_ceremony as b\n"
                "b.SWAPS = Path(sys.argv[1])\nreal = b.new_key\n"
                "def watched():\n    print('KEY MADE', flush=True)\n    return real()\n"
                "b.new_key = watched\nsys.exit(b.main(sys.argv[2:]))\n")  # fmt: skip

        def unprivileged() -> None:
            import resource

            resource.setrlimit(resource.RLIMIT_MEMLOCK, (0, 0))
            if os.geteuid() == 0:  # root may always lock memory: run as nobody
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)

        stick = box.stick()
        env = {**box.env(), "HOME": "/"}
        argv = [sys.executable, "-c", code, str(swaps), "--stick", str(stick), "--operator", OP, "--witness", WIT]
        r = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False,
                           preexec_fn=unprivileged)  # fmt: skip
    finally:
        swaps.unlink()
    assert r.returncode == 1 and r.stderr.strip() == "\n".join(bkc.HARDEN_FAILED[lg] for lg in bkc.LANGS), r.stderr
    assert "KEY MADE" not in r.stdout and r.stdout == ""
    assert list(stick.iterdir()) == [] and box.pending() == [] and box.journal() == []
    spy = box.tmp / "spy.json"
    assert box.drive(stick, spy=spy).returncode == 0
    seen = json.loads(spy.read_text())
    assert seen["locked_kb"] > 0 or not seen["swap_on"]


def test_m_7_a_key_file_restore_would_reject_is_never_taken(box: Box) -> None:
    """M-7: the fingerprint line without its word: refused by the ceremony as by restore --key."""
    raw = bkc.new_key()
    bad = bkc.key_text(raw).replace(b"fingerprint ", b"")
    assert bkc.read_key(bad) is None
    (box.tmp / "bad.key").write_bytes(bad)
    with pytest.raises(bk.BackupError):
        bk.load_private(box.tmp / "bad.key")


# ------------------------------------------------------------------------------------------------ second review of 6c33ba4f
@pytest.mark.parametrize("where", ["inside", "equal", "holds", "same-filesystem", "elsewhere"])
def test_h2_second_review_a_stick_folder_beside_the_backups_is_refused(
    box: Box, where: str, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """The stick folder may not be a TB_BACKUP_TARGETS folder, inside one, hold one, or share its filesystem (by real
    path and by device): the key never sits beside the backups it opens. A target elsewhere is no matter."""
    stick = box.tmp / "backups" / "escrow" if where == "inside" else box.stick()
    stick.mkdir(parents=True, mode=0o700, exist_ok=True)
    target = {"inside": box.tmp / "backups", "equal": stick, "holds": stick / "nightly",
              "same-filesystem": box.tmp / "share", "elsewhere": Path("/nonexistent-backup-target")}[where]  # fmt: skip
    if where in ("holds", "same-filesystem"):
        target.mkdir()
    monkeypatch.setenv("TB_BACKUP_TARGETS", f"/nonexistent-first, {target}")
    before = _tree(box.tmp)
    code, _, err = _main(box, stick, capsys)
    if where == "elsewhere":
        assert code == 0
        return
    assert code == 1 and err.strip() == bkc.STICK_IS_BACKUP["en"].format(path=stick, target=target)
    assert _tree(box.tmp) == before and box.journal() == [] and box.pending() == []


def test_h3_second_review_the_compose_project_is_this_checkouts_own(
    box: Box, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """The project is the one whose running orchestrator was started from this checkout's deploy folder, never a name
    from the environment; none, or two projects claiming it: refused before anything is written."""
    deploy = box.deploy.resolve()
    listing = f"site-a\t{deploy}\ntrialbox\t/srv/other/deploy\n"
    assert bkc.project_of(listing, deploy) == "site-a"
    assert bkc.project_of("trialbox\t/srv/other/deploy\n", deploy) is None
    assert bkc.project_of(f"site-a\t{deploy}\nsite-b\t{deploy}\n", deploy) is None
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "trialbox")
    monkeypatch.setattr(bkc, "COMPOSE", None)
    monkeypatch.setattr(bkc, "_local_socket", lambda: True)
    monkeypatch.setattr(bkc, "_project", lambda: None)
    stick = box.stick()
    before = _tree(box.tmp)
    code, _, err = _main(box, stick, capsys)
    assert code == 1 and err.strip() == bkc.NO_PROJECT["en"].format(path=box.deploy)
    assert _tree(box.tmp) == before and box.journal() == []
