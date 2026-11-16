"""The mail gateway's start-time store (D-921; the runner: ``tb_common.start_migrations``): its lifespan opens it."""

from __future__ import annotations

from tb_common.start_migrations import Store, closed, main


def _mail() -> str:
    from mail_gateway.store import MailDB

    return closed(MailDB())


STORES: tuple[Store, ...] = (("mail", _mail),)

if __name__ == "__main__":
    raise SystemExit(main("mail-gateway", STORES))
