"""Linked-table disclosure control for DL-1 (spec v4 §12.2.3, RPT-05 … RPT-07).

RPT-07 asks for a Hypothesis property test; Hypothesis is not installed in this environment, so the property is
checked over a seeded random sample of funnels (same property, fixed examples)."""

from __future__ import annotations

import random

import pytest
from deliverables.disclosure import (
    INTERNAL,
    ORDER,
    SPONSOR,
    DisclosureError,
    DisclosureTrace,
    Profile,
    complementary,
    funnel_recovery,
    interval_of,
    pct,
    profile_for,
    rate_publishable,
    release,
    released_ok,
    require_complete,
    round_base,
)


@pytest.mark.req("RPT-05")
def test_profile_follows_recipient_class() -> None:
    assert profile_for("external_sponsor") is SPONSOR
    assert profile_for("internal") is INTERNAL
    assert (SPONSOR.k, SPONSOR.base, INTERNAL.k, INTERNAL.base) == (11, 5, 5, 5)
    with pytest.raises(DisclosureError):
        profile_for("press")


@pytest.mark.req("RPT-05", "RPT-06")
def test_primary_suppression_and_rounding() -> None:
    assert [release(n, SPONSOR) for n in (0, 1, 10, 11, 12, 13, 17, 18, 102)] == [
        0,
        "<11",
        "<11",
        10,
        10,
        15,
        15,
        20,
        100,
    ]
    assert [release(n, INTERNAL) for n in (0, 4, 5, 7, 8)] == [0, "<5", 5, 5, 10]
    assert round_base(12, 5) == 10 and round_base(13, 5) == 15  # half up on Decimal
    with pytest.raises(DisclosureError):
        release(-1, SPONSOR)
    assert all(released_ok(release(n, SPONSOR), SPONSOR) for n in range(500))


@pytest.mark.req("RPT-06")
def test_rates_only_when_every_part_is_zero_or_at_least_k() -> None:
    assert rate_publishable(20, 40, 11) and pct(20, 40, SPONSOR) == 50.0
    assert not rate_publishable(35, 40, 11) and pct(35, 40, SPONSOR) is None  # complement 5 < k
    assert pct(0, 40, SPONSOR) == 0.0
    assert pct(0, 0, SPONSOR) is None


@pytest.mark.req("RPT-06")
def test_trace_order_enforced_and_renderers_refuse_incomplete() -> None:
    tr = DisclosureTrace(SPONSOR.name, SPONSOR.version)
    with pytest.raises(DisclosureError):
        tr.add("independent_rounding")
    for step in ORDER[:-1]:
        tr.add(step)
    assert not tr.complete
    with pytest.raises(DisclosureError):
        require_complete(tr.to_dict())
    tr.add(ORDER[-1])
    assert tr.complete
    require_complete(tr.to_dict())


def _random_funnel(rng: random.Random) -> tuple[list[int], list[int]]:
    n = rng.randint(2, 16)
    rem = [rng.choice([rng.randint(0, 30), rng.randint(0, 3000)])]
    drop = [0]
    for _ in range(1, n):
        d = min(rem[-1], rng.choice([0, rng.randint(0, 12), rng.randint(0, max(1, rem[-1]))]))
        drop.append(d)
        rem.append(rem[-1] - d)
    return rem, drop


@pytest.mark.req("RPT-07")
@pytest.mark.parametrize("p", [SPONSOR, INTERNAL], ids=lambda p: p.name)
def test_no_suppressed_cell_recoverable_after_complementary_suppression(p: Profile) -> None:
    rng = random.Random(20261025)
    seen_complementary = 0
    for _ in range(400):
        rem, drop = _random_funnel(rng)
        rel_r = [release(v, p) for v in rem]
        rel_d = [release(v, p) for v in drop]
        out_r, out_d, added = complementary(rel_r, rel_d, p)
        seen_complementary += bool(added)
        assert funnel_recovery(out_r, out_d, p) == []
        # every released value still brackets the exact value (rounding never lies)
        for released, exact in [*zip(out_r, rem, strict=True), *zip(out_d[1:], drop[1:], strict=True)]:
            lo, hi = interval_of(released, p)
            assert lo <= exact <= hi or (released == 0 and exact == 0)
    assert seen_complementary > 0  # the generator does produce linked leaks that need step 4
