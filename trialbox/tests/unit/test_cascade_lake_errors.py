"""D-127 (review F-04): only a missing consent or note table is tolerated; any other lake error stops the run."""

from __future__ import annotations

import duckdb
import pytest
from matching.cascade.engine import missing_table


def _catalog_error(table: str) -> Exception:
    try:
        duckdb.sql(f"SELECT * FROM {table}")
    except Exception as exc:  # duckdb.CatalogException
        return exc
    raise AssertionError("no error")


def test_missing_table_is_recognised_locally_and_over_http() -> None:
    assert missing_table(_catalog_error("consent"), "consent")
    assert missing_table(RuntimeError("lake query failed (400): Catalog Error: Table with name document does not exist!"),
                         "document")  # fmt: skip


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("lake query failed (503): upstream connect error"),
        TimeoutError("timed out"),
        RuntimeError("lake query failed (500): Binder Error: column contact_ok not found in consent"),
        PermissionError("snapshot locked"),
    ],
)
def test_other_errors_are_not_mistaken_for_a_missing_table(exc: Exception) -> None:
    assert not missing_table(exc, "consent")
