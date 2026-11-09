"""Supply-chain gates for TrialBox (D-185 hashed lock, D-186 SBOM, scanners, allow-list, licences).

    python -m tools.supply_chain lock-export          # uv.lock -> deploy/requirements.lock (with sha256 hashes)
    python -m tools.supply_chain lock-check           # fails if a lock is stale or an entry has no hash
    python -m tools.supply_chain allowlist-check      # every allow-list entry has a reason and a review date
    python -m tools.supply_chain pip-audit-gate FILE  # pip-audit JSON -> pass/fail after the allow-list
    python -m tools.supply_chain trivy-gate FILE...   # Trivy JSON -> pass/fail after the allow-list
    python -m tools.supply_chain sbom ...             # run Syft per image / for the lock, check what it wrote
    python -m tools.supply_chain licences FILE...     # licence report from CycloneDX SBOMs; flags (L)GPL and AGPL

The scanners (uv, pip-audit, Syft, Trivy) are separate programs. Everything that decides pass or fail reads their
JSON and is tested offline on small fixtures (``tests/unit/test_supply_chain.py``).
"""
