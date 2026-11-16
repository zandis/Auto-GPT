"""D-685 under the install's roles (D-378): a per-lake OMOP store (``omop_<hash>``) on a box with roles.

The real role script runs on a throwaway cluster. D-721: a second lake's OMOP store is made by the admin's step
(``tools.trialbox.omop_store``) for the OMOP group ``tbs_omop``, so every service with ``omop`` on its list works in
it as the group. The opt-out worker runs in the orchestrator, which has ``omop``: it finds the store in the catalog,
opens it and clears it in the same tick as the box's own. (Before D-721 the lake service made such a store alone and
the worker failed closed on it; that gap is closed.) A site set-up space's store is the orchestrator's own and is
cleared too. Synthetic pseudonyms only."""

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

SITE_LAKE = Path("/srv/practice-a/lake")  # a name only: nothing is read from or written to it
SITE_STORE = __import__("omop.schema", fromlist=["schema_for"]).schema_for(SITE_LAKE)  # made by the admin (D-721)
SPACE_STORE = "omop_abcdef0123"  # made by the orchestrator itself: a site set-up space's lake (lake.source = omop)


@pytest.fixture(scope="module")
def box() -> Iterator[str]:
    """Roles applied; the box's own OMOP store made by the admin (as the install does), a practice lake's store made
    by the admin's step for the OMOP group and loaded by the lake service, and a site space's store made by the
    orchestrator, each holding A and B. Yields the admin's URL."""
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

        from tools.trialbox import omop_store

        assert omop_store.make(admin, SITE_LAKE) == SITE_STORE
        stores = ((admin, "omop"), (_as(admin, "tb_lake"), SITE_STORE), (_as(admin, "tb_orchestrator"), SPACE_STORE))
        for url, name in stores:
            with schema.connect(url, name, lake_dir=SITE_LAKE if name == SITE_STORE else None) as db:
                load_batch(db, "feed", "2026-11-01", _batch([A, B]), tz="Asia/Taipei")
        yield admin
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def test_a_per_lake_store_belongs_to_the_omop_group_and_every_omop_service_opens_it(box: str) -> None:
    """D-721: why the worker can open it: the store is the group's, and the orchestrator is in the group."""
    from omop import schema

    with Database.connect(box, "omop") as db:
        owner = db.fetchval("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = ?", (SITE_STORE,))
    assert owner == "tbs_omop"
    for role in ("tb_lake", "tb_adapter", "tb_orchestrator"):
        with schema.connect(_as(box, role), SITE_STORE, lake_dir=SITE_LAKE) as db:
            assert db.fetchval("SELECT current_user") == "tbs_omop", role
    # D-872: the console opens no OMOP store (its clinical conflicts are the orchestrator's routes, D-865)
    with pytest.raises(Exception):  # noqa: B017 - refused however the role meets the schema it may not use
        schema.connect(_as(box, "tb_console"), SITE_STORE, lake_dir=SITE_LAKE).close()


def test_the_worker_finds_every_store_and_clears_the_patient_from_each(
    box: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore import optout_worker as w

    orch_url = _as(box, "tb_orchestrator")
    monkeypatch.setenv("TB_DB_URL", orch_url)
    # the catalog answers a role that may not use a store
    assert w.omop_store_names(orch_url) == sorted(["omop", SITE_STORE, SPACE_STORE])
    reg = OptOutRegister(orch_url)
    reg.add(A, "office", "by letter", "office:t", T0)
    reg.close()
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=Audit(),
        services=SimpleNamespace(lake=Lake([])), db=Jobs(),
    )  # fmt: skip
    out = w.tick(orch)
    assert out is not None
    assert out["failed"] == [] and w.status()["failed"] == [], out  # every store opened and cleared
    assert not out.get("not_opened") and out["stores"]["omop"]["stores"] == 3
    assert A not in str(out) and A not in str(orch.audit.events)
    with Database.connect(box, "omop") as own:
        assert _live(own, A) == 0  # the box's own store was cleared in the same tick
    with Database.connect(orch_url, SPACE_STORE) as space:
        # the one such store a box as shipped can hold (a site set-up space, made in the orchestrator's process):
        # the worker is its owner and clears it
        assert space.fetchval("SELECT current_user") == "tb_orchestrator" and _live(space, A) == 0
    with Database.connect(_as(box, "tb_lake"), SITE_STORE) as site:
        assert _live(site, A) == 0  # D-721: the practice lake's store too, in the same tick


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
