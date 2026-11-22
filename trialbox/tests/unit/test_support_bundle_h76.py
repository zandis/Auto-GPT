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
    out = [text, bs._decode(text), bs._decode(text.replace("=\n", ""))]
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
SPLITS = ["=\n", "%E2%80%8B", "%e2%80%8b", "&shy;", "\u200b", "­", "⁠", "﻿", "&#8203;", "\\u200b"]


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
    ("run_cmd", "subprocess.run"),  # the commands of the bundle; their output goes through the scrub
    ("last_look", "ds.run"),  # tools.data_scan.run: the last look reads the archive, it starts nothing
}


def _spawns(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[tuple[str, str]] = set()

    def visit(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else fn
            if isinstance(child, ast.Call):
                f = child.func
                last = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                if last in SPAWN:
                    out.add((fn, ast.unparse(f)))
            visit(child, name)

    visit(tree, "<module>")
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
