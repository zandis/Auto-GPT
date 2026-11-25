"""H-147 (CI-1): ids a reader looks up in the log, drawn so that the log's scrubber leaves them whole.

A run record sends its reader to the log by the run's id (``failure.words``: "...; run <id>"). A hex id holds a run
of digits often enough (about 1 draw in 130) for the scrubber to read it as a phone number or an ID number and mask
it, and then no log line holds the id (``d6d8b0974142441a`` was logged as ``d6d8b[PHONE]a``).

The rule, from the scrubber's own patterns (``tb_common.logging`` and the note masker in ``tb_common.phi_guard``):
each identifier rule needs a digit; each masker rule needs a digit, a capital letter, an ``@`` or a label word with
its mark; each secret rule needs a ``:`` or ``=`` after a secret's name, or a ``bearer``/``basic`` with a space. An id
of lower-case ASCII letters only holds none of these. The scrubber is also asked once per draw, for the rules a site
or the process adds (the site's chart-number pattern, the secret values the process holds): a draw it would change
is drawn again (none was in a million draws).

Strength: 16 letters of 26 is 16 x log2(26) = 75.2 bits, against the 64 of the 8-byte hex id it replaces; the length
(16) is the same, and an older hex id is still a valid id where one is read back (both are ``str.isalnum``).
"""

from __future__ import annotations

import random
import secrets

ALPHABET = "abcdefghijklmnopqrstuvwxyz"
LENGTH = 16
BITS = 75  # floor(16 x log2(26)); the 8-byte hex id held 64
_SPACE = len(ALPHABET) ** LENGTH


def _spell(n: int) -> str:
    out = []
    for _ in range(LENGTH):
        n, d = divmod(n, len(ALPHABET))
        out.append(ALPHABET[d])
    return "".join(out)


def log_safe_id(rng: random.Random | None = None) -> str:
    """A new id of :data:`LENGTH` lower-case letters that the log's scrubber leaves whole. ``rng`` is for tests (a
    seeded generator); the service draws from the system's (``secrets``)."""
    from tb_common.logging import redact  # here, not at import: the logging module imports much

    while True:
        n = rng.randrange(_SPACE) if rng is not None else secrets.randbelow(_SPACE)
        rid = _spell(n)
        line = f"run {rid} failed"
        if redact(line) == line:
            return rid
