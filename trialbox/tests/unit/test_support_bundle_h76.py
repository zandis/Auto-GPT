"""H-76, the follow-up of H-71: a test per finding, red before its fix and green after. Every random value is drawn
from a fixed seed (the test's id, or a named ``random.Random``): no run depends on the order, the worker or
``--dist``. Synthetic values only.

Findings (the page ``docs/handover/support-bundle-scrub-follow-up-2026-11-22.md``): H76-01 the flake; H76-02 a
twice-encoded secret cut at a decoded separator; H76-03 encodings not decoded (five or more percent layers, an entity
without ``;``, quoted-printable without ``=3D``); H76-04 a token split by a soft line break or an invisible
character; H76-05 command lists and other secret forms; H76-06 screening prefixes; H76-07 a subprocess writer;
H76-08 a box secret encoded twice with no name; H76-09 base64; H76-10 the 64 MB read cut; H76-11 the fuzz test."""

from __future__ import annotations

import ast
import base64
import contextlib
import json
import quopri
import random
import re
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.unit.test_support_bundle_planted import DAY, NOW, _archive, _gz, _runner, make_box
from tests.unit.test_support_bundle_review1 import ENCODED
from tools import bundle_scrub as bs
from tools import support_bundle as sb

ROOT = Path(__file__).resolve().parents[2]

#: pseudonyms that left in part when the raw line's phone pattern cut them before the decoded view read the line
#: (found by drawing 20 000 pseudonyms; the invariant test failed on master about once in 60 runs)
FLAKE_PIDS = [
    "81e464e3dfaa0b022044419fbefa9f1c",
    "d8817e0af088239924d57d1e46814959",
    "a4382307164f7a7aeac52f0812439029",
    "26c022565768fa8585689c072bad30b1",
    "b361e31377878455f7e058958255d770",
    "7a78124708f93f3bd003236707c9b2a5",
]


def _rng(name: str) -> random.Random:
    return random.Random(f"H-76|{name}")


def _pid(rng: random.Random) -> str:
    return rng.getrandbits(128).to_bytes(16, "big").hex()


def _value(rng: random.Random) -> str:
    """A secret's value of letters only, so that no phone or chart-number pattern can take part of it."""
    return "v" + "".join(rng.choice("bcdfghjkmnpqrstvwxz") for _ in range(18))


def _left(pid: str, out: str) -> list[str]:
    """Every run of 8 or more of the pseudonym's digits that is still in ``out`` (any case)."""
    low = out.lower()
    return [pid[i : i + 8] for i in range(len(pid) - 7) if pid[i : i + 8] in low]


_B64RUN = re.compile(r"[A-Za-z0-9+/_\-]{16,}={0,2}")


def views(text: str) -> str:
    """``text`` with every view a reader could take of it: as written, decoded (percent, entities, escapes,
    quoted-printable, invisible characters out), and every base64 run decoded, twice."""
    out = [text, bs._decode(text), bs._decode(text.replace("=\n", "")), bs._decode(text.replace("=\r\n", ""))]
    for _ in range(2):
        more = []
        for m in _B64RUN.finditer("\n".join(out)):
            run = m.group(0)
            for dec in (base64.b64decode, base64.urlsafe_b64decode):
                with contextlib.suppress(ValueError):
                    more.append(dec(run + "=" * (-len(run) % 4)).decode("utf-8", errors="ignore"))
        out += more
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ H76-01 the flake
@pytest.mark.parametrize("pid", FLAKE_PIDS)
def test_flake_the_pseudonyms_that_left_are_masked_whole(pid: str) -> None:
    line = f"next=%252Fp%252F{pid}%253Fpassword%253Dabc"
    assert _left(pid, bs.Scrubber.for_bundle().text(line)) == []


@pytest.mark.parametrize("form", ENCODED)
def test_flake_class_no_raw_rule_cuts_a_token_before_the_decoded_view(form: str) -> None:
    """The class: a token that the raw line hides (its encoded neighbour joins it) must reach the decoded view whole.
    150 pseudonyms a form, from a fixed seed; no 8 of their digits may stay."""
    rng = random.Random(f"H-76 flake class {form}")
    s = bs.Scrubber.for_bundle()
    for _ in range(150):
        pid = _pid(rng)
        out = s.text("x=" + form.format(t=pid) + "&y=1 tail")
        assert _left(pid, out) == [], (pid, out)


