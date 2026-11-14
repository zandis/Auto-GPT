"""D-685 under the install's roles (D-378): a per-lake OMOP store (``omop_<hash>``) on a box with roles.

The real role script runs on a throwaway cluster. A service that opens a lake other than the box's own makes that
lake's OMOP store itself; there is no group role for it, so the store is the making service's alone. The opt-out
worker runs in the orchestrator: it finds the store in the catalog and cannot open it. What this file holds is
that the gap fails closed: the store is named, the tick is failed, the box's own store is still cleared, and
nothing says the patient is out of a store that still holds them. Synthetic pseudonyms only."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.db import Database
from tb_common.optout import OptOutRegister

from tests.unit.test_db_roles import _as, _run_script
from tests.unit.test_optout_worker import T0, A, Audit, B, Jobs, Lake, _batch, _live
from tools import pglocal

SITE_STORE = "omop_0123456789"  # made by the lake service: another service's
SPACE_STORE = "omop_abcdef0123"  # made by the orchestrator itself: a site set-up space's lake (lake.source = omop)


@pytest.fixture(scope="module")
def box() -> Iterator[str]:
    """Roles applied; the box's own OMOP store made by the admin (as the install does) and a practice lake's
    store made by the lake service, each holding A and B. Yields the admin's URL."""
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-pgomops-", dir=base))
    root.chmod(0o755)
    admin = pglocal.ensure(root)
    try:
        _run_script(root)
        OptOutRegister(admin).close()
        from omop import schema
        from omop.load import load_batch

        stores = ((admin, "omop"), (_as(admin, "tb_lake"), SITE_STORE), (_as(admin, "tb_orchestrator"), SPACE_STORE))
        for url, name in stores:
            with schema.connect(url, name) as db:
                load_batch(db, "feed", "2026-11-01", _batch([A, B]), tz="Asia/Taipei")
        yield admin
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def test_a_per_lake_store_belongs_to_the_service_that_made_it(box: str) -> None:
    """Why the worker cannot open it: no group role, so no other service may use the schema."""
    from omop import schema

    with Database.connect(_as(box, "tb_lake"), SITE_STORE) as db:
        assert db.fetchval("SELECT current_user") == "tb_lake"
        owner = db.fetchval("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = ?", (SITE_STORE,))
        assert owner == "tb_lake"
    for role in ("tb_orchestrator", "tb_adapter", "tb_console"):
        with pytest.raises(Exception, match="schema"):
            schema.connect(_as(box, role), SITE_STORE).close()


def test_the_worker_finds_the_store_names_it_and_still_clears_the_boxs_own(
    box: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore import optout_worker as w

    orch_url = _as(box, "tb_orchestrator")
    monkeypatch.setenv("TB_DB_URL", orch_url)
    # the catalog answers a role that may not use a store
    assert w.omop_store_names(orch_url) == ["omop", SITE_STORE, SPACE_STORE]
    reg = OptOutRegister(orch_url)
    reg.add(A, "office", "by letter", "office:t", T0)
    reg.close()
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=Audit(),
        services=SimpleNamespace(lake=Lake([])), db=Jobs(),
    )  # fmt: skip
    out = w.tick(orch)
    assert out is not None
    assert out["failed"] == ["omop"] and w.status()["failed"] == ["omop"]  # the health line is red
    assert out["not_opened"] == [SITE_STORE] and "omop" not in out["stores"]
    assert A not in str(out) and A not in str(orch.audit.events)
    with Database.connect(box, "omop") as own:
        assert _live(own, A) == 0  # the box's own store was cleared in the same tick
    with Database.connect(orch_url, SPACE_STORE) as space:
        # the one such store a box as shipped can hold (a site set-up space, made in the orchestrator's process):
        # the worker is its owner and clears it
        assert space.fetchval("SELECT current_user") == "tb_orchestrator" and _live(space, A) == 0
    with Database.connect(_as(box, "tb_lake"), SITE_STORE) as site:
        assert _live(site, A) > 0  # still there, and the tick said so


def test_the_admin_who_may_open_every_store_clears_both(box: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same tick as a role that may open the per-lake store (the admin is a member of every service role):
    the patient goes from both. It is the worker's side that is whole; the role model is what keeps the
    orchestrator out."""
    from datacore import optout_worker as w

    monkeypatch.setenv("TB_DB_URL", box)
    reg = OptOutRegister(box)
    reg.add(B, "office", "by letter", "office:t", T0)
    reg.close()
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=Audit(),
        services=SimpleNamespace(lake=Lake([])), db=Jobs(),
    )  # fmt: skip
    out = w.tick(orch)
    assert out is not None and out["failed"] == [], out
    assert out["stores"]["omop"]["stores"] == 3
    for url, name in ((box, "omop"), (_as(box, "tb_lake"), SITE_STORE), (box, SPACE_STORE)):
        with Database.connect(url, name) as db:
            assert _live(db, B) == 0, name
