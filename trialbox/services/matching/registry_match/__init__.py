"""Registry matching: the TrialGPT port (NCBI TrialGPT, Jin et al. 2024) vendored from the research branch
``claude/trialgpt-local-lcvm9p`` (folder ``trialgpt/trialgpt_local/``) by S1-17 (spec v4 §10.5).

What changed against the port:

* **No live registry search** (FR-M5-9). The port searched ClinicalTrials.gov with keywords generated from the patient
  note. Candidates now come only from the local mirror (:mod:`matching.registry_mirror`); nothing in this package
  opens a network connection.
* **No direct model calls.** Every model call goes through :func:`matching.registry_match.llm.call_model`, which takes
  an injected client callable (the tb-gateway client once it exists) and raises when none is injected.
* Not vendored: the web interface (``app.py``, ``static/``; C-5′ allows no extra surface), the trialgpt.app
  head-to-head (``h2h/``), the blinded-workbook helper used only by those two, and the CGRD harness (``cgrd/``,
  which belongs in ``eval/cgrd_match/`` in the de-identified zone).
* The benchmark (``benchmark.py``, ``datasets.py``, ``metrics.py``, the paper reference values) is in
  ``eval/match_registry/``.

Upstream NCBI sources used by the prompt drift check are in ``ncbi_upstream/`` with their public-domain notice.
"""

__version__ = "0.1.0"
