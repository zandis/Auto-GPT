"""TrialBox Test Bench: a developer and validation web tool, never a product surface (docs/HANDOFF.md §5).

It runs only with ``TB_ENV`` set to ``DEV`` or ``TEST``, loads only D0 datasets from ``eval/DATASETS.yaml``, binds
``127.0.0.1`` by default and shows :data:`BANNER` on every page. It lives under ``tools/`` so that no product image
or production compose file contains it (``tests/testbench/test_testbench_no_prod.py``).
"""

from __future__ import annotations

BANNER = "TEST BENCH: synthetic and open data only, not a clinical tool"
HTMX_VERSION = "2.0.4"
HTMX_SOURCE = "https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.4/htmx.min.js"
HTMX_SHA256 = "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447"

__all__ = ["BANNER", "HTMX_SHA256", "HTMX_SOURCE", "HTMX_VERSION"]
