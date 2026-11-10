"""Supply-chain gates for TrialBox (D-185 hashed lock, D-186 SBOM, scanners, allow-list, licences).

    python -m tools.supply_chain lock-export          # uv.lock -> deploy/requirements.lock (with sha256 hashes)
    python -m tools.supply_chain lock-check           # fails if a lock is stale or an entry has no hash
    python -m tools.supply_chain allowlist-check      # every allow-list entry has a reason and a review date
    python -m tools.supply_chain scanners             # Syft and Trivy archives with pinned sha256
    python -m tools.supply_chain pip-audit-gate FILE  # pip-audit JSON -> pass/fail (audited set = the lock)
    python -m tools.supply_chain lock-sbom            # Syft SBOM of the environment installed from the lock
    python -m tools.supply_chain licences FILE...     # licence report; flags (L)GPL, AGPL, unknown and dual
    python -m tools.supply_chain trivy-gate FILE...   # Trivy JSON -> pass/fail (and the DB age)
    python -m tools.supply_chain release-gates ...    # every shipped image by id/digest and platform: one record
    python -m tools.supply_chain bundle-check ...     # may a bundle carry these local images?

The scanners (uv, pip-audit, Syft, Trivy) are separate programs. Everything that decides pass or fail reads their
JSON and is tested offline on small fixtures (``tests/unit/test_supply_chain.py``).
"""
