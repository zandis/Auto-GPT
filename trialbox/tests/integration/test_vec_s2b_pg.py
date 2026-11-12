"""S2b from the vector store on pgvector (T-203b, D-449): the lake's read on a real ``vec`` schema.

Needs a server with the ``vector`` extension, as ``tests/integration/test_vec_store.py`` (its fixture is reused):
``TB_TEST_DB_URL`` pointing at one, or the box's db image with ``TB_INTEGRATION=1``. Anywhere else (the pull-request
CI has no pgvector) these tests skip with that reason. The switch, the fallback and the evidence are unit tests
(``tests/unit/test_vec_s2b.py``, ``tests/unit/test_safety_properties.py``) that need no database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from vec import s2b
from vec.index import Note, index_notes, index_snapshot, snapshot_notes
from vec.store import VecStore

from tests.integration.test_vec_store import url, vec_server  # noqa: F401  (fixtures)
from tests.unit.test_phi_note_mask import SITE_MRN, _ndjson

pytestmark = pytest.mark.integration


def test_the_lake_ranks_the_pinned_snapshot_from_pgvector_and_falls_back_on_a_change(
    url: str,  # noqa: F811
    tmp_path: Path,
) -> None:
    lake = Lake(tmp_path / "lake", "Asia/Taipei", SITE_MRN)
    lake.rebuild("2026-01-02", HashEmbedder(), _ndjson(tmp_path / "nd"))
    e = HashEmbedder()
    with VecStore(url, model=e.model, dim=e.dim) as st:
        stats = index_snapshot(st, lake, "2026-01-02", e, exclude={"p2"}, mrn_regex=SITE_MRN)
        assert stats.notes == 1 and st.counts()["patients"] == 1
        did = next(n.did for n in snapshot_notes(lake, "2026-01-02") if n.pid == "p1")
        got = lake.vec_s2b("p1", [did], "gout", e, st, "2026-01-02")
        assert got["state"] == "vec" and got["model"] == e.model and got["hits"]
        assert {h["did"] for h in got["hits"]} == {did}
        assert [h["score"] for h in got["hits"]] == sorted((h["score"] for h in got["hits"]), reverse=True)
        local = LakeLocal(tmp_path / "lake", e, "Asia/Taipei", vec_store=st, mrn_regex=SITE_MRN)
        assert local.vec_s2b("p1", [did], "gout", "2026-01-02") == got
        # the opted-out patient was never indexed: its pair falls back, it is not ranked from nothing
        assert lake.vec_s2b("p2", ["d2"], "gout", e, st, "2026-01-02") == s2b.fallback(s2b.NOT_INDEXED)
        # a later night indexed another text of the note: the pinned snapshot's vectors are gone, so it falls back
        later = [Note(n.pid, n.did, n.text + " Seen again.") for n in snapshot_notes(lake, "2026-01-02")]
        index_notes(st, [n for n in later if n.pid == "p1"], e, mrn_regex=SITE_MRN)
        assert lake.vec_s2b("p1", [did], "gout", e, st, "2026-01-02") == s2b.fallback(s2b.STALE)
