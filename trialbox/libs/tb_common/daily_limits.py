"""D-775 (the owner's ruling D-507, cut to the build phase by D-511): the heavy-jobs daily limit is a declared setting.

The heavy jobs one sender may start in a day (FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION; 20, D-146) were set
in the site's ``settings.yaml`` only, which a box made by ``install.sh --answers`` does not reach. The declared
``TB_JOBS_PER_SENDER_PER_DAY`` does (``env_extra``): when set, it is the limit of every heavy type, overriding
``settings.yaml``; 0 means no limit, which is how lane G's VALIDATION box lifts it. A value that is not a whole number
is ignored. The mails one recipient gets a day already have their declared setting (``TB_MAIL_PER_RECIPIENT_PER_DAY``).
The refusal of a lift on PRODUCTION (D-507's option (a)) waits until after PoC-1 (D-511)."""

from __future__ import annotations

from collections.abc import Mapping

JOBS_VAR = "TB_JOBS_PER_SENDER_PER_DAY"


def jobs_override(env: Mapping[str, str]) -> int | None:
    """The declared limit of the heavy job types (0 = no limit), or None when it is not set to a whole number."""
    raw = (env.get(JOBS_VAR) or "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None
