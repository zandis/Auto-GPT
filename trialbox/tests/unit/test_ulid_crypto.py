from __future__ import annotations

from pathlib import Path

import pytest
from tb_common.crypto import (
    aes_decrypt,
    aes_encrypt,
    ed25519_generate,
    ed25519_sign,
    ed25519_verify,
    load_or_create_key,
    pid_for_mrn,
    sha256_bytes,
)
from tb_common.smallcell import suppress
from tb_common.timeutil import month_ends, quarter_of
from tb_common.ulid import is_ulid, new_ulid, ulid_timestamp_ms


def test_ulid_monotonic_and_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    import tb_common.ulid as u

    monkeypatch.setattr(u, "_last_ms", -1)  # independent of ULIDs other tests created in this process
    monkeypatch.setattr(u, "_last_rand", 0)
    ids = [new_ulid(now_ms=1_700_000_000_000) for _ in range(1000)]
    assert all(is_ulid(i) for i in ids)
    assert ids == sorted(ids) and len(set(ids)) == 1000
    assert ulid_timestamp_ms(ids[0]) == 1_700_000_000_000


def test_pid_is_stable_and_keyed() -> None:
    k1, k2 = b"k" * 32, b"j" * 32
    assert pid_for_mrn(k1, "12345678") == pid_for_mrn(k1, " 12345678 ")
    assert pid_for_mrn(k1, "12345678") != pid_for_mrn(k2, "12345678")
    assert len(pid_for_mrn(k1, "1")) == 32
    with pytest.raises(ValueError):
        pid_for_mrn(b"short", "1")


def test_aes_roundtrip_and_key_file(tmp_path: Path) -> None:
    key = load_or_create_key(tmp_path / "k.key")
    assert (tmp_path / "k.key").stat().st_mode & 0o777 == 0o600
    assert load_or_create_key(tmp_path / "k.key") == key
    blob = aes_encrypt(key, b"12345678", b"pid")
    assert aes_decrypt(key, blob, b"pid") == b"12345678"


def test_ed25519() -> None:
    priv, pub = ed25519_generate()
    sig = ed25519_sign(priv, b"bundle")
    assert ed25519_verify(pub, b"bundle", sig)
    assert not ed25519_verify(pub, b"bundle!", sig)


def test_sha256() -> None:
    assert sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_small_cell() -> None:
    assert suppress(0) == 0 and suppress(4) == "<5" and suppress(5) == 5 and suppress(2, 3) == "<3"


def test_month_ends_and_quarters() -> None:
    from datetime import date

    me = month_ends(date(2026, 10, 5), 3)
    assert me == [date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)]
    assert quarter_of(date(2026, 10, 5)) == "2026Q4"
