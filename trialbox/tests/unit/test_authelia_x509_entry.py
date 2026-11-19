"""CVE-2026-111943 (crypto/x509) in the Authelia image. The owner's ruling of 2026-11-13 accepted it for the image at
the digest the lock pins, until the real fix (D-722: the identity overlay gives Authelia only the hospital's
directory CA). With D-722 on master, the owner's yes of 2026-11-15 (D-820) replaces the acceptance by one "Not
reachable" entry, as the image's other entries are: same digest, review 2026-12-10, its reason the fact D-722 makes
true. The entry names the digest: a new pin fails this test, and the entry is looked at again."""

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
    assert e["review_by"] == dt.date(2027, 1, 10)
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    digest = lock["third_party"]["authelia"]["digest"]
    assert digest.startswith("sha256:") and digest in str(e["reason"])  # this image, not whatever is pinned next


def test_the_reason_is_the_fact_d722_makes_true_and_its_limit() -> None:
    """D-820: no longer the owner's acceptance; why the flaw cannot be reached, and when that holds."""
    reason = str(_entries()[0]["reason"])
    assert reason.startswith("Not reachable:") and "Accepted by the owner" not in reason
    assert "LDAPS" in reason and "directory" in reason  # the one connection the flaw could matter on
    assert "hospital's directory CA only" in reason and "TB_LDAP_CA" in reason and "D-722" in reason  # the fix
    assert "does not start without a usable file" in reason  # where the guarantee comes from (D-722 point 3)
    assert e_owner() == "security owner (D-1067)"  # a role, never a person (D-1339)
    assert str(_entries()[0]["date"]) == "2026-11-15"  # the owner's yes of D-820


def e_owner() -> str:
    return str(_entries()[0]["owner"])


def test_the_authelia_entry_stands_on_its_own() -> None:
    """Until SC-1b the db image carried the same id in its gosu binary, under an entry of its own. D-993 deleted that
    binary and its entries went with it: the Authelia entry is now the only one of this id, scoped to its image, and
    its reason does not lean on another image's entry."""
    doc = yaml.safe_load((ROOT / "deploy" / "supply-chain-allowlist.yaml").read_text(encoding="utf-8"))
    same_id = [e for e in doc["vulnerabilities"] if e.get("id") == "CVE-2026-111943"]
    assert [e.get("image") for e in same_id] == ["authelia/authelia"]
    assert "gosu" not in str(same_id[0]["reason"]) and "trialbox-postgres" not in str(same_id[0]["reason"])


def test_no_entry_covers_every_finding_of_the_login_front() -> None:
    doc = yaml.safe_load((ROOT / "deploy" / "supply-chain-allowlist.yaml").read_text(encoding="utf-8"))
    wide = [e for e in doc["vulnerabilities"] if e.get("image") == "authelia/authelia" and e.get("id") == "*"]
    assert wide == []
