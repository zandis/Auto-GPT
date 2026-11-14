"""The kinds of the night's counter of values the mapping could not use (NEW-B-39, D-740; D-580).

The adapter splits its counter by these kinds per source table (``adapter.pipeline.unmapped_kinds``); the night's
page reads them back. Counts only: no code and no value travels with a kind.
"""

from __future__ import annotations

#: ``code_unknown``: a code no look-up, list of known codes or map gives a single answer for; ``unit_not_read``: a
#: value whose unit is not the look-up's, or implausible without one (D-590); ``reference_data_not_reached``: a code
#: the reference data could not be asked for (D-593)
KINDS = ("code_unknown", "unit_not_read", "reference_data_not_reached")
