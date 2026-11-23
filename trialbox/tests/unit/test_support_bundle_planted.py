"""H-71 (D-1354), the invariant: a real bundle built from a box in which every source the builder reads holds planted
patient tokens and secrets of every kind holds none of them, in any form, in any member's bytes or name.

Sources planted (each is a path by which text enters a bundle): ``deploy/.env``; the update history (``history.jsonl``
and the ops snapshot's update rows); ``installed.json`` and ``release.json``; the secrets folder's file NAMES (the ops
snapshot lists them); the audit verification's messages; every command's output; the collected service logs; an
``--add`` file and its name and folder; the builder's own error messages (a snapshot and a verification that fail).
The manifest carries the sources and the left-out lines. Every value is synthetic and made at run time."""

from __future__ import annotations

import ast
import base64
import gzip
import json
import os
import random
import re
import tarfile
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools import bundle_scrub as bs
from tools import support_bundle as sb

ROOT = Path(__file__).resolve().parents[2]


class Seeded:
    """The random values of the bundle's tests, the same on every run of a test whatever the order, the worker or
    ``--dist`` (H-76: a value drawn from ``secrets`` made the invariant test fail about once in 60 runs). The seed
    is the test's node id, read from ``PYTEST_CURRENT_TEST``; a test draws the same values in the same order."""

    def __init__(self) -> None:
        self.key: str | None = None
        self.rng = random.Random(0)

    def _r(self) -> random.Random:
        key = os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" (", 1)[0]
        if key != self.key:
            self.key, self.rng = key, random.Random(f"H-76|{key}")
        return self.rng

    def token_bytes(self, n: int = 32) -> bytes:
        return self._r().getrandbits(8 * n).to_bytes(n, "big")

    def token_hex(self, n: int = 32) -> str:
        return self.token_bytes(n).hex()

    def token_urlsafe(self, n: int = 32) -> str:
        return base64.urlsafe_b64encode(self.token_bytes(n)).rstrip(b"=").decode()

    def randbelow(self, n: int) -> int:
        return self._r().randrange(n)

    def choice(self, seq: str) -> str:
        return self._r().choice(seq)


SEEDED = Seeded()
secrets = SEEDED  # the module's draws, by the name the code read before
NOW = datetime(2026, 11, 22, 4, 31, tzinfo=UTC)
DAY = "2026-11-21"


@dataclass
class Planted:
    pid: str
    pid2: str
    screening: list[str]
    settings: dict[str, str]  # every secret setting the declarations and the builder know, and TB_SMTP_LOGIN
    loose: dict[str, str]  # secrets no setting holds: they leave only by their form

    def values(self) -> dict[str, str]:
        out = {
            "pid": self.pid,
            "pid upper": self.pid2.upper(),
            "pid short": self.pid[:8] + "…",
            "pid bare short": self.pid2[:8],
        }
        out |= {f"screening {i}": s for i, s in enumerate(self.screening)}
        return (
            out
            | {f"setting {k}": v for k, v in self.settings.items()}
            | {f"loose {k}": v for k, v in self.loose.items()}
        )


LOOSE = ("query password", "query token", "form pwd", "userinfo user", "userinfo pass", "bearer", "cookie",
         "pem body", "json secret", "escaped json", "multi line a", "multi line b", "yaml block", "encoded next",
         "redcap family", "header key",
         # review round 1 (H1, M1)
         "double encoded", "cli password", "cli token", "curl user", "yaml next", "userinfo slash", "userinfo at",
         "xml", "spaced key", "json next line", "escaped key", "flag dash")  # fmt: skip


