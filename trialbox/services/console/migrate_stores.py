"""The console's start-time stores (D-921; the runner: ``tb_common.start_migrations``): ``create_app`` opens them
all (the workspace's when it is on, the default)."""

from __future__ import annotations

import os

from tb_common.start_migrations import Store, closed, main


def _auth() -> str:
    from console.auth import UserStore

    return closed(UserStore())


def _site() -> str:
    from console.sitestore import SiteStore

    return closed(SiteStore())


def _team() -> str:
    from console.teamstore import TeamStore

    return closed(TeamStore())


def _optout() -> str:
    from tb_common.optout import OptOutRegister

    return closed(OptOutRegister())


def _flags() -> str:
    from tb_common.db import Database
    from tb_common.flags import Flags

    db = Database.connect(os.environ.get("TB_DB_URL"), "app")
    try:
        Flags(db).install(db)
    finally:
        db.close()
    return "migrated"


def _feedback() -> str:
    from console.feedback import FeedbackStore

    return closed(FeedbackStore())


def _sae() -> str:
    from console.saerecord import SaeStore

    return closed(SaeStore())


def _breakglass() -> str:
    from console.breakglass_store import BreakGlassStore

    return closed(BreakGlassStore())


def _tuned() -> str:
    from tb_common.notmatched import NotMatchedStore

    return closed(NotMatchedStore())


STORES: tuple[Store, ...] = (
    ("auth", _auth),
    ("site", _site),
    ("team", _team),
    ("optout", _optout),
    ("app", _flags),
    ("feedback", _feedback),
    ("sae", _sae),
    ("breakglass", _breakglass),
    ("tuned", _tuned),
)

if __name__ == "__main__":
    raise SystemExit(main("console", STORES))
