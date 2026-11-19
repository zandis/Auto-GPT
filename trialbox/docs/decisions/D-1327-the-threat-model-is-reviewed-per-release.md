# D-1327 The threat model is a section of the security document, reviewed per release (10G-4)

- **Task:** lane H, plan 10 row 10G-4 (review 16, item 16-16): a threat model file, reviewed per release; ASVS 1.1.2
  to "meets". · **Date:** 2026-11-19
- **Decision:**
  - The threat model is section 12 of the security document, `docs/security/12-threat-model.md`, in the section
    files' plain form (D-352): assets, actors, the trust boundaries of the compose services and networks, and per
    boundary each threat with its control and the file or test that proves it, or the open finding.
  - A control counts as proved only with a test (or a file whose check runs in CI) that the page names; otherwise the
    threat is open and names a row of the findings register, a finding of the page (H10G4-nn) or a plan card.
  - **Per release.** The page names the release it was reviewed for (`**Reviewed for release:** <version>`).
    `tests/unit/test_threat_model_per_release.py` fails when `[project] version` in `pyproject.toml` is not that
    release, so the pull request that sets a version reviews the page, as `test_changelog_has_the_current_version`
    holds the changelog. The same test fails on a cited path, test or finding that no longer exists.
  - ASVS 1.1.2 is "meets", basis "shown", with this page as evidence and that test as its test; the checklist's finding
    V3-16 stays named on the line, as 3.4.1 keeps V3-12. Closing V3-16 in the register is the integrator's.
- **Held by:** `tests/unit/test_threat_model_per_release.py`.
