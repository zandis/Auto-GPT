"""RC13-F (D-852): REDCap 13 is a supported version (the owner's ruling D-524: 13.7 is the hospital's production
version).

The evidence is the owner's REDCap 13.7.23, installed privately and offline (D-521; synthetic projects only): the
conformance tests R1 to R9 pass on it with the instance tool's fixes (D-850), and the client's ICD-04 calls (version,
project, metadata, events, form-event mapping, data access groups, the record export and the export since a time)
all answer. 12 and earlier stay refused."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from rc_bridge.client import SUPPORTED_MAJORS, RcError, RedcapClient
from rc_sim.app import create_app

from tests.rc_kit import TOKEN_A


def _client(version: str) -> RedcapClient:
    rc = RedcapClient("https://rc.example", TOKEN_A, http=TestClient(create_app(version=version), base_url="http://rc"))
    rc.url = "/api/"
    return rc


@pytest.mark.parametrize("version", ["13.7.23", "13.0.0", "14.5.0", "17.3.15"])
def test_redcap_13_to_17_are_supported(version: str) -> None:
    assert _client(version).check_version() == version


@pytest.mark.parametrize("version", ["12.4.1", "18.0.1"])
def test_12_and_18_are_still_refused(version: str) -> None:
    with pytest.raises(RcError) as e:
        _client(version).check_version()
    assert e.value.code == "RC-VERSION"


def test_the_supported_majors_are_13_to_17() -> None:
    assert SUPPORTED_MAJORS == (13, 14, 15, 16, 17)
