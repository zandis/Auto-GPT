"""F-4 (#639, 7078734731): a decision is made by a type or a code, never by an error's words.

The ratchet card (#1337, R22-14) left four tightenings out because they turned code red: a ``noqa`` that names no
code (``registry_match/prompts.py``), ``detail`` and ``reason`` in the decision scan, and ``reason`` across services.
The code is fixed and the scans take them. Each place was read first: a decision by the words is changed, a decision
by a code and a display of the words are left as they are, and the scan tells them apart by its structure. Synthetic
data only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.unit.test_error_text_across_services import _found
from tests.unit.test_no_decision_by_error_text import decisions_by_text
from tools import inline_suppressions as IS

pytestmark = [pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
VALUE = "A1234567"  # a synthetic chart number


# ------------------------------------------------------------------------------------- the decision scan (F-4)
#: a decision by the words of ``detail`` / ``reason``: round 1's shapes, then the review's (round 2)
BY_WORDS = {
    "a_sentence_with_no_space": '    if exc.detail == "フォームの項目が多すぎます":\n        pass\n',
    "in": '    if "timeout" in exc.detail:\n        pass\n',
    "not_in": '    if "busy" not in exc.reason:\n        pass\n',
    "assigned_search": '    too_many = "too many fields" in str(exc.detail).lower()\n    code = 413 if too_many else 400\n',
    "startswith": '    if exc.detail.startswith("Too many"):\n        pass\n',
    "regex": '    if re.search("fields", exc.detail):\n        pass\n',
    "regex_assigned": '    found = re.search("busy", exc.reason)\n    if found:\n        pass\n',
    "split_part": '    if exc.reason.split()[0] == "busy":\n        pass\n',
    "eq_sentence": '    if exc.detail == "Too many fields":\n        pass\n',
    "in_sentences": '    if exc.reason in ("model busy", "model down"):\n        pass\n',
    "alias_of_words": '    words = exc.detail\n    if "busy" in words:\n        pass\n',
    "getattr_folded": '    low = str(getattr(exc, "detail", "")).lower()\n    if "busy" in low:\n        pass\n',
    "slice": '    if exc.detail[:8] == "Too many":\n        pass\n',
    "helper": '    if missing(exc.detail, "t"):\n        pass\n',
    # round 2 (the review): a match on the words
    "match": '    match exc.detail:\n        case "Too many fields":\n            pass\n',
    "match_lower": '    match exc.detail.lower():\n        case "too many fields":\n            pass\n',
    # compared with a name the module binds to a sentence, or to a collection of them
    "eq_module_text": 'TOO_MANY = "Too many fields"\ntry:\n    pass\nexcept Exception as exc:\n'
    "    if exc.detail == TOO_MANY:\n        pass\n",
    "ne_module_text": 'TOO_MANY = "Too many fields"\ntry:\n    pass\nexcept Exception as exc:\n'
    "    if exc.detail != TOO_MANY:\n        pass\n",
    "in_module_texts": 'REFUSALS = {"Too many fields", "Part too large"}\ntry:\n    pass\nexcept Exception as exc:\n'
    "    if exc.detail in REFUSALS:\n        pass\n",
    "eq_local_text": '    s = "too many fields"\n    if exc.detail == s:\n        pass\n',
    # a lookup in a mapping keyed by sentences
    "dict_get": '    code = {"Too many fields": 413}.get(exc.detail, 400)\n',
    "module_map_get": 'PAGES = {"too many fields": "size"}\ntry:\n    pass\nexcept Exception as exc:\n'
    "    page = PAGES.get(exc.detail.lower())\n",
    "module_map_index": 'PAGES = {"Too many fields": "size"}\ntry:\n    pass\nexcept Exception as exc:\n'
    "    page = PAGES[exc.detail]\n",
    # the words inside a longer text
    "percent": '    if "fields" in ("%s" % exc.detail):\n        pass\n',
    "format": '    if "fields" in "{}".format(exc.detail):\n        pass\n',
    "fstring": '    if "busy" in f"{exc.reason}":\n        pass\n',
    "concat": '    if "fields" in (exc.detail + ""):\n        pass\n',
    "encode": '    if b"fields" in exc.detail.encode():\n        pass\n',
    # the same error under another name or through what carries it
    "alias_of_error": '    e2 = exc\n    if "busy" in e2.detail:\n        pass\n',
    "cause": '    if "busy" in exc.__cause__.reason:\n        pass\n',
    "context": '    if "busy" in exc.__context__.detail:\n        pass\n',
    "vars": '    d = vars(exc)["detail"]\n    if "busy" in d:\n        pass\n',
    "dunder_dict": '    if "busy" in exc.__dict__["reason"]:\n        pass\n',
    "getattr": '    if getattr(exc, "detail").endswith("x"):\n        pass\n',
    # ordered
    "gt": '    if exc.detail.lower() > "too":\n        pass\n',
    "lt": '    if exc.reason < "m":\n        pass\n',
    # a helper: assigned and tested, not in the module, or in the module and searching
    "helper_assigned": "    t = too_many(exc.detail)\n    if t:\n        pass\n",
    "module_helper_searches": 'def too_many(s):\n    return "too many" in s.lower()\n\n\n'
    "try:\n    pass\nexcept Exception as exc:\n    if too_many(exc.detail):\n        pass\n",
}
#: a decision by a code or a typed field, and a display of the words: the shapes of the places read (F-4)
BY_CODE = {
    # libs/tb_common/llm.py: the registry's and the gateway's stable refusal codes
    "llm_eq_code": '    if exc.reason == "prompt_too_long":\n        pass\n',
    "llm_ifexp_code": "    kind = Unqualified if exc.reason == 'prompt_unqualified' else Error\n",
    "llm_in_imported_codes": "    if exc.reason in MODEL_FAULTS:\n        pass\n",
    # services/gateway/core.py: the refusal's code looked up
    "gateway_lookup": "    if exc.reason in RETRY_AFTER:\n        h = RETRY_AFTER[exc.reason]\n",
    # services/console/backend.py: the orchestrator's refusal parsed and shown
    "backend_parse": "    try:\n        detail = json.loads(exc.detail).get('detail')\n"
    "        detail = str(detail.get('message') if isinstance(detail, dict) else detail)\n"
    "    except ValueError:\n        detail = exc.detail\n    raise Refused(detail) from exc\n",
    # services/console/dataops_page.py: the refusal parsed by a helper of the module, then its typed fields
    "dataops_module_parse": "def _detail(text):\n    got = json.loads(text).get('detail')\n"
    "    return got if isinstance(got, dict) else {}\n\n\ntry:\n    pass\nexcept Exception as exc:\n"
    "    detail = _detail(exc.detail)\n    if exc.status == 409:\n        raise Refused(str(detail.get('why') or 'x'))\n",
    # services/console/site_pages.py: one typed field of the refusal, shown
    "site_typed_field": "    col = str(exc.detail.get('column') or '')[:80]\n",
    # services/adapter/sources/ssmix2/hl7.py: the error's type picks the phrase
    "hl7_by_type": "    reason = exc.code if isinstance(exc, Unread) else 'a character outside the code tables'\n",
    "present": "    if exc.detail and exc.reason is not None:\n        pass\n",
    "ne_code": "    if exc.reason != 'upstream_failed':\n        pass\n",
    "in_module_codes": 'FAULTS = {"model_busy", "model_down"}\ntry:\n    pass\nexcept Exception as exc:\n'
    "    if exc.reason in FAULTS:\n        pass\n",
    # round 2 (the review): no decision by the words
    "json_key": '    if json.loads(exc.detail).get("code") == "x":\n        pass\n',
    "empty": '    if exc.detail.strip() == "":\n        pass\n',
    "lower_eq_code": '    if exc.reason.lower() == "busy":\n        pass\n',
    "display_call": "    if flash(exc.detail):\n        pass\n",
    "module_helper_shows": "def shown(s):\n    return render('page', message=s)\n\n\n"
    "try:\n    pass\nexcept Exception as exc:\n    if shown(exc.detail):\n        pass\n",
    "log": '    log.warning("refused: %s", exc.detail)\n',
    "len": "    if len(exc.detail) > 80:\n        pass\n",
}

HEAD = "try:\n    pass\nexcept Exception as exc:\n"


def _flagged(tmp_path: Path, body: str) -> bool:
    src = HEAD + body if body.startswith("    ") else body  # a shape with its own module lines is whole
    ast.parse(src)  # each shape is Python
    (tmp_path / "shape.py").write_text(src, encoding="utf-8")
    return bool(decisions_by_text(tmp_path))


@pytest.mark.parametrize("shape", sorted(BY_WORDS))
def test_the_decision_scan_sees_a_decision_by_the_words(tmp_path: Path, shape: str) -> None:
    assert _flagged(tmp_path, BY_WORDS[shape])


@pytest.mark.parametrize("shape", sorted(BY_CODE))
def test_the_decision_scan_leaves_a_code_a_typed_field_and_a_display_alone(tmp_path: Path, shape: str) -> None:
    assert not _flagged(tmp_path, BY_CODE[shape])


def test_no_code_under_libs_or_services_decides_by_the_words_of_detail_or_reason() -> None:
    """The real tree: the only place that searched the words (the console's map form, D-768) decides by a count."""
    found = [f"{top}/{hit}" for top in ("libs", "services") for hit in decisions_by_text(ROOT / top)]
    assert not [f for f in found if f.startswith("services/console/edc_pages.py")], found


# --------------------------------------------------------------------------------- across services (F-4)
def test_a_general_errors_reason_put_into_an_answer_is_its_text(tmp_path: Path) -> None:
    head = "def f():\n    try:\n        run()\n    except ValueError as exc:\n"
    (tmp_path / "t.py").write_text(head + "        raise Unread(f'ISO-2022-JP: {exc.reason}') from exc\n", "utf-8")
    (tmp_path / "u.py").write_text(head + "        raise Unread(PHRASE[exc.code]) from exc\n", "utf-8")
    assert sorted(f for f, _ in _found(tmp_path)) == ["t.py"]


def test_a_codecs_reworded_reason_is_not_repeated(monkeypatch: pytest.MonkeyPatch) -> None:
    """hl7.py:282 (lane J's): a codec's refusal said its own words in the SS-MIX2 reader's error. The reader says its
    own phrase now, chosen by its refusal's code; any other codec error is a character outside the code tables."""
    from adapter.sources.ssmix2 import hl7

    def reworded(data: bytes) -> str:
        raise UnicodeDecodeError("cp932", data, 0, 1, f"illegal multibyte sequence near {VALUE}")

    monkeypatch.setattr(hl7, "_iso2022", reworded)
    with pytest.raises(hl7.Undecodable) as e:
        hl7.decode_bytes(b"MSH|^~\\&|\r\x1b$B\x29\x21\x1b(B\r")
    assert str(e.value) == "ISO-2022-JP: a character outside the code tables"


def test_the_readers_own_refusal_keeps_its_phrase_by_its_code() -> None:
    from adapter.sources.ssmix2 import hl7

    with pytest.raises(hl7.Undecodable) as e:
        hl7.decode_bytes(b"MSH|^~\\&|\r\x1b$B\x30\x21\r")  # a two-byte set left open at the segment's end
    assert str(e.value) == "ISO-2022-JP: an escape sequence left open at a segment end"


def test_a_set_left_open_at_the_end_of_the_data_says_so_by_its_code() -> None:
    """The end of the data with a set still open (no segment end after it) is the same refusal as at a segment's
    end: its code, and so its phrase, is ``left_open``."""
    from adapter.sources.ssmix2 import hl7

    with pytest.raises(hl7._Unread) as e:
        hl7._iso2022(b"MSH|^~\\&|\r\x1b$B\x30\x21")
    assert e.value.code == "left_open" and e.value.start == len(b"MSH|^~\\&|\r\x1b$B\x30\x21") - 1
    with pytest.raises(hl7.Undecodable) as u:
        hl7.decode_bytes(b"MSH|^~\\&|\r\x1b$B\x30\x21")
    assert str(u.value) == "ISO-2022-JP: an escape sequence left open at a segment end"


# ------------------------------------------------------------------------------ the suppression check (F-4)
#: comment -> whether ruff hides every rule on the line (checked against ruff itself below): a ``noqa`` with a colon
#: after it names codes, or is ignored by ruff when it names none it knows
NOQA_FORMS = {
    "# noqa": True, "# NOQA": True, "#noqa": True, "# noqa - a reason": True, "# x # noqa": True,
    "# noqa:": False, "# noqa: see below": False, "# noqa : x": False, "# noqa: XYZ": False, "# noqa:E501": False,
    "# noqa:,": False, "#: every ``noqa`` comment disregarded": False,
}  # fmt: skip
FILE_FORMS = {"# ruff: noqa": True, "# flake8: noqa": True, "# ruff : noqa": True, "# ruff: noqa:": False,
              "# ruff: noqa: E501": False}  # fmt: skip


@pytest.mark.parametrize("comment", sorted(NOQA_FORMS))
def test_a_noqa_that_hides_every_rule_is_counted_as_all(comment: str) -> None:
    """A ``noqa`` that hides every rule hides the security rules too: it needs its ledger line like a bare
    ``nosec``. One with a colon after it is not (ruff reads codes there, or nothing)."""
    got = [(s.line, s.rule) for s in IS.suppressions_in(f"q = 1  {comment}\n", "e.py")]
    assert got == ([(1, "all")] if NOQA_FORMS[comment] else [])


@pytest.mark.parametrize("comment", sorted(FILE_FORMS))
def test_a_file_level_noqa_that_hides_every_rule_is_counted_as_all(comment: str) -> None:
    got = [(s.line, s.rule) for s in IS.suppressions_in(f"{comment}\nq = 1\n", "e.py")]
    assert got == ([(1, "all")] if FILE_FORMS[comment] else [])


def test_the_forms_are_read_as_ruff_reads_them(tmp_path: Path) -> None:
    """The tables above are ruff's own reading: an unused import under each comment is reported exactly when the
    comment hides nothing."""
    import json
    import subprocess
    import sys

    files = {f"l{i:02d}.py": f"import os  {c}\n" for i, c in enumerate(sorted(NOQA_FORMS))}
    files |= {f"f{i:02d}.py": f"{c}\nimport os\n" for i, c in enumerate(sorted(FILE_FORMS))}
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F401",
                          "--output-format", "json", str(tmp_path)], capture_output=True, text=True, check=False,
                         timeout=120)  # fmt: skip
    reported = {Path(r["filename"]).name for r in json.loads(run.stdout)}
    hidden = {n for n in files if n not in reported}
    want = {f"l{i:02d}.py" for i, c in enumerate(sorted(NOQA_FORMS)) if NOQA_FORMS[c]}
    want |= {f"f{i:02d}.py" for i, c in enumerate(sorted(FILE_FORMS)) if FILE_FORMS[c]}
    assert hidden == want


def test_the_ncbi_prompts_hide_no_rule_wholesale() -> None:
    """registry_match/prompts.py is NCBI's code verbatim; it names the style rules it breaks (pyproject.toml), and
    the security rules read it as any other file."""
    import tomllib

    prompts = "services/matching/registry_match/prompts.py"
    assert IS.suppressions_in((ROOT / prompts).read_text(encoding="utf-8"), prompts) == []
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignored = config["tool"]["ruff"]["lint"]["per-file-ignores"][prompts]
    assert ignored and not [c for c in ignored if c.startswith(("S", "B6", "B3"))]
