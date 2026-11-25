"""H-147 (CI-1): ids a reader looks up in the log, drawn so that the log's scrubber leaves them whole.

A run record sends its reader to the log by the run's id (``failure.words``: "...; run <id>"). A hex id holds a run
of digits often enough (about 1 draw in 130) for the scrubber to read it as a phone number or an ID number and mask
it, and then no log line holds the id (CI's draw was logged as ``d6d8b[PHONE]a``).

The rule, from the scrubber's own patterns (``tb_common.logging`` and the note masker in ``tb_common.phi_guard``):
each identifier rule needs a digit; each masker rule needs a digit, a capital letter, an ``@`` or a label word with
its mark; each secret rule needs a ``:`` or ``=`` after a secret's name, or a ``bearer``/``basic`` with a space. An id
of lower-case ASCII letters only holds none of these. The scrubber is also asked once per draw, for the rules a site
or the process adds (the site's chart-number pattern, the secret values the process holds): a draw it would change
is drawn again (none was in a million draws), at most :data:`ATTEMPTS` times. A site pattern that reads letters (such
as ``^[A-Za-z0-9]{6,20}$``, which the settings take) changes every draw: the last draw is handed out then, a valid id
whose log line shows the rule's kind, as a hex id's did on such a site. The request that draws holds the adapter's
run gate, so it must never spin (H-147, review 1515-1).

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
#: draws asked of the scrubber at most: a rule that refuses one draw in a million never refuses 32 in a row, and one
#: that reads letters refuses every draw
ATTEMPTS = 32


def _spell(n: int) -> str:
    out = []
    for _ in range(LENGTH):
        n, d = divmod(n, len(ALPHABET))
        out.append(ALPHABET[d])
    return "".join(out)


def log_safe_id(rng: random.Random | None = None) -> str:
    """A new id of :data:`LENGTH` lower-case letters that the log's scrubber leaves whole (unless a site rule reads
    every letter draw: then the last of :data:`ATTEMPTS` draws). ``rng`` is for tests (a seeded generator); the
    service draws from the system's (``secrets``)."""
    from tb_common.logging import redact  # here, not at import: the logging module imports much

    rid = ""
    for _ in range(ATTEMPTS):
        n = rng.randrange(_SPACE) if rng is not None else secrets.randbelow(_SPACE)
        rid = _spell(n)
        line = f"run {rid} failed"
        if redact(line) == line:
            return rid
    return rid  # every draw changed: a site rule reads letters; still a valid id, never a request that spins
