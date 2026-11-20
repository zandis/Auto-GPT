"""Card 10G-8 (D-1339): every vulnerability waiver of the allow-list has an owner, a date and a reason, and with a
release date is not past its review_by on it; ``python -m tools.vex write`` turns the waivers into one deterministic
CycloneDX VEX document per release."""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import vex

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "vex"

pytestmark = pytest.mark.nodb


def _fixture() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((FIX / "allowlist.yaml").read_text(encoding="utf-8"))
    return data


def _planted(**change: object) -> dict[str, Any]:
    """The fixture with its first vulnerability waiver changed (a value of None removes the key)."""
    data = copy.deepcopy(_fixture())
    entry = data["vulnerabilities"][0]
    for key, value in change.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return data


def test_the_shipped_waivers_each_have_an_owner_a_date_and_a_reason() -> None:
    data = vex.load()
    assert vex.check(data, None) == []
    found = vex.waivers(data)
    assert len(found) == 63  # 62 vulnerability entries and 1 os_packages_unreadable on 2026-11-19
    assert all(str(raw["owner"]).strip() and raw["date"] for _, _, raw in found)


@pytest.mark.parametrize("owner", ["A. Person (the owner, D-1)", "security owner (D-9999)", "lane H"])
def test_the_owner_is_any_named_holder_its_form_is_not_ruled_on_here(owner: str) -> None:
    assert vex.check(_planted(owner=owner), dt.date(2099, 1, 31)) == []


def test_the_fixture_passes_on_its_release_date() -> None:
    assert vex.check(_fixture(), dt.date(2099, 1, 31)) == []


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"owner": None}, "no owner"),
        ({"owner": "  "}, "no owner"),
        ({"owner": ""}, "no owner"),
        ({"date": None}, "no date"),
        ({"date": "soon"}, "no date"),
        ({"reason": None}, "no reason"),
        ({"review_by": None}, "no review_by"),
        ({"review_by": "2099-13-01"}, "no review_by"),
        ({"date": "2099-04-01"}, "is after its review_by"),
    ],
)
def test_a_planted_waiver_fails(change: dict[str, object], says: str) -> None:
    errors = vex.check(_planted(**change), dt.date(2099, 1, 31))
    assert len(errors) == 1 and says in errors[0] and "CVE-2099-0001" in errors[0]


def test_an_os_packages_unreadable_waiver_without_an_owner_fails() -> None:
    data = copy.deepcopy(_fixture())
    del data["os_packages_unreadable"][0]["owner"]
    errors = vex.check(data, dt.date(2099, 1, 31))
    assert errors == [errors[0]] and errors[0].startswith("os_packages_unreadable[0] (example/login): no owner")


def test_a_waiver_past_its_review_by_on_the_release_date_fails_and_on_the_day_passes() -> None:
    assert vex.check(_fixture(), dt.date(2099, 2, 1)) == []  # GHSA-aaaa-bbbb-cccc's review_by is the release day
    errors = vex.check(_fixture(), dt.date(2099, 2, 2))
    assert len(errors) == 1 and "GHSA-aaaa-bbbb-cccc" in errors[0] and "before the release date 2099-02-02" in errors[0]


def test_without_a_release_date_no_calendar_day_fails_the_check(capsys: pytest.CaptureFixture[str]) -> None:
    """lint and CI run ``check`` with no date: a waiver past review fails allowlist-check and ``write``, not lint."""
    assert vex.check(_fixture(), None) == []
    fixture = str(FIX / "allowlist.yaml")
    assert vex.main(["check", "--allowlist", fixture]) == 0  # every review_by of the fixture is 2099
    assert vex.main(["check", "--allowlist", fixture, "--release-date", "2099-02-02"]) == 1
    assert "before the release date 2099-02-02" in capsys.readouterr().err


def test_the_licence_entries_are_no_waiver_here() -> None:
    data = _fixture()
    data["licences"][0]["owner"] = ""
    assert vex.check(data, None) == []


