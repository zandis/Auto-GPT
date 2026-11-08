"""Where the console's stores live: their schemas in the trial database (PostgreSQL ``trialbox_wf``, D-126).

``auth`` holds accounts, sessions and failed sign-ins (:class:`console.auth.UserStore`); ``site`` holds what the site
types in and the investigators' marks (:class:`console.sitestore.SiteStore`).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from tb_common.db import ENV, Database, DatabaseError


def open_db(url: str | None, schema: str, migrations: Sequence[str]) -> Database:
    """``schema`` of the trial database at ``url`` (else ``TB_DB_URL``), migrated to the current version."""
    url = url if url is not None else os.environ.get(ENV)
    if not url:
        raise DatabaseError(
            f"{ENV} is not set: the console keeps its {schema!r} store in the trial database (PostgreSQL, D-126)"
        )
    db = Database.connect(url, schema)
    db.migrate(migrations)
    return db
