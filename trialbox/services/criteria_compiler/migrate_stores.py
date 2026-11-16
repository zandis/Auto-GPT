"""The compiler's start-time store (D-921; the runner: ``tb_common.start_migrations``): the vocabulary store, opened
at start only when the compiler resolves through it (``TB_TERMINOLOGY_SOURCE=vocab``)."""

from __future__ import annotations

from tb_common.start_migrations import Store, closed, main


def _vocab() -> str:
    from criteria_compiler.terminology import resolver

    if resolver.source() != "vocab":
        return "the compiler reads its terminology files"
    return closed(resolver._vocab_db())


STORES: tuple[Store, ...] = (("omop", _vocab),)

if __name__ == "__main__":
    raise SystemExit(main("criteria-compiler", STORES))
