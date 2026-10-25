"""Local ClinicalTrials.gov mirror (spec v4 §10.5, FR-M5-9).

Registry retrieval runs only over this mirror: ClinicalTrials.gov API v2 study records stored on the box with a
manifest (records, content hash, fetch time). The mirror is D0 (public registry text). It replaces the port's live
registry search, which sent keywords generated from the patient note to the registry; no patient-derived text is ever
used to fetch records. Refreshing the mirror (a nightly fetch of recruiting studies by country, with no patient input)
is a separate job; :class:`RegistryMirror` only reads what is stored.
"""

from __future__ import annotations

from matching.registry_mirror.convert import split_criteria, to_corpus_entry, to_trial
from matching.registry_mirror.mirror import MirrorManifest, RegistryMirror

__all__ = ["MirrorManifest", "RegistryMirror", "split_criteria", "to_corpus_entry", "to_trial"]
