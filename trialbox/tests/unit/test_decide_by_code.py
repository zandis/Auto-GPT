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
#: a decision by the words of ``detail`` / ``reason``
BY_WORDS = [
    '    if "timeout" in exc.detail:\n        pass\n',
    '    if "busy" not in exc.reason:\n        pass\n',
    '    too_many = "too many fields" in str(exc.detail).lower()\n    code = 413 if too_many else 400\n',
    '    if exc.detail.startswith("Too many"):\n        pass\n',
    '    if re.search("fields", exc.detail):\n        pass\n',
    '    if exc.reason.lower() == "busy":\n        pass\n',
    '    if exc.reason.split()[0] == "busy":\n        pass\n',
    '    if exc.detail == "Too many fields":\n        pass\n',
    '    if exc.reason in ("model busy", "model down"):\n        pass\n',
    '    words = exc.detail\n    if "busy" in words:\n        pass\n',
    '    low = str(getattr(exc, "detail", "")).lower()\n    if "busy" in low:\n        pass\n',
    '    if exc.detail[:8] == "Too many":\n        pass\n',
    '    if missing(exc.detail, "t"):\n        pass\n',
]
#: a decision by a code or a typed field, and a display of the words: the shapes of the places read (F-4)
BY_CODE = [
    # libs/tb_common/llm.py: the registry's and the gateway's stable refusal codes
    '    if exc.reason == "prompt_too_long":\n        pass\n',
    "    kind = Unqualified if exc.reason == 'prompt_unqualified' else Error\n",
    "    if exc.reason in MODEL_FAULTS:\n        pass\n",
    # services/gateway/core.py: the refusal's code looked up
    "    if exc.reason in RETRY_AFTER:\n        pass\n",
    # services/console/backend.py: the orchestrator's refusal parsed and shown
    "    try:\n        detail = json.loads(exc.detail).get('detail')\n"
    "        detail = str(detail.get('message') if isinstance(detail, dict) else detail)\n"
    "    except ValueError:\n        detail = exc.detail\n    raise Refused(detail) from exc\n",
    # services/console/dataops_page.py: the refusal's typed fields
    "    detail = parse(exc.detail)\n    if exc.status == 409:\n        raise Refused(str(detail.get('why') or 'state'))\n",
    # services/console/site_pages.py: one typed field of the refusal, shown
    "    col = str(exc.detail.get('column') or '')[:80]\n",
    # services/adapter/sources/ssmix2/hl7.py: the error's type picks the phrase
    "    reason = exc.code if isinstance(exc, Unread) else 'a character outside the code tables'\n",
    "    if exc.detail and exc.reason is not None:\n        pass\n",
    "    if exc.reason != 'upstream_failed':\n        pass\n",
]


def _scan(tmp_path: Path, bodies: list[str], prefix: str) -> list[str]:
    head = "try:\n    pass\nexcept Exception as exc:\n"
    for i, body in enumerate(bodies):
        (tmp_path / f"{prefix}{i:02d}.py").write_text(head + body, encoding="utf-8")
    return sorted({f.split(":")[0] for f in decisions_by_text(tmp_path)})


def test_the_decision_scan_sees_a_search_of_detail_or_reason(tmp_path: Path) -> None:
    assert _scan(tmp_path, BY_WORDS, "w") == [f"w{i:02d}.py" for i in range(len(BY_WORDS))]


def test_the_decision_scan_leaves_a_code_a_typed_field_and_a_display_alone(tmp_path: Path) -> None:
    for body in BY_CODE:
        ast.parse("try:\n    pass\nexcept Exception as exc:\n" + body)  # each shape is Python
    assert _scan(tmp_path, BY_CODE, "c") == []


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


# ------------------------------------------------------------------------------ the suppression check (F-4)
@pytest.mark.parametrize("comment", ["# noqa", "# ruff: noqa", "# NOQA", "# Ruff: NoQA", "# flake8: noqa", "#noqa"])
def test_a_noqa_with_no_code_is_counted_as_all(comment: str) -> None:
    """A ``noqa`` that names no code hides the security rules too: it needs its ledger line like a bare ``nosec``."""
    assert [(s.line, s.rule) for s in IS.suppressions_in(f"q = 1  {comment}\n", "e.py")] == [(1, "all")]


@pytest.mark.parametrize("comment", ["# noqa: E501", "# noqa:E501,W291", "#: every ``noqa`` comment disregarded"])
def test_a_noqa_with_codes_or_words_about_noqa_is_not_all(comment: str) -> None:
    assert IS.suppressions_in(f"q = 1  {comment}\n", "e.py") == []


def test_the_ncbi_prompts_hide_no_rule_wholesale() -> None:
    """registry_match/prompts.py is NCBI's code verbatim; it names the style rules it breaks (pyproject.toml), and
    the security rules read it as any other file."""
    import tomllib

    prompts = "services/matching/registry_match/prompts.py"
    assert IS.suppressions_in((ROOT / prompts).read_text(encoding="utf-8"), prompts) == []
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignored = config["tool"]["ruff"]["lint"]["per-file-ignores"][prompts]
    assert ignored and not [c for c in ignored if c.startswith(("S", "B6", "B3"))]
