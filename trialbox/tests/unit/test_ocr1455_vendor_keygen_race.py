"""OCR #1455 (1455-6): a vendor key that appears after the command's check is never replaced without --force."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import sign_bundle

pytestmark = pytest.mark.nodb


def test_a_key_made_between_the_check_and_the_write_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "vendor"
    first: list[bytes] = []

    def check_then_other_keygen(o: Path) -> None:  # the check passes, then a second keygen puts its pair in place
        assert not (o / "vendor_ed25519.key").exists()
        sign_bundle.keygen(o)
        first.append((o / "vendor_ed25519.key").read_bytes())

    monkeypatch.setattr(sign_bundle, "refuse_existing", check_then_other_keygen)
    assert sign_bundle.main(["keygen", "--out", str(out)]) == 1
    assert (out / "vendor_ed25519.key").read_bytes() == first[0]  # the key the other run made is still there
    assert not list(out.glob(".*.tmp"))