# ------------------------------------------------------------------------------------------------ H76-02
@pytest.mark.parametrize("sep", ["%2526", "%2520", "%2522", "%252C", "%253B", "%25252526"])
def test_h76_02_a_twice_encoded_secret_is_not_cut_at_a_decoded_separator(sep: str) -> None:
    rng = _rng(f"02 {sep}")
    head, tail = _value(rng), _value(rng)
    out = bs.scrub_text(f"next=%252Fx%253Fpassword%253D{head}{sep}{tail} done")
    assert head not in views(out) and tail not in views(out), out


# ------------------------------------------------------------------------------------------------ H76-03
FORMS_03 = [
    "back=%252525252F{t}", "back=%25252525252F{t}", "back=%2525252525252f{t}", "&#47{t}", "&#x2f{t}", "&#X2F{t}",
    "Patient n=C2=B0{t} enrolled", "n=2F{t}=20done", "\\\\x2f{t}", "\\\\\\\\u002f{t}",
]  # fmt: skip


@pytest.mark.parametrize("form", FORMS_03)
def test_h76_03_encodings_the_first_round_left_are_decoded(form: str) -> None:
    rng = _rng(f"03 {form}")
    for _ in range(40):
        pid = _pid(rng)
        out = bs.Scrubber.for_bundle().text(form.format(t=pid))
        assert _left(pid, views(out)) == [], (pid, out)


@pytest.mark.parametrize("form", ["next=%25252525253Fpassword%25252525253D{v} x", "q=&#112assword={v}"])
def test_h76_03_a_secret_under_many_layers_is_replaced(form: str) -> None:
    v = _value(_rng(f"03s {form}"))
    assert v not in views(bs.scrub_text(form.format(v=v)))


# ------------------------------------------------------------------------------------------------ H76-04
SPLITS = ["=\n", "=\r\n", "%E2%80%8B", "%e2%80%8b", "&shy;", "\u200b", "­", "⁠", "﻿", "&#8203;", "\\u200b"]


@pytest.mark.parametrize("cut", SPLITS)
def test_h76_04_a_pseudonym_split_by_a_soft_break_or_an_invisible_character_is_masked(cut: str) -> None:
    rng = _rng(f"04 {cut!r}")
    for _ in range(40):
        pid = _pid(rng)
        k = 4 + rng.randrange(24)
        out = bs.Scrubber.for_bundle().text(f"patient {pid[:k]}{cut}{pid[k:]} seen\n")
        assert _left(pid, views(out)) == [], (pid, out)


@pytest.mark.parametrize("cut", SPLITS)
def test_h76_04_a_secret_split_by_a_soft_break_or_an_invisible_character_is_replaced(cut: str) -> None:
    v = _value(_rng(f"04s {cut!r}"))
    out = bs.scrub_text(f"login password={v[:9]}{cut}{v[9:]} ok\n")
    assert v not in views(out) and v[9:] not in out, out


# ------------------------------------------------------------------------------------------------ H76-05
FORMS_05 = [
    "command:\n  - --password\n  - {v}\n", "    command:\n      - \"--password\"\n      - \"{v}\"\n",
    'command: ["--password", "{v}"]', '["serve", "--api-key", "{v}", "--port", "80"]', "run --password -{v}",
    "password:\n{v}\n", "cfg |   password:\ncfg |     {v}\n", "web-1  | smtp:\nweb-1  |   password: {v}\n",
    "postgres://u:ab'{v}@db/x", "--token {v}",
]  # fmt: skip


@pytest.mark.parametrize("form", FORMS_05)
def test_h76_05_command_lists_and_other_forms_are_replaced(form: str) -> None:
    v = _value(_rng(f"05 {form}"))
    out = bs.scrub_text(form.format(v=v))
    assert v not in out, out


def test_h76_05_a_flag_that_is_not_a_secret_keeps_its_value() -> None:
    assert bs.scrub_text('command: ["serve", "--port", "8080", "--workers", "4"]').count("8080") == 1


# ------------------------------------------------------------------------------------------------ H76-06
@pytest.mark.parametrize("shape", ["Scr.{n}", "S.{n}", "S#{n}", "Rq/{n}", "篩選{n}", "RA 01 {n}", "RQ 7 A {n}"])
def test_h76_06_more_screening_prefixes_are_masked(shape: str) -> None:
    no = shape.format(n=1000 + _rng(f"06 {shape}").randrange(9000))
    out = bs.scrub_text(f"assigned {no} today")
    assert no not in out and "assigned" in out and "today" in out


