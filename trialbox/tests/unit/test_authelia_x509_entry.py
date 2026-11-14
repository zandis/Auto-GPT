"""The owner's ruling of 2026-11-13 on CVE-2026-111943 (crypto/x509) in the Authelia image: one dated entry, for
the image at the digest the lock pins, review 2026-12-10, saying what it takes to reach the flaw as the box runs
the image; and the real fix as a card (the identity overlay mounts only the hospital's directory CA), after which
the entry goes. The entry names the digest: a new pin fails this test, and the entry is looked at again."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def _entries() -> list[dict[str, object]]:
    doc = yaml.safe_load((ROOT / "deploy" / "supply-chain-allowlist.yaml").read_text(encoding="utf-8"))
    return [
        e for e in doc["vulnerabilities"] if e.get("id") == "CVE-2026-111943" and e.get("image") == "authelia/authelia"
    ]


def test_there_is_one_dated_entry_for_the_pinned_image() -> None:
    got = _entries()
    assert len(got) == 1
    e = got[0]
    assert e["package"] == "stdlib"
    assert e["review_by"] == dt.date(2026, 12, 10)
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    digest = lock["third_party"]["authelia"]["digest"]
    assert digest.startswith("sha256:") and digest in str(e["reason"])  # this image, not whatever is pinned next


def test_the_reason_says_what_it_takes_and_what_removes_the_entry() -> None:
    reason = str(_entries()[0]["reason"])
    assert "LDAPS" in reason and "directory" in reason  # the one connection the flaw could matter on
    assert "inside the hospital's network" in reason  # where an attacker would have to be
    assert "owner" in reason and "2026-11-13" in reason  # whose decision, and when
    assert "only the hospital's" in reason and "remove" in reason  # the real fix, and that this entry then goes


def test_no_entry_covers_every_finding_of_the_login_front() -> None:
    doc = yaml.safe_load((ROOT / "deploy" / "supply-chain-allowlist.yaml").read_text(encoding="utf-8"))
    wide = [e for e in doc["vulnerabilities"] if e.get("image") == "authelia/authelia" and e.get("id") == "*"]
    assert wide == []
