"""H-71, review round 1 (#1314, head f944d626): a test per finding, red on that head and green after the fix.

H1 a token next to an encoded character; H2 a member cut before the scrub; M1 secret forms; M2 screening prefixes;
M3 the ops snapshot's update rows; M4 the writer guard; speed (every rule on a long line); L1 the bare short
pseudonym; L2 names that collide after the scrub; L3 a trailing invalid byte. Each finding's CLASS is tested, not
only the instance the review showed. Synthetic values only, made at run time."""

from __future__ import annotations

import ast
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_support_bundle_planted import (
    DAY,
    NOW,
    _archive,
    _assert_clean,
    _gz,
    _runner,
    make_box,
    secrets,  # one seed per test id (H-76)
)
from tools import bundle_scrub as bs
from tools import support_bundle as sb

ROOT = Path(__file__).resolve().parents[2]


def _pid() -> str:
    while True:
        pid = secrets.token_hex(bs.pid_hex_len() // 2)
        if any(c in "abcdef" for c in pid[:8]):
            return pid


def _v() -> str:
    return "q" + secrets.token_hex(9)


def _blob(out: Path) -> bytes:
    return b"\n".join(n.encode() + b"\n" + data for n, data in _archive(out))


# ------------------------------------------------------------------------------------------------ H1
ENCODED = [
    "%2F{t}", "%2f{t}", "%22{t}%22", "%3D{t}", "%3A{t}%2C", "%252F{t}", "%25252F{t}", "\\u002F{t}", "\\\\u002F{t}",
    "\\x2F{t}", "\\U0000002F{t}", "&#x2F;{t}", "&#47;{t}", "&quot;{t}&quot;", "=3D{t}", "%7B%22pid%22%3A%22{t}%22%7D",
]  # fmt: skip


@pytest.mark.parametrize("form", ENCODED)
def test_h1_a_pseudonym_next_to_an_encoded_character_is_masked(form: str) -> None:
    pid = _pid()
    out = bs.Scrubber.for_bundle().text(form.format(t=pid) + " tail")
    assert pid not in out.lower() and "tail" in out


@pytest.mark.parametrize("form", ENCODED)
def test_h1_a_screening_number_next_to_an_encoded_character_is_masked(form: str) -> None:
    no = f"RA{secrets.randbelow(90) + 10}-{secrets.randbelow(9000) + 1000}"
    out = bs.scrub_text(form.format(t=no) + " tail")
    assert no not in out


@pytest.mark.parametrize(
    "form",
    ["%3Fpassword%3D{v}%26x%3D1", "%253Fpassword%253D{v}%2526x", "%7B%22password%22%3A%22{v}%22%7D",
     "\\u0022password\\u0022: \\u0022{v}\\u0022", "&quot;password&quot;: &quot;{v}&quot;", "%22token%22%3A%22{v}%22"],
)  # fmt: skip
def test_h1_a_secret_value_in_an_encoded_text_is_replaced(form: str) -> None:
    v = _v()
    assert v not in bs.scrub_text("next=" + form.format(v=v))


def test_h1_the_reviewers_lines_leave_no_pseudonym_in_a_built_bundle(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    deploy, p, _add = make_box(tmp_path, mp)
    pid = _pid()
    lines = (f"console | GET /demo/ack?back=%2Fstudies%2FRA01%2Fpatients%2F{pid} 303\n"
             f"console | GET /x?q=%7B%22pid%22%3A%22{pid}%22%7D 200\n")  # fmt: skip
    _gz(deploy.parent / "logs" / "services" / DAY / "gateway.log.gz", lines.encode())
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    assert pid.encode() not in _blob(out).lower()
    assert f"support/logs/{DAY}/gateway.log" in dict(_archive(out))


# ------------------------------------------------------------------------------------------------ H2
@pytest.fixture
def mp(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    return monkeypatch


def test_h2_a_pem_block_cut_by_the_size_limit_leaves_no_body(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    deploy, p, _add = make_box(tmp_path, mp)
    mp.setattr(sb, "MAX_MEMBER", 4096)
    body = [secrets.token_hex(32) for _ in range(100)]  # 6.5 KB of body: the 4 KB cut lands inside it
    pem = "-----BEGIN " + "PRIVATE KEY-----\n" + "\n".join(body) + "\n-----END " + "PRIVATE KEY-----\n"
    text = "orchestrator | start\n" * 300 + pem + "orchestrator | after\n" * 20
    _gz(deploy.parent / "logs" / "services" / DAY / "orchestrator.log.gz", text.encode())
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    blob = _blob(out)
    assert not [b for b in body if b.encode() in blob]
    assert f"support/logs/{DAY}/orchestrator.log" in dict(_archive(out))


def test_h2_a_yaml_block_secret_cut_by_the_size_limit_leaves_no_line(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """The cut must come after the scrub, not be repaired after it: a YAML block value cut in its middle has no key
    line left, and no rule can tell its lines from any other (a mutant that cut first passed every other test)."""
    deploy, p, _add = make_box(tmp_path, mp)
    mp.setattr(sb, "MAX_MEMBER", 4096)
    parts = [secrets.token_hex(20) for _ in range(150)]  # 6.3 KB of value: the 4 KB cut lands inside it
    text = "adapter | start\n" * 50 + "private_key: |\n" + "".join(f"  {x}\n" for x in parts) + "adapter | end\n" * 10
    _gz(deploy.parent / "logs" / "services" / DAY / "adapter.log.gz", text.encode())
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    blob = _blob(out)
    assert not [x for x in parts if x.encode() in blob]
    assert f"support/logs/{DAY}/adapter.log" in dict(_archive(out))


def test_h2_every_cut_is_after_the_scrub(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """The class: a slice of text taken before the scrub can halve a token, which the scrub then cannot know. The
    container list's error text is cut to 200 characters: the pseudonym at the cut must not leave in part."""
    deploy, p, _add = make_box(tmp_path, mp)
    pid = _pid()
    base = _runner(p)

    def run(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        if " ".join(argv).endswith("ps --all -q"):
            return 1, "x " * 92 + pid  # the cut at 200 falls inside the pseudonym
        return base(argv, timeout)

    out = sb.build(deploy, tmp_path / "usb", runner=run, now=NOW, say=lambda _: None)
    assert pid[:12].encode() not in _blob(out)


@pytest.mark.parametrize("sep", ["\n", "\\n", "\n# ", "\n2026-11-21T01:00:00Z orchestrator | "])
def test_h2_a_pem_body_with_no_begin_line_is_masked(sep: str) -> None:
    """A cut, a log rotation or a day's boundary can start a member inside a PEM block: base64 lines then END."""
    body = [secrets.token_hex(32) for _ in range(5)]
    text = "head line\n" + sep.lstrip("\n") + sep.join(body) + sep + "-----END " + "RSA PRIVATE KEY-----\nnext\n"
    out = bs.scrub_text(text)
    assert not [b for b in body if b in out] and "next" in out and "head line" in out


# ------------------------------------------------------------------------------------------------ M1
M1_FORMS = [
    "pg_dump --password={v} -d tb", "args: --db-password={v}", "run -token={v}", "--token {v} --verbose",
    "--api-key {v}", "curl -u admin:{v} https://x.test", "curl --user admin:{v} x", "smtp:\n  password:\n    {v}\n",
    "secrets:\n  token:\n    - {v}\n", "postgres://u:ab/{v}@db/x", "redis://:p@{v}@host", "<password>{v}</password>",
    "<db:password type='x'>{v}</db:password>", "smtp password = {v}", "password = {v}", "Password : {v}",
    '{{"password":\n "{v}"}}', '{{"\\u0070assword": "{v}"}}', "next=%2Fx%253Fpassword%253D{v}",
    "PGPASSWORD={v} psql", "MYSQL_PWD={v}",
]  # fmt: skip


@pytest.mark.parametrize("form", M1_FORMS)
def test_m1_secret_forms_are_replaced(form: str) -> None:
    v = _v()
    out = bs.scrub_text(form.format(v=v))
    assert v not in out, out


def test_m1_the_reviewers_forms_leave_nothing_in_a_built_bundle(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    deploy, p, _add = make_box(tmp_path, mp)
    vals = [_v() for _ in range(3)]
    text = f"pg_dump --password={vals[0]}\nsmtp:\n  password:\n    {vals[1]}\nredis://:p@{vals[2]}@host\n"
    _gz(deploy.parent / "logs" / "services" / DAY / "adapter.log.gz", text.encode())
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    blob = _blob(out)
    assert not [v for v in vals if v.encode() in blob]


# ------------------------------------------------------------------------------------------------ M2
@pytest.mark.parametrize(
    "shape", ["Scr{n}", "SCR.{n}", "SCR {n}", "SCR#{n}", "SCR/{n}", "SCR:{n}", "\u7be9\u9078-{n}", "Ra01-{n}"]
)
def test_m2_other_screening_prefixes_are_masked(shape: str) -> None:
    no = shape.format(n=secrets.randbelow(9000) + 1000)
    out = bs.scrub_text(f"assigned {no} today")
    assert no not in out and "assigned" in out and "today" in out


def test_m2_the_prefix_the_console_takes_is_any_16_characters() -> None:
    """The docstring said ``[A-Za-z0-9_-]{0,16}``; the console takes any 16 characters (study_setup.py)."""
    src = (ROOT / "services/console/study_setup.py").read_text(encoding="utf-8")
    assert 'str(form.get("screening_prefix") or "").strip()[:16]' in src
    doc = bs.token_patterns.__doc__ or ""
    assert "any 16 characters" in doc


# ------------------------------------------------------------------------------------------------ M3
def _details(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        return [v for k, v in obj.items() if k == "detail"] + [d for v in obj.values() for d in _details(v)]
    if isinstance(obj, list):
        return [d for v in obj for d in _details(v)]
    return []


def test_m3_the_ops_snapshots_update_rows_keep_type_and_length(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    deploy, p, _add = make_box(tmp_path, mp)
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    snap = json.loads(dict(_archive(out))["support/ops-snapshot.json"])
    details = _details(snap)
    assert details, "the planted history gives the snapshot update rows with a detail"
    assert all(isinstance(d, dict) and set(d) == {"type", "length"} for d in details), details[:3]


# ------------------------------------------------------------------------------------------------ M4
#: calls that write a file or into an archive
WRITES = {"add", "addfile", "TarInfo", "TarFile", "writestr", "write", "writelines", "ZipFile", "ZipInfo",
          "GzipFile", "make_archive", "copyfile", "copy", "copy2", "copyfileobj", "move", "write_bytes",
          "write_text", "fdopen", "mkstemp", "NamedTemporaryFile"}  # fmt: skip
#: every such call in the two modules, by (function, call as written): a new one fails until it is reviewed here
ALLOWED = {
    ("_write_tar", "os.open"),  # the archive, 0600, O_EXCL
    ("_write_tar", "os.fdopen"),
    ("_write_tar", "tarfile.open"),
    ("_write_tar", "tar.addfile"),  # after every member passed is_clean
    ("_write_tar", "tarfile.TarInfo"),
    ("_build", "scan_copy.write_bytes"),  # a byte copy of the finished archive, for the last look
    *((part, "b.add") for part in ("_audit_part", "_box_part", "_build", "_cmd_part", "_logs_part")),  # Bundle.add
    ("_build", "used.add"),  # a set of names
    ("_logs_part", "third.add"),  # a set of service names
    ("declarations", "names.add"),  # sets of setting names
    ("declarations", "secret.add"),
}
OPENERS = {"open"}  # tarfile.open, gzip.open, zipfile.open, os.open, builtin open, Path.open, from-imported open


def _mode(node: ast.Call) -> str:
    for a in [*node.args[1:3], *(k.value for k in node.keywords if k.arg in ("mode", "flags"))]:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        if isinstance(a, ast.BinOp | ast.Attribute | ast.Name):
            return ast.unparse(a)
    return ""


def _calls(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[tuple[str, str]] = set()

    def visit(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else fn
            if isinstance(child, ast.Call):
                f = child.func
                last = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                if last in WRITES or (last in OPENERS and any(m in _mode(child) for m in ("w", "a", "x", "O_"))):
                    out.add((fn, ast.unparse(f)))
            visit(child, name)

    visit(tree, "<module>")
    return out


def test_m4_every_write_in_the_builder_and_the_scrub_is_a_reviewed_one() -> None:
    found = _calls(ROOT / "tools/support_bundle.py") | _calls(ROOT / "tools/bundle_scrub.py")
    assert found == ALLOWED, sorted(found ^ ALLOWED)


@pytest.mark.parametrize(
    "src",
    [
        "def h(tar, f):\n    tar.add(f, arcname='x')\n",
        "import shutil\ndef h(d):\n    shutil.make_archive('x', 'gztar', d)\n",
        "import gzip\ndef h(p):\n    gzip.GzipFile(p, 'wb')\n",
        "from tarfile import open\ndef h(p):\n    open(p, 'w:gz')\n",
        "import zipfile\nz = zipfile.ZipFile('x.zip', 'w')\n",
        "def h(p, b):\n    p.write_bytes(b)\n",
    ],
)
def test_m4_the_write_finder_is_not_blind(src: str, tmp_path: Path) -> None:
    f = tmp_path / "probe.py"
    f.write_text(src, encoding="utf-8")
    assert _calls(f) - ALLOWED, src


def test_m4_no_other_module_writes_a_bundle() -> None:
    """Only the command dispatcher imports the builder; nothing else can make a bundle past ``_write_tar``."""
    users = sorted(
        str(f.relative_to(ROOT))
        for d in ("tools", "services", "libs")
        for f in (ROOT / d).rglob("*.py")
        if f.name not in ("support_bundle.py", "bundle_scrub.py")
        and any(m in f.read_text(encoding="utf-8", errors="replace") for m in ("support_bundle", "bundle_scrub"))
    )
    # rc1 (R22-34; the integrator's go, 7080384411): the refusals' table names the builder as its site, and only names
    # it: it neither imports nor calls the bundle's modules
    assert users == ["libs/tb_common/rc1_refusals.py", "tools/trialbox/__main__.py"], users
    table = ast.parse((ROOT / "libs" / "tb_common" / "rc1_refusals.py").read_text(encoding="utf-8"))
    imported = [n for n in ast.walk(table) if isinstance(n, ast.Import | ast.ImportFrom)
                and any(m in ast.unparse(n) for m in ("support_bundle", "bundle_scrub"))]  # fmt: skip
    called = [n for n in ast.walk(table) if isinstance(n, ast.Call)
              and any(m in ast.unparse(n.func) for m in ("support_bundle", "bundle_scrub", "build"))]  # fmt: skip
    assert imported == [] and called == [], (imported, called)


# ------------------------------------------------------------------------------------------------ speed
#: worst cases for each rule: a long run of one class of character on one line (1 MB or 256 KB)
LONG = {
    "hex": "0123456789abcdef" * 65536, "digits": "1234567890" * 104858, "letters": "abcdefghij" * 104858,
    "upper": "ABCDEFGHIJ" * 26215, "at": "@" * 262144, "colon": ":" * 262144, "slash": "/" * 262144,
    "percent": "%2F" * 87382, "equals": "a=" * 131072, "dash": "a-" * 131072, "quote": '"' * 262144,
    "backslash-u": "\\u0041" * 43690, "word-colon": "ab:" * 87382, "scheme": "a://" * 65536,
    "spaces-digits": "SCR 1234 " * 29127, "pem-ish": ("A" * 64 + "\\n") * 3971, "amp": "&#x2F;" * 43690,
    "key-eq": "password=" * 29127, "dots": "a." * 131072, "hex-dash": "abcd-" * 52429,
}  # fmt: skip
LIMIT = 20.0  # seconds for one scrub of the line, a CI runner included (one pass took 32 s on 100 KB before)


@pytest.mark.parametrize("kind", sorted(LONG))
def test_speed_every_rule_is_linear_on_a_long_line(kind: str) -> None:
    s = bs.Scrubber.for_bundle()
    start = time.monotonic()
    s.text("start " + LONG[kind] + " end\n")
    took = time.monotonic() - start
    assert took < LIMIT, f"{kind}: {took:.1f} s"


# ------------------------------------------------------------------------------------------------ L1 to L3
@pytest.mark.parametrize("form", ['"short": "{s}"', "#x-{s}", "p {s} done", "/p/{s}/", "pid={s}"])
def test_l1_the_bare_short_pseudonym_is_masked(form: str) -> None:
    s = _pid()[:8]
    assert s not in bs.scrub_text(form.format(s=s))


def test_l1_the_short_form_with_its_ellipsis_is_masked_even_all_decimal() -> None:
    """The bare rule wants a hex letter; the ``…`` form needs none (a round-1 test failed 2 times in 100 on it)."""
    short = "".join(secrets.choice("0123456789") for _ in range(8))
    assert bs.scrub_text(f"two chart numbers ({short}…)") == "two chart numbers ([pseudonym])"


def test_l2_names_that_collide_after_the_scrub_both_stay(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    deploy, p, _add = make_box(tmp_path, mp)
    a, b = tmp_path / "pw=a1.txt", tmp_path / "pw=b2.txt"
    a.write_text("first file\n", encoding="utf-8")
    b.write_text("second file\n", encoding="utf-8")
    out = sb.build(deploy, tmp_path / "usb", add=[a, b], runner=_runner(p), now=NOW, say=lambda _: None)
    texts = [d.decode() for n, d in _archive(out) if n.startswith("support/added/")]
    assert sorted(t.strip() for t in texts) == ["first file", "second file"]


def test_l3_a_trailing_invalid_byte_of_a_file_not_cut_is_not_text() -> None:
    assert bs.as_text(b"caf\xe9") is None
    assert bs.as_text(b"caf\xc3") is None  # a cut character, but the file was not cut
    assert bs.as_text(b"caf\xc3", cut=True) == "caf"


def test_the_extended_corpus_still_holds_the_invariant(tmp_path: Path, mp: pytest.MonkeyPatch) -> None:
    """The planted corpus now carries every form above (H1, M1, M2, L1): the whole bundle is checked again."""
    deploy, p, add = make_box(tmp_path, mp)
    out = sb.build(deploy, tmp_path / "usb", add=[add], runner=_runner(p), now=NOW, say=lambda _: None)
    _assert_clean(out, p)
