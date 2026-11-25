"""H-139 (the integrator's 7155060416): the test cluster refuses, once and plainly, a server whose vector extension is
older than the db image's pin.

On the bench host, test_erasure_reach's 238 errors came from an older vector extension (``public.halfvec`` missing),
not from the code. A host like that now stops the run at the start with one message.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import psycopg
import pytest
from tb_common.db import split_url

from tests import conftest
from tools import pglocal

PIN = str(json.loads(pglocal.IMAGES_LOCK.read_text(encoding="utf-8"))["images"]["db"]["extensions"]["vector"])


@pytest.mark.parametrize("offered", [None, "", PIN, "9.9.9", f"{PIN}-1.pgdg13+1"])
def test_a_server_with_no_vector_or_one_at_least_the_pin_is_not_refused(offered: str | None) -> None:
    assert pglocal.vector_behind_pin(offered, PIN) == ""


@pytest.mark.parametrize("offered", ["0.5.1", "0.6.0", "0.7.4"])
def test_an_older_vector_is_refused_by_both_versions(offered: str) -> None:
    why = pglocal.vector_behind_pin(offered, "0.8.7")
    assert f"vector extension {offered}, older than the db image's 0.8.7" in why and "halfvec" in why


def test_the_check_reads_this_clusters_vector(pg_cluster_url: str) -> None:
    dsn = split_url(pg_cluster_url)[0]
    with psycopg.connect(dsn, autocommit=True) as con:
        row = con.execute("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'").fetchone()
    assert pglocal.vector_check(dsn) == pglocal.vector_behind_pin(row[0] if row else None, PIN)


def test_the_cluster_fixture_stops_the_run_once_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pglocal, "vector_check", lambda url: "synthetic: the vector extension is older")
    request = SimpleNamespace(session=SimpleNamespace(shouldstop=False))
    with pytest.raises(pytest.fail.Exception, match="synthetic: the vector extension is older"):
        conftest._vector_or_stop(request, "postgresql://synthetic@/x?host=/nowhere")  # type: ignore[arg-type]
    assert request.session.shouldstop == "synthetic: the vector extension is older"
    monkeypatch.setattr(pglocal, "vector_check", lambda url: "")
    conftest._vector_or_stop(request, "postgresql://synthetic@/x?host=/nowhere")  # type: ignore[arg-type]
    source = inspect.getsource(conftest.pg_cluster_url)
    assert "_vector_or_stop(request, given)" in source and "_vector_or_stop(request, url)" in source