# ------------------------------------------------------------------------------------------------ H76-07
#: calls that start another program: one could write a side archive the guard of ``_write_tar`` never sees
SPAWN = {"run", "Popen", "call", "check_call", "check_output", "system", "popen", "spawnl", "spawnv", "execv",
         "execvp", "execl", "startfile", "create_subprocess_exec", "create_subprocess_shell"}  # fmt: skip
SPAWN_ALLOWED = {
    ("support_bundle:run_cmd", "subprocess.run"),  # the commands of the bundle; their output goes through the scrub
    ("support_bundle:last_look", "ds.run"),  # tools.data_scan.run: the last look reads the archive, it starts nothing
    # the egress rules asked of one container of the box image (already on the base: no network, no mount)
    ("bundle_scrub:_Image.__init__", "subprocess.Popen"),
}


def _spawns(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[tuple[str, str]] = set()

    def visit(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = fn
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{fn}.{child.name}" if fn else child.name
            if isinstance(child, ast.Call):
                f = child.func
                last = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                if last in SPAWN:
                    out.add((f"{path.stem}:{fn or '<module>'}", ast.unparse(f)))
            visit(child, name)

    visit(tree, "")
    return out


def test_h76_07_no_program_is_started_but_the_reviewed_ones() -> None:
    found = _spawns(ROOT / "tools/support_bundle.py") | _spawns(ROOT / "tools/bundle_scrub.py")
    assert found == SPAWN_ALLOWED, sorted(found ^ SPAWN_ALLOWED)


@pytest.mark.parametrize(
    "src",
    [
        "import subprocess\ndef h(o, d):\n    subprocess.run(['tar', 'czf', o, '-C', d, '.'])\n",
        "import os\ndef h():\n    os.system('tar czf x.tgz .')\n",
        "from subprocess import Popen\ndef h():\n    Popen(['tar'])\n",
    ],
)
def test_h76_07_the_finder_sees_a_subprocess_writer(src: str, tmp_path: Path) -> None:
    f = tmp_path / "probe.py"
    f.write_text(src, encoding="utf-8")
    assert _spawns(f) - SPAWN_ALLOWED, src


# ------------------------------------------------------------------------------------------------ H76-08
def test_h76_08_a_box_secret_encoded_twice_with_no_name_is_hidden() -> None:
    value = "Ab3/Kq9+Zz7/Rw2=Q" + _value(_rng("08"))[:6]
    twice = urllib.parse.quote(urllib.parse.quote(value, safe=""), safe="")
    for form in (twice, urllib.parse.quote(twice, safe=""), base64.b64encode(value.encode()).decode()):
        text, n = sb.hide_values(f"next=%2Fcb%3Fstate%3D{form} end", {"SMTP_PASS": value})
        assert form not in text and n == 1, form
        assert sb.still_held(f"state={form}", {"SMTP_PASS": value}) == ["SMTP_PASS"]


# ------------------------------------------------------------------------------------------------ H76-09
def _b64forms(raw: bytes) -> list[str]:
    std, url = base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()
    return [std, std.rstrip("="), url, url.rstrip("=")]


def test_h76_09_a_pseudonym_inside_base64_is_masked() -> None:
    rng = _rng("09")
    for _ in range(40):
        pid = _pid(rng)
        doc = json.dumps({"patient": pid, "step": "screen"}).encode()
        inner = base64.b64encode(doc).decode()
        cases = [f"payload={f}" for f in _b64forms(doc)]
        cases += [json.dumps({"data": f}) for f in _b64forms(doc)]  # nested once in JSON
        cases += [f"outer={base64.b64encode(json.dumps({'blob': inner}).encode()).decode()}"]  # base64 in base64
        for case in cases:
            out = bs.Scrubber.for_bundle().text(case)
            assert _left(pid, views(out)) == [], (pid, case, out)


def test_h76_09_base64_of_binary_and_ordinary_runs_are_left_as_they_are() -> None:
    rng = _rng("09b")
    blob = base64.b64encode(bytes(rng.getrandbits(8) for _ in range(300))).decode()
    text = f"image={blob} sha256 {'ab12' * 16} word supercalifragilisticexpialidocious_value_here"
    assert bs.scrub_text(text) == text


# ------------------------------------------------------------------------------------------------ H76-10
@pytest.mark.parametrize("kind", ["pseudonym", "screening", "secret"])
def test_h76_10_a_token_cut_by_the_read_limit_leaves_no_fragment(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy, p, _add = make_box(tmp_path, monkeypatch)
    monkeypatch.setattr(sb, "MAX_MEMBER", 1024)  # the read limit is MAX_MEMBER * 4 = 4096 bytes
    rng = _rng(f"10 {kind}")
    token = {"pseudonym": _pid(rng), "screening": f"RA77-{1000 + rng.randrange(9000)}", "secret": _value(rng)}[kind]
    lead = {"pseudonym": "patient ", "screening": "assigned ", "secret": "login password="}[kind]
    head = "lake | ok\n" * 400  # 4000 bytes
    line = f"lake | {lead}{token} done\n"
    cut = 4096 - len(head) - len(f"lake | {lead}") - len(token) // 2  # the read limit falls inside the token
    text = head[: len(head) + cut] if cut < 0 else head + "x" * cut
    _gz(deploy.parent / "logs" / "services" / DAY / "lake.log.gz", (text + line + "lake | after\n").encode())
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    members = dict(_archive(out))
    blob = b"\n".join(members.values()).decode()
    frag = token[: len(token) // 2]
    assert len(frag) >= 4 and frag.lower() not in blob.lower(), frag
    changed = json.loads(members["support/MANIFEST.json"])["changed"]
    assert changed[f"logs/{DAY}/lake.log"].get("cut_at_read_limit") == 1


# ------------------------------------------------------------------------------------------------ H76-11 fuzz
def _pct(s: str, layers: int, upper: bool) -> str:
    for _ in range(layers):
        s = urllib.parse.quote(s, safe="")
        s = s if upper else re.sub("%[0-9A-F]{2}", lambda m: m.group(0).lower(), s)
    return s


def _ent(s: str, rng: random.Random) -> str:
    out = []
    for ch in s:
        if ch.isalnum() and rng.random() < 0.7:
            out.append(ch)
            continue
        form = rng.choice([f"&#{ord(ch)};", f"&#x{ord(ch):x};", f"&#X{ord(ch):X};"])
        out.append(form)
    return "".join(out)


def _esc(s: str, rng: random.Random) -> str:
    return "".join(rng.choice([f"\\u{ord(c):04x}", f"\\x{ord(c):02x}", c, c]) if ord(c) < 256 else c for c in s)


def _qp(s: str, rng: random.Random) -> str:
    units = [f"={ord(c):02X}" if (not c.isalnum() or rng.random() < 0.3) else c for c in s]
    k = rng.randrange(1, len(units))
    return "".join(units[:k]) + "=\n" + "".join(units[k:])  # a soft line break between two units, as QP writes it


def _inv(s: str, rng: random.Random) -> str:
    k = rng.randrange(1, len(s) - 1)
    return s[:k] + rng.choice(["\u200b", "­", "%E2%80%8B", "&shy;", "&#8203;", "﻿"]) + s[k:]


def _b64(s: str, rng: random.Random) -> str:
    doc = json.dumps({"line": s}) if rng.random() < 0.5 else s
    f = rng.choice(_b64forms(doc.encode()))
    return json.dumps({"b": f}) if rng.random() < 0.3 else f"blob={f}"


CLASSES: dict[str, Callable[[str, random.Random], str]] = {
    "percent": lambda s, r: _pct(s, r.randrange(1, 7), r.random() < 0.5),
    "entity": _ent,
    "escape": _esc,
    "quoted-printable": _qp,
    "invisible": _inv,
    "base64": _b64,
}


@pytest.mark.parametrize("cls", sorted(CLASSES))
def test_h76_11_fuzz_every_encoding_class_through_a_built_bundle(
    cls: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """150 cases a class from a fixed seed: a pseudonym, a screening number or a secret pair, encoded, in a
    collected log; the archive's every view is read back for any of them."""
    deploy, p, _add = make_box(tmp_path, monkeypatch)
    rng = _rng(f"11 {cls}")
    planted: list[tuple[str, str]] = []
    lines = []
    for i in range(150):
        kind = ("pseudonym", "screening", "secret")[i % 3]
        if kind == "pseudonym":
            token = _pid(rng)
            plain = f"/studies/RA01/patients/{token}"
        elif kind == "screening":
            token = f"RA{10 + rng.randrange(89)}-{1000 + rng.randrange(9000)}"
            plain = f"/screening/{token}/notes"
        else:
            token = _value(rng)
            plain = f"/login?user=amy&password={token}&lang=en"
        planted.append((kind, token))
        lines.append(f"2026-11-21T01:{i % 60:02d}:00Z gateway | GET {CLASSES[cls](plain, rng)} 200\n")
    _gz(deploy.parent / "logs" / "services" / DAY / "gateway.log.gz", "".join(lines).encode())
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=lambda _: None)
    member = dict(_archive(out))[f"support/logs/{DAY}/gateway.log"].decode()
    seen = views(member)
    left = [(k, t) for k, t in planted if (_left(t, seen) if k == "pseudonym" else t.lower() in seen.lower())]
    assert left == [], f"{len(left)} of 150 left, e.g. {left[:3]}"


# ------------------------------------------------------------------------------------------------ speed kept
LONG_76 = {
    "base64-text": base64.b64encode(b"patient record " * 70000).decode(),
    "percent-pct": "%25" * 349525,
    "entities-no-semicolon": "&#47" * 262144,
    "qp-pairs": "=C2=B0" * 174762,
    "invisibles": "a\u200b" * 262144,
    "flag-list": '"--x", ' * 149796,
}  # fmt: skip


@pytest.mark.parametrize("kind", sorted(LONG_76))
def test_speed_the_new_rules_are_linear_on_a_long_line(kind: str) -> None:
    s = bs.Scrubber.for_bundle()
    start = time.monotonic()
    s.text("start " + LONG_76[kind] + " end\n")
    took = time.monotonic() - start
    assert took < 20.0, f"{kind}: {took:.1f} s"


# ------------------------------------------------------------------------------------------------ second guards
def test_the_raw_rule_masks_a_pseudonym_under_any_percent_layer_without_the_decoded_view() -> None:
    """The decoded view is the first guard; the raw rule masks the same pseudonym on its own (a line the view cannot
    decode, a member written in place). The mutation pass found no test that held this second guard."""
    pid = _pid(_rng("raw layers"))
    for prefix in ("%2F", "%252F", "%25252F", "%2525252525252F", "&#47", "&#x2f;", "=C2=B0", "\\x2f", "\\\\u002F"):
        out = bs.Scrubber().pseudonyms(f"back={prefix}{pid}%22")
        assert pid not in out, prefix


# ------------------------------------------------------------------------------------------------ review of #1354
def _chart(digits: int, bound: str = "0-9") -> re.Pattern[str]:
    """A chart-number pattern of ``digits`` digits. ``bound`` is what may not stand beside it: ``0-9A-Za-z`` as
    ``mrn_pattern`` wraps a site's pattern, or digits only, as the review's probe did (and as the log scrubber's own
    phone patterns are bounded), which fires between the letters of a hex run."""
    return re.compile(rf"(?<![{bound}])[0-9]{{{digits}}}(?![{bound}])")


def _run_left(pid: str, out: str, n: int = 5) -> list[str]:
    """Every run of ``n`` or more of the pseudonym's characters still in ``out`` (any case)."""
    low = out.lower()
    return [pid[i : i + n] for i in range(len(pid) - n + 1) if pid[i : i + n] in low]


def _timed(fn: Callable[[], object]) -> float:
    best = 1e9
    for _ in range(3):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def test_review_h1_a_line_that_cannot_be_lined_up_does_not_hang_the_scrub() -> None:
    """#1354 H1: 24 masks on a 335-character line took 9.7 s (0.04 s on master); each 4 more masks multiplied it by
    16. The bound is a small multiple of master's time, on a slow runner too."""
    probe = "%2F " + " ".join(["03-1234-5678"] * 24) + " 'token': abcdefgh12"
    took = _timed(lambda: bs.Scrubber.for_bundle().text(probe))
    assert took < 0.5, f"{took:.2f} s"


def test_review_m1_two_raw_rules_that_cut_a_pseudonym_leave_nothing_of_it() -> None:
    """#1354 M1: with a 7-digit chart pattern the raw rules cut the pseudonym into pieces under 8 digits each, and
    the shortcut kept the raw line: ``next=%2Fe3b296e[MRN]c702d[PHONE]c2e7``."""
    pid = "e3b296e6352540c702d051568971c2e7"
    out = bs.Scrubber.for_bundle(mrn=_chart(7)).text(f"next=%2F{pid}")
    assert _run_left(pid, out) == [], out


@pytest.mark.parametrize("bound", ["0-9", "0-9A-Za-z"])
@pytest.mark.parametrize("digits", range(5, 11))
def test_review_m1_class_no_pair_of_raw_rules_leaves_part_of_a_pseudonym(digits: int, bound: str) -> None:
    """The class: a site's chart pattern of 5 to 10 digits and the log scrubber's phone patterns, each able to cut a
    pseudonym hidden by an encoding. 150 seeded pseudonyms, each in one of the encoded forms: no run of 5 or more of
    its characters may remain (a run of 4 can stand in other text by chance; the page says so)."""
    rng = random.Random(f"H-76a review M1 class {digits} {bound}")
    s = bs.Scrubber.for_bundle(mrn=_chart(digits, bound))
    for _ in range(150):
        pid = "".join(rng.choice("0123456789abcdef" if rng.random() < 0.5 else "0123456789") for _ in range(32))
        form = rng.choice(ENCODED)
        out = s.text("x=" + form.format(t=pid) + "&y=1")
        assert _run_left(pid, out) == [], (form, pid, out)


#: the time bounds of the scrub's tests, in one place (#1354 round 3, L4): a line of 48 masks, and the ratio of 4,000
#: masks to 1,000 on one line (linear is 4; a quadratic path is 16; no slack added)
BOUNDS = {"line_of_48_masks_s": 0.5, "four_times_the_masks_ratio": 6.0}


@pytest.mark.parametrize(
    "unit",
    ["03-1234-5678", "0912-345-678", "RA01-0042", "password=abcd1234", "a1b2c3d4e5f60718293a4b5c6d7e8f90"],
)
def test_review_the_scrub_of_one_line_is_linear_in_its_masks(unit: str) -> None:
    """No line of 48 masks may take more than its bound, and four times the masks may take at most the bound's ratio
    of the time (a linear scrub; the hang grew 16-fold with each 4 masks). Timed at 1,000 and 4,000 masks, where the
    time is far above a timer's noise, so the ratio needs no slack."""
    line = {n: "%2F " + " ".join([unit] * n) + " 'token': abcdefgh12" for n in (48, 1000, 4000)}
    t48 = _timed(lambda: bs.Scrubber.for_bundle().text(line[48]))
    assert t48 < BOUNDS["line_of_48_masks_s"], f"{t48:.2f} s"
    t1 = _timed(lambda: bs.Scrubber.for_bundle().text(line[1000]))
    t4 = _timed(lambda: bs.Scrubber.for_bundle().text(line[4000]))
    assert t4 <= BOUNDS["four_times_the_masks_ratio"] * t1, f"1,000 masks {t1:.3f} s, 4,000 masks {t4:.3f} s"


def test_review_the_raw_line_is_kept_only_when_it_is_the_view_mark_for_mark() -> None:
    """The condition of the fix, held directly (the mutation pass found no line that told an equal length or a part
    from the whole): a different mark, a mark missing, the same length, and one inside the other are not the same."""
    same = "next=/p/[pseudonym #bcdfg]?password=[redacted]"
    assert bs._same_masks(same, same)
    assert not bs._same_masks("next=/p/[MRN]?password=[redacted]", same)  # another mark in its place
    assert not bs._same_masks("next=/p/9659a6d97592b[PHONE]aba1a4b274", "next=/p/[pseudonym #bcdfg]")
    assert not bs._same_masks("ab[x]cd", "abc[x]d")  # the same length
    assert not bs._same_masks("a[x]", "a[x]b") and not bs._same_masks("a[x]b", "a[x]")  # a part of the other
    assert not bs._same_masks("pid=ABCDEF[x]", "pid=abcdef[x]")  # a case of its own: not the same text


def test_the_planted_invariants_encodings_are_the_scrub_tests() -> None:
    from tests.unit.test_support_bundle_planted import ENCODINGS

    assert sorted(ENCODINGS.values()) == sorted(ENCODED) and len(ENCODINGS) == 16


# ------------------------------------------------------------------------------------------------ round B: timing
@pytest.mark.parametrize("kind", sorted(LONG_76))
def test_speed_doubling_a_long_line_at_most_doubles_the_time(kind: str) -> None:
    """No rule is super-linear: twice the input takes at most 2.2 times as long (best of three, plus 0.05 s)."""
    unit = LONG_76[kind][: len(LONG_76[kind]) // 4]
    s = bs.Scrubber.for_bundle()
    t1 = _timed(lambda: s.text("start " + unit + " end\n"))
    t2 = _timed(lambda: s.text("start " + unit + unit + " end\n"))
    assert t2 <= 2.2 * t1 + 0.05, f"{kind}: {t1:.3f} s, twice the input {t2:.3f} s"


def test_a_large_member_is_announced_with_its_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round B: a 64 MiB log takes minutes; the operator is told so before, not left at a silent prompt."""
    deploy, p, _add = make_box(tmp_path, monkeypatch)
    monkeypatch.setattr(sb, "SAY_LARGE", 1024)
    _gz(deploy.parent / "logs" / "services" / DAY / "lake.log.gz", ("lake | ok\n" * 400).encode())
    said: list[str] = []
    sb.build(deploy, tmp_path / "usb", runner=_runner(p), now=NOW, say=said.append)
    assert any(s.startswith(f"scrubbing logs/{DAY}/lake.log (") and "minute" in s for s in said), said


@pytest.mark.parametrize(
    "line",
    [
        "GET /p/%2F--passwd%20D9tshbrt5tntdg%20A123456789 200",  # found by the mutation search of round 3
        "GET /p/%2F--token%20Q7xk2mVb9tLpw%20RA01-0042 200",
        "x=%2F--api-key%20Wm4k8pZq2xJr%2003-1234-5678",
    ],
)
def test_review_an_encoded_flag_value_beside_an_identifier_leaves_nothing(line: str) -> None:
    """#1354 round 3, L5: a raw line the same length as its view, but not the view, is not kept (a mutant that kept
    it left the value; only the direct ``_same_masks`` test told it apart before)."""
    value = line.split("%20")[1]
    out = bs.Scrubber.for_bundle().text(line)
    assert value.lower() not in (out + bs._decode(out)).lower(), out


@pytest.mark.parametrize(
    "line",
    [
        "--password Kq7w%20Zx9m",
        '"password": "Kq7w\\u0022Zx9m"',
        "Authorization: Bearer Kq7w%0AZx9m",
        "password=Kq7w%0aZx9m",
        "password=Kq7w&#10;Zx9m",
    ],
)
def test_review_a_secret_masked_on_the_raw_line_stays_masked_when_the_line_is_written_decoded(line: str) -> None:
    """#1354 round 3, H2: an encoded separator inside a secret's value (a space, a quote, a line break) cuts the value
    in the decoded view, so the view alone masks only its first part. The secret rule runs on the raw line first,
    and no part of the value is left (through the bundle's path: ``scrub_text``, then ``redact_secrets``)."""
    out, _ = sb.redact_secrets(bs.scrub_text(line))
    seen = out + "\n" + bs._decode(out)
    assert "Kq7w" not in seen and "Zx9m" not in seen, out


@pytest.mark.parametrize("line", ["%2F %2F[--password%20Wq3bKmZt9x]", "%2F %2F[--password%20Wq3bKmZt9x] user=amy"])
def test_review_a_secret_inside_a_log_s_own_brackets_is_not_taken_for_a_mask(line: str) -> None:
    """#1354 round 3, L5: a log's own ``[...]`` is text, not a mask; a comparison that blanked every bracket kept the
    raw line with the value in it (only the direct ``_same_masks`` test told it apart before)."""
    out, _ = sb.redact_secrets(bs.scrub_text(line))
    assert "wq3bkmzt9x" not in (out + "\n" + bs._decode(out)).lower(), out


# ------------------------------------------------------------------------------------------------ review 1634.1
# A regex scrub cannot know every shape: where a value's end is ambiguous, it masks to the end of the quoted value,
# the field or the line (more, never less). Synthetic names and values only.
def _bundle(line: str) -> str:
    out, _ = sb.redact_secrets(bs.scrub_text(line))
    return out + "\n" + bs._decode(out)


@pytest.mark.parametrize(
    "line",
    [
        'mysql --password "Kq7w Zx9m Pt4r" -h db',
        "mysql --password 'Kq7w Zx9m Pt4r' -h db",
        'mysql --password "Kq7w \\"Zx9m\\" Pt4r" -h db',
    ],
)
def test_review_r1_a_quoted_flag_value_with_spaces_is_replaced_whole(line: str) -> None:
    seen = _bundle(line)
    assert not [w for w in ("Kq7w", "Zx9m", "Pt4r") if w in seen], seen


@pytest.mark.parametrize(
    "line",
    ['["mysql", "--password", "-Kq7w Zx9m"]', '["mysql", "--password", "Kq7w Zx9m"]', "['--token', 'Kq7w Zx9m']"],
)
def test_review_r3_a_quoted_list_value_with_a_hyphen_or_a_space_is_replaced(line: str) -> None:
    seen = _bundle(line)
    assert "Kq7w" not in seen and "Zx9m" not in seen, seen


def test_review_r4_a_short_base64_email_is_masked() -> None:
    enc = base64.b64encode(b"tx@ex.jp").decode()
    assert len(enc) < 24
    out = bs.scrub_text(f"contact {enc} ok")
    assert enc not in out and "tx@ex.jp" not in views(out), out


@pytest.mark.parametrize("tag", ["患者氏名", "病患姓名", "氏名", "住所"])
def test_review_r5_an_xml_element_with_a_cjk_label_is_masked(tag: str) -> None:
    out = bs.scrub_text(f"<{tag}>Testo Hanako</{tag}>")
    assert "Testo" not in out and "Hanako" not in out, out


def test_review_r6_a_quoted_printable_utf8_label_is_read_before_the_labels() -> None:
    label = quopri.encodestring("患者氏名".encode()).decode()
    assert label.startswith("=E6")
    out = bs.scrub_text(f"{label}: Testo Hanako\n")
    seen = out + "\n" + quopri.decodestring(out.encode()).decode("utf-8", "replace")
    assert "Testo" not in seen and "Hanako" not in seen, out


@pytest.mark.parametrize(
    "line", ['{"patient_name": "Testo \\"Tee\\" Hanako", "n": 1}', '{"address": "1 Testo St \\"B\\" Hanako-cho"}']
)
def test_review_r7_an_escaped_quote_inside_a_labelled_value_does_not_end_it(line: str) -> None:
    seen = bs.scrub_text(line)
    assert "Testo" not in seen and "Hanako" not in seen, seen


def test_review_r8_a_spaced_screening_number_before_a_count_is_masked() -> None:
    out = bs.scrub_text("RA 0042 2 visits")
    assert "0042" not in out, out


@pytest.mark.parametrize(
    "line",
    [
        'mysql --password "first"second -h db',
        "mysql --password 'Kq7w Zx9m'Pt4r -h db",
        "mysql --password Kq7w\\ Zx9m -h db",
        'mysql --password Kq7w"Zx9m Pt4r"Wv2c -h db',
        "mysql --password 'Kq7w'\"Zx9m Pt4r\"Wv2c -h db",
    ],
)
def test_review_r1b_a_flag_value_is_the_whole_shell_word(line: str) -> None:
    out = bs.scrub_text(line)
    assert not [w for w in ("first", "second", "Kq7w", "Zx9m", "Pt4r", "Wv2c") if w in out], out
    assert out.endswith(" -h db"), out


def test_review_r2b_a_twice_encoded_short_email_is_masked() -> None:
    twice = base64.b64encode(base64.b64encode(b"a@b.co")).decode()
    assert len(twice) < 24
    out = bs.scrub_text(f"contact {twice} ok")
    assert twice not in out, out
    seen = [out]
    for _ in range(2):
        seen += [
            base64.b64decode(run + "=" * (-len(run) % 4), validate=False).decode("utf-8", "ignore")
            for run in re.findall(r"[A-Za-z0-9+/]{8,}={0,2}", seen[-1])
        ]
    assert "a@b.co" not in "\n".join(seen), seen


@pytest.mark.parametrize("tail", ["1234", "1234-5", "56789", "98765.4"])
@pytest.mark.parametrize("gap", [" ", "  ", "\t"])
def test_review_r3b_a_numeric_group_after_a_spaced_short_number_is_masked(gap: str, tail: str) -> None:
    out = bs.scrub_text(f"RA 0042{gap}{tail} ok")
    assert "0042" not in out and tail not in out, out


def test_review_r3c_a_count_after_a_spaced_short_number_stays() -> None:
    assert bs.scrub_text("RA 0042 2 visits") == "[screening-no] 2 visits"


@pytest.mark.parametrize("at", ["before", "after"])
def test_review_r4b_one_invalid_utf8_byte_does_not_hide_a_quoted_printable_label(at: str) -> None:
    label = quopri.encodestring("患者氏名".encode()).decode()
    bad = "=FF"
    out = bs.scrub_text(f"{bad + label if at == 'before' else label + bad}: Testo Hanako\n")
    assert "Testo" not in out and "Hanako" not in out, out
