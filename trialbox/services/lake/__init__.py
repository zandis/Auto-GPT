"""DuckDB starts a default database when its public Python module is imported."""

import os

if threads := os.environ.get("TB_LAKE_THREADS"):
    # Install the bounded default before duckdb imports it in each HTTP worker and rebuild process.
    # The native module ships with our pinned DuckDB wheel and opens no database on import.
    import _duckdb

    _duckdb.set_default_connection(_duckdb.connect(config={"threads": threads}))
