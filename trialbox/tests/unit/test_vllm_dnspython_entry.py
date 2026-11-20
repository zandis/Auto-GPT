"""The owner's yes of 2026-11-15, typed in lane D's session, on CVE-2026-128089 (dnspython 2.9.0) in the vLLM image: one dated entry, in the
form of the other vLLM entries, review 2026-12-10, saying where the flaw is (zone-file text parsing, which the model
server never runs), why no fixed image is pinned yet, and that it waits for a patched vLLM tag."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def _doc() -> dict[str, list[dict[str, object]]]:
    doc: dict[str, list[dict[str, object]]] = yaml.safe_load(
        (ROOT / "deploy" / "supply-chain-allowlist.yaml").read_text(encoding="utf-8")
    )
    return doc


def _entries() -> list[dict[str, object]]:
    return [e for e in _doc()["vulnerabilities"] if e.get("id") == "CVE-2026-128089"]


def test_there_is_one_dated_entry_for_the_vllm_image_and_its_package() -> None:
    got = _entries()
    assert len(got) == 1
    e = got[0]
    assert (e["package"], e["image"]) == ("dnspython", "vllm/vllm-openai")
    assert e["review_by"] == dt.date(2027, 1, 10)  # with the other vLLM entries
    assert e["owner"] == "Chang-Fu Kuo (the owner, D-1067)"
    assert e["date"] == dt.date(2026, 11, 15)  # the owner's yes (D-790)


def test_the_reason_says_where_the_flaw_is_and_what_removes_the_entry() -> None:
    reason = str(_entries()[0]["reason"])
    assert "2.9.2" in reason  # the fixed version
    assert "zone-file" in reason and "from_text" in reason  # the one code path the advisory names
    assert "never" in reason  # the model server does not run it
    assert "waits for a patched vLLM tag pinned by digest" in reason  # what removes it
    assert "no egress" in reason


def test_no_entry_covers_every_finding_of_the_model_server() -> None:
    """No entry of any id for any package of the image (a package-wide one, such as the kernel headers', stays)."""
    wide = [
        e
        for e in _doc()["vulnerabilities"]
        if e.get("image") == "vllm/vllm-openai" and e.get("id") == "*" and e.get("package") in (None, "*", "")
    ]
    assert wide == []


def test_the_known_findings_page_names_the_entry_in_the_vllm_row() -> None:
    page = (ROOT / "deploy" / "security" / "known-image-findings.md").read_text(encoding="utf-8")
    row = next(ln for ln in page.splitlines() if ln.startswith("| vllm/vllm-openai |"))
    assert "CVE-2026-128089" in row and "dnspython" in row and "2027-01-10" in row