def test_check_exits_1_on_a_waiver_without_an_owner(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "allowlist.yaml"
    bad.write_text(yaml.safe_dump(_planted(owner=None)), encoding="utf-8")
    assert vex.main(["check", "--allowlist", str(bad)]) == 1
    assert "no owner" in capsys.readouterr().err
    assert vex.main(["check", "--allowlist", str(FIX / "allowlist.yaml"), "--release-date", "2099-01-31"]) == 0


def _write(tmp_path: Path, name: str, allowlist: Path = FIX / "allowlist.yaml") -> tuple[int, Path]:
    out = tmp_path / name / "trialbox-vex.cdx.json"
    rc = vex.main(
        [
            "write",
            "--allowlist",
            str(allowlist),
            "--images-lock",
            str(FIX / "images.lock"),
            "--release-date",
            "2099-01-31",
            "--version",
            "9.9.9",
            "--out",
            str(out),
        ]
    )
    return rc, out


def test_write_gives_the_expected_bytes_every_time(tmp_path: Path) -> None:
    rc1, one = _write(tmp_path, "a")
    rc2, two = _write(tmp_path, "b")
    assert rc1 == rc2 == 0
    assert one.read_bytes() == two.read_bytes() == (FIX / "expected.cdx.json").read_bytes()


def test_write_refuses_when_a_waiver_fails(tmp_path: Path) -> None:
    bad = tmp_path / "allowlist.yaml"
    bad.write_text(yaml.safe_dump(_planted(date=None)), encoding="utf-8")
    rc, out = _write(tmp_path, "c", bad)
    assert rc == 1 and not out.exists()


def test_the_status_comes_from_the_reason_and_every_waiver_is_a_record() -> None:
    doc = json.loads((FIX / "expected.cdx.json").read_text(encoding="utf-8"))
    assert (doc["bomFormat"], doc["specVersion"], doc["metadata"]["timestamp"]) == (
        "CycloneDX",
        "1.6",
        "2099-01-31T00:00:00Z",
    )
    by_id = {v["id"]: v for v in doc["vulnerabilities"]}
    assert set(by_id) == {"CVE-2099-0001", "CVE-2099-0002", "GHSA-aaaa-bbbb-cccc", "*"}
    reach = by_id["CVE-2099-0002"]["analysis"]
    assert (reach["state"], reach["justification"]) == ("not_affected", "code_not_reachable")
    for vid in ("CVE-2099-0001", "GHSA-aaaa-bbbb-cccc", "*"):
        a = by_id[vid]["analysis"]
        assert (a["state"], a["response"], "justification" in a) == ("exploitable", ["update"], False)
    assert "every finding of linux-libc-dev" in by_id["*"]["description"]
    lock = by_id["GHSA-aaaa-bbbb-cccc"]
    assert lock["affects"] == [{"ref": "subject:requirements.lock#examplepkg"}]
    assert {p["name"]: p["value"] for p in lock["properties"]} == {
        "trialbox:owner": "release owner",
        "trialbox:waiver-date": "2099-01-04",
        "trialbox:review-by": "2099-02-01",
    }
    refs = {c["bom-ref"] for c in doc["components"]} | {
        s["bom-ref"] for c in doc["components"] for s in c.get("components", [])
    }
    assert all(v["affects"][0]["ref"] in refs for v in doc["vulnerabilities"])
    upstream = next(c for c in doc["components"] if c["name"] == "example/upstream")
    assert upstream["version"] == "sha256:" + "1" * 64  # the digest the lock pins
    assert "examplelib" not in json.dumps(doc)  # the licence entry is not in the VEX


def test_the_shipped_allowlist_gives_one_record_per_vulnerability_waiver() -> None:
    data = vex.load()
    doc = vex.build(data, version="1.0.0", release_date=dt.date(2026, 11, 19), digests={})
    assert len(doc["vulnerabilities"]) == len(data["vulnerabilities"]) == 62
    assert len({v["bom-ref"] for v in doc["vulnerabilities"]}) == 62
    not_affected = [v for v in doc["vulnerabilities"] if v["analysis"]["state"] == "not_affected"]
    assert all(v["analysis"]["detail"].startswith("Not reachable:") for v in not_affected)
    assert vex.dumps(doc) == vex.dumps(vex.build(data, version="1.0.0", release_date=dt.date(2026, 11, 19), digests={}))
