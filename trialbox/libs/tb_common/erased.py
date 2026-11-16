"""ERASE-A2 (D-875, the owner's D-1032): the token a never-consented patient's screening-log rows take in place of the
pseudonym, and the sets that count a token as opted out. No register is read here (a reader that leaves out the
opted-out gets its pseudonyms through the decision context, T-708, D-477)."""

from __future__ import annotations

import re
from typing import Any

# a never-consented patient's screening-log rows stay, numbered, and their
# pseudonym becomes a random token. The token carries the site's day of the opt-out (the log shows it, D-762) and
# nothing of the patient. ERASE-C's tokens (D-868) have the prefix and no day.
ERASED = "erased:"


def erased_token(day: str) -> str:
    """A fresh token for one patient's rows in one study: ``erased:<YYYY-MM-DD or empty>:<random>``."""
    import uuid

    return f"{ERASED}{day if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) else ''}:{uuid.uuid4().hex}"


def is_erased(pid: object) -> bool:
    return isinstance(pid, str) and pid.startswith(ERASED)


def erased_day(pid: str) -> str:
    """The day of the opt-out a token carries, or ""."""
    m = re.fullmatch(r"erased:(\d{4}-\d{2}-\d{2}):[0-9a-f]+", pid)
    return m.group(1) if m else ""


class Gone(set[str]):
    """The pseudonyms opted out now, which also holds every erased token: a row whose pseudonym was erased is an
    opted-out patient's row to every reader that leaves those out (fail closed: D-875)."""

    def __contains__(self, pid: object) -> bool:
        return is_erased(pid) or super().__contains__(pid)


class GoneOn(dict[str, str]):
    """:class:`Gone` with the site's day each was opted out; an erased token's day is the one it carries."""

    def __contains__(self, pid: object) -> bool:
        return is_erased(pid) or super().__contains__(pid)

    def get(self, pid: str, default: Any = None) -> Any:
        if super().__contains__(pid):
            return super().__getitem__(pid)
        return erased_day(pid) if is_erased(pid) else default

    def __getitem__(self, pid: str) -> str:
        if not super().__contains__(pid) and is_erased(pid):
            return erased_day(pid)
        return super().__getitem__(pid)
