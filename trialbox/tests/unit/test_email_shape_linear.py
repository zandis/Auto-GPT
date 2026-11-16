"""NEW-B-51 (D-759): the email shape is looked for around each "@" only, and finds the same addresses (synthetic
text only)."""

from __future__ import annotations

import random
import re
import time

from tb_common import phi_guard as pg

BEFORE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _texts() -> list[str]:
    rnd = random.Random(7)
    parts = ["ana.lee", "@", "hospa", ".test", ".", "x", "1234", " ", "\n", "mail:", "+tag", "%", "-", "_", "ex.com",
             "a@b", "@@", "..", "台北", "電子郵件", "Dr", "co.jp", "9"]  # fmt: skip
    return ["".join(rnd.choice(parts) for _ in range(rnd.randint(1, 60))) for _ in range(3000)]


def test_the_same_addresses_as_before() -> None:
    for t in _texts():
        assert [m.span() for m in pg.find_emails(t)] == [m.span() for m in BEFORE.finditer(t)], t


def test_a_long_run_is_read_in_one_pass() -> None:
    for t in ("1" * 30000, "a" * 30000 + "@", "x@" + "b" * 30000, "a." * 15000):
        start = time.monotonic()
        list(pg.find_emails(t))
        pg.mask_note(t)
        assert time.monotonic() - start < 0.5, t[:5]


def test_the_guard_reads_the_masker_s_search() -> None:
    from guard.guard import Guard

    address = "ana.lee" + "@" + "hospa.test"
    assert address not in Guard("^\\d{8}$").redact(f"mail {address} now") and address not in pg.mask_note(address)