def _pid_with_a_letter() -> str:
    """A pseudonym whose first 8 digits hold a hex letter (the bare short form is masked only then: the page)."""
    while True:
        pid = secrets.token_hex(bs.pid_hex_len() // 2)
        if re.search("[a-f]", pid[:8]):
            return pid


def _plant() -> Planted:
    hexed = secrets.token_hex
    names = sorted({"TB_SMTP_LOGIN", *bs.declarations().secret, *sb.SECRET_SETTINGS} - {"TB_REDCAP_TOKEN_"})
    return Planted(
        pid=_pid_with_a_letter(),
        pid2=_pid_with_a_letter(),
        screening=[
            f"RQ{hexed(2).upper()}-{1000 + secrets.randbelow(8000)}",
            f"scr_{secrets.randbelow(9000) + 1000}",
            f"TBQ{secrets.randbelow(90000) + 10000}",
            # review round 1 (M2): the prefixes the console takes (any 16 characters)
            f"Scr{secrets.randbelow(9000) + 1000}",
            f"SCR.{secrets.randbelow(9000) + 1000}",
            f"SCR {secrets.randbelow(9000) + 1000}",
            f"SCR#{secrets.randbelow(9000) + 1000}",
            f"SCR/{secrets.randbelow(9000) + 1000}",
            f"\u7be9\u9078-{secrets.randbelow(9000) + 1000}",
        ],
        settings={n: f"s{hexed(9)}" for n in names},
        loose={k: f"l{hexed(9)}" for k in LOOSE},
    )


def corpus(p: Planted) -> str:
    """Every kind in the forms a log, a command or a file could hold it."""
    lo, s = p.loose, p.settings
    pem = "-----BEGIN " + "PRIVATE KEY-----\n" + lo["pem body"] + "\n-----END " + "PRIVATE KEY-----"
    lines = [
        f"job for patient {p.pid} done; also {p.pid2.upper()} and the short form ({p.pid[:8]}…)",
        f'{{"pid": "{p.pid}", "no": "{p.screening[0]}", "password": "{lo["json secret"]}"}}',
        f"screening numbers {p.screening[0]}, {p.screening[1]} and {p.screening[2]} were assigned",
        f"GET /console/p/{p.pid}?password={lo['query password']}&token={lo['query token']}&lang=en HTTP/1.1",
        f"POST form: user=amy&pwd={lo['form pwd']}",
        f"next=%2Flogin%3Faccess_token%3D{lo['encoded next']}%26x%3D1",
        f"connect smtp://{lo['userinfo user']}:{lo['userinfo pass']}@relay.test:587",
        f"Authorization: Bearer {lo['bearer']}",
        f"Cookie: sessionid={lo['cookie']}; theme=dark",
        f"x-api-key: {lo['header key']}",
        json.dumps({"msg": json.dumps({"secret": lo["escaped json"]})}),
        # review round 1, H1: a token next to an encoded character, in every encoding
        f"GET /demo/ack?back=%2Fstudies%2FRA01%2Fpatients%2F{p.pid} 303",
        f"GET /x?q=%7B%22pid%22%3A%22{p.pid}%22%7D and %7b%22no%22%3a%22{p.screening[0]}%22%7d",
        f"next=%252Fp%252F{p.pid2}%253Fpassword%253D{lo['double encoded']}",
        "\\u002F" + p.pid + "\\u0022 \\x2F" + p.pid2 + " &#x2F;" + p.pid + "&#x2F; &#47;" + p.pid2 + "&quot;",
        f"/q%2F{p.screening[1]}%2F and =3D{p.pid}=3D",
        # review round 1, M1: secret forms the first round missed
        f"pg_dump --password={lo['cli password']} --token {lo['cli token']} -d tb",
        f"args: --db-password={lo['flag dash']}",
        f"curl -u admin:{lo['curl user']} https://x.test",
        f"smtp:\n  password:\n    {lo['yaml next']}\n  user: amy",
        f"postgres://u:ab/{lo['userinfo slash']}@db/x and redis://:p@{lo['userinfo at']}@host",
        f"<password>{lo['xml']}</password>",
        f"smtp password = {lo['spaced key']}",
        f'{{"password":\n "{lo["json next line"]}"}}',
        '{"\\u0070assword": "' + lo["escaped key"] + '"}',
        # review round 1, L1 and M2: the bare short form and the other screening prefixes
        f"short {p.pid[:8]} and #x-{p.pid2[:8]}",
        " / ".join(p.screening[3:]),
        f"TB_REDCAP_TOKEN_P42={lo['redcap family']}",
        pem,
        f'TB_SMTP_PASSWORD_HINT="{lo["multi line a"]}\n{lo["multi line b"]}"',
        f"password: |\n  {lo['yaml block']}",
        *(f"{name}={value}" for name, value in s.items()),
        *(f'{{"{name}": "{value}"}}' for name, value in s.items()),
    ]
    return "\n".join(lines) + "\n"


def _gz(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(data)


@pytest.fixture
def planted_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Planted, Path]:
    return make_box(tmp_path, monkeypatch)


def make_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Planted, Path]:
    """The planted box (also used by test_support_bundle_review1.py)."""
    p = _plant()
    for k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR", *p.settings):
        monkeypatch.delenv(k, raising=False)
    deploy, logs, audit = tmp_path / "deploy", tmp_path / "logs", tmp_path / "audit"
    (deploy / "secrets" / "services").mkdir(parents=True)
    (deploy / "secrets" / "services" / f"{p.pid}.token").write_text("x" * 12 + "\n", encoding="utf-8")  # a NAME
    audit.mkdir()
    env = ["TB_TZ=Asia/Taipei", "TB_ENV=TEST", f"TB_LOG_DIR={logs}", f"TB_AUDIT_HOST_DIR={audit}",
           f"TB_SITE_NOTE={p.pid} {p.screening[0]}"]  # fmt: skip
    env += [f"{n}={v}" for n, v in p.settings.items()]
    env += [f"# {line}" for line in corpus(p).splitlines()]
    (deploy / ".env").write_text("\n".join(env) + "\n", encoding="utf-8")
    (deploy / "settings.yaml").write_text('mrn_regex: "^\\\\d{8}$"\n', encoding="utf-8")
    upd = deploy / "updates"
    upd.mkdir()
    hist = [{"at": "2026-11-20T09:41:00Z", "bundle": "1.4.2", "box": "compose", "step": "restore", "ok": False,
             "detail": f"CalledProcessError: {line}"} for line in corpus(p).splitlines()]  # fmt: skip
    (upd / "history.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hist) + corpus(p), encoding="utf-8")
    (upd / "installed.json").write_text(json.dumps({"version": "1.4.2", "note": corpus(p)}), encoding="utf-8")
    (deploy / "release.json").write_text(json.dumps({"by": p.pid, "notes": corpus(p).splitlines()}), encoding="utf-8")
    _gz(logs / "services" / DAY / "orchestrator.log.gz", corpus(p).encode())
    _gz(logs / "services" / DAY / "console.log.gz", ("console | " + corpus(p)).encode())
    _gz(logs / "services" / DAY / "lake.log.gz", corpus(p).encode("utf-16"))  # not UTF-8: left out, listed
    folder = tmp_path / f"case-{p.pid}"
    folder.mkdir()
    add = folder / f"report-{p.screening[0]}-{p.pid2}.txt"
    add.write_text(corpus(p), encoding="utf-8")
    return deploy, p, add


def _runner(p: Planted) -> sb.Runner:
    text = corpus(p)

    def run(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        if argv[0] == "docker" and len(argv) > 1 and argv[1] == "inspect":
            return 0, f"/trialbox-console-1 restarts=0 status=running\n{text}"
        if argv[0] == "nvidia-smi":
            return 0, "binary\x00output"  # not text: left out, listed
        return 0, text

    return run


def _forms(value: str) -> set[str]:
    raw = value.encode()
    return {value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value), json.dumps(value)[1:-1],
            json.dumps(value, ensure_ascii=False)[1:-1], base64.b64encode(raw).decode().rstrip("="),
            base64.urlsafe_b64encode(raw).decode().rstrip("="), value.lower(), value.upper()}  # fmt: skip


def _archive(out: Path) -> list[tuple[str, bytes]]:
    rows: list[tuple[str, bytes]] = []
    with tarfile.open(out, "r:gz") as tar:
        for m in tar.getmembers():
            fh = tar.extractfile(m)
            rows.append((m.name, fh.read() if fh is not None else b""))
    return rows


def _assert_clean(out: Path, p: Planted) -> list[tuple[str, bytes]]:
    members = _archive(out)
    blob = b"\n".join(n.encode() + b"\n" + data for n, data in members)
    for what, value in p.values().items():
        for form in _forms(value):
            assert form.encode() not in blob, f"{what} left in the bundle (a form of {len(value)} characters)"
    return members


class _Verified:
    ok, files, lines = False, 1, 3

    def __init__(self, p: Planted) -> None:
        self.errors = [f"line 2: chain broken at event of {p.pid}", corpus(p)]
        self.notes = [f"screening {p.screening[1]}"]


def test_no_planted_value_leaves_in_any_member_or_name(
    planted_box: tuple[Path, Planted, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy, p, add = planted_box
    from tb_common import audit

    monkeypatch.setattr(audit, "verify", lambda _d: _Verified(p))
    said: list[str] = []
    out = sb.build(deploy, tmp_path / "usb", add=[add], runner=_runner(p), now=NOW, say=said.append)
    members = _assert_clean(out, p)
    names = {n.removeprefix("support/") for n, _ in members}
    assert {"env.redacted", "history.jsonl", "release.json", "ops-snapshot.json", "audit-verify.json",
            f"logs/{DAY}/orchestrator.log", f"logs/{DAY}/console.log", "cmd/doctor.json"} <= names  # fmt: skip
    assert any(n.startswith("added/[screening-no") for n in names), names  # "report-" is in the prefix
    manifest = json.loads(dict(members)["support/MANIFEST.json"])
    left = {r["what"]: r["why"] for r in manifest["left_out"]}
    assert "not UTF-8" in left[f"logs/{DAY}/lake.log"] and "not text" in left["cmd/nvidia-smi.txt"]
    for row in json.loads(dict(members)["support/history.jsonl"].splitlines()[0]).values():
        assert not isinstance(row, str) or len(row) < 40  # the detail is its type and length
    assert not any(v in " ".join(said) for v in p.values().values())


def test_the_builders_own_errors_leave_as_type_and_length(
    planted_box: tuple[Path, Planted, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy, p, add = planted_box
    from tb_common import audit

    from tools.trialbox import ops as tb_ops

    def fail(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError(corpus(p))

    monkeypatch.setattr(audit, "verify", fail)
    monkeypatch.setattr(tb_ops, "snapshot", fail)
    out = sb.build(deploy, tmp_path / "usb", add=[add], runner=_runner(p), now=NOW, say=lambda _: None)
    members = dict(_assert_clean(out, p))
    snap = json.loads(members["support/ops-snapshot.json"])
    assert snap["error"] == {"type": "RuntimeError", "length": len(f"RuntimeError: {corpus(p)}")}
    assert json.loads(members["support/audit-verify.json"])["error"]["type"] == "RuntimeError"


def test_a_member_put_in_past_add_is_scrubbed_before_it_is_written(
    planted_box: tuple[Path, Planted, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pass that writes a member straight into the bundle (as the line removal and the secret passes do) still
    goes through the scrub: the bundle is sealed after them."""
    deploy, p, _add = planted_box
    real = sb.clean_lines

    def sneaky(b: sb.Bundle, say: Any) -> None:
        real(b, say)
        b.members[f"sneak-{p.pid}.txt"] = corpus(p)

    monkeypatch.setattr(sb, "clean_lines", sneaky)
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    members = _assert_clean(out, p)
    assert any("sneak-[pseudonym" in n for n, _ in members)


def test_the_archive_writer_refuses_a_member_the_scrub_would_change(tmp_path: Path) -> None:
    p = _plant()
    s = bs.Scrubber.for_bundle()
    target = tmp_path / "x.tar.gz"
    with pytest.raises(sb.BundleRefused, match="did not go through the scrub"):
        sb._write_tar(target, {"a.txt": s.text("fine\n"), "b.log": corpus(p)}, NOW, s)
    assert not target.exists()
    with pytest.raises(sb.BundleRefused):
        sb._write_tar(target, {f"n-{p.pid}.txt": "fine\n"}, NOW, s)  # a raw NAME is refused too
    sb._write_tar(target, {"a.txt": s.text("fine\n")}, NOW, s)
    assert target.exists()


# ------------------------------------------------------------------------------------------------ every writer
#: calls that put bytes into an archive or open one for writing
ARCHIVE_WRITES = {"addfile", "TarInfo", "writestr", "ZipFile", "ZipInfo"}


def _writers(path: Path) -> dict[str, set[str]]:
    """Each function of ``path`` and the archive-writing calls in it (by AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            mode = next((a.value for a in [*node.args[1:2], *(k.value for k in node.keywords if k.arg == "mode")]
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)), "")  # fmt: skip
            if name in ARCHIVE_WRITES or (name == "open" and isinstance(f, ast.Attribute) and isinstance(
                    f.value, ast.Name) and f.value.id in ("tarfile", "gzip", "zipfile") and mode[:1] in "wax"):  # fmt: skip
                found.setdefault(fn.name, set()).add(name)
    return found


def test_every_function_that_writes_into_the_archive_goes_through_the_scrub() -> None:
    """The one writer is ``_write_tar``, and it checks every member with the scrub before it writes. A new writer
    anywhere in the builder or the scrub, one that bypasses the check, fails here."""
    found: dict[str, set[str]] = {}
    for path in (ROOT / "tools/support_bundle.py", ROOT / "tools/bundle_scrub.py"):
        for fn, calls in _writers(path).items():
            found[f"{path.name}:{fn}"] = calls
    assert set(found) == {"support_bundle.py:_write_tar"}, found
    tree = ast.parse((ROOT / "tools/support_bundle.py").read_text(encoding="utf-8"))
    writer = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_write_tar")
    lines = {
        n.func.attr: n.lineno
        for n in reversed(list(ast.walk(writer)))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert lines["is_clean"] < lines["addfile"]  # checked before anything is written
    # and the builder hands the archive writer the bundle's own scrubber
    builds = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_write_tar"]  # fmt: skip
    assert builds and all(ast.unparse(c.args[3]) == "b.scrubber" for c in builds)


def test_the_writer_finder_finds_a_writer() -> None:
    """The finder is not blind: a function that opens a tar for writing is found."""
    src = "import tarfile\ndef leak(p):\n    with tarfile.open(p, 'w:gz') as t:\n        t.addfile(None)\n"
    tmp = Path(__file__).parent / "__pycache__"
    tmp.mkdir(exist_ok=True)
    f = tmp / "h71_writer_probe.py"
    f.write_text(src, encoding="utf-8")
    try:
        assert _writers(f) == {"leak": {"open", "addfile"}}
    finally:
        f.unlink()
