# H69: the allow-list names the owner's role; the install runbook says building the images needs memory

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H69, two small cards in one pull request: the owner's ruling on finding H10G8-08 (relayed by the
  integrator on 2026-11-19, 22:47 UTC) and the integrator's docs card of 2026-11-20, 03:09 UTC.
- **Date:** 2026-11-20
- **Decision:** [D-1352](../decisions/D-1352-a-waiver-names-the-owner-role-not-a-person.md)
- **Findings:** [`owner-as-role-and-images-memory-2026-11-20/findings.json`](owner-as-role-and-images-memory-2026-11-20/findings.json)
  (H69-01, H69-02)

## 1. The owner as a role

The owner ruled: "a role, not a person's name." Each of the 63 `owner` values of
`deploy/supply-chain-allowlist.yaml` now reads `the project owner (D-1067)`. No date, reason, review_by or match key
changed: the diff against master removes 63 owner lines and adds 63.

Two tests asserted the allow-list's owner text and take the new text:
`tests/unit/test_authelia_x509_entry.py` and `tests/unit/test_vllm_dnspython_entry.py`.
`tests/unit/test_supply_chain.py` asserts the owner's name in `deploy/security/known-image-findings.md`, not in the
allow-list. That file is not changed here, so neither is the test.

The release VEX carries each waiver's owner as its `trialbox:owner` property, so its output changes: 63 owner values,
and the serial number, which is derived from the content. The test fixture under `tests/fixtures/vex/` has its own
allow-list and does not change.

H10G8-08 is fixed by this card's first commit. The other tracked files that still hold the name are listed in the
pull request and in H69-02, not changed.

## 2. Memory for building the images

Step 2 of `docs/runbook/01-install-a-new-site.md` lists what the build host needs. One line is added at the end of
that list (line 128): building the images needs memory; on a Windows host raise the Linux VM's memory limit or
build with fewer parallel jobs, or `make images` can take the VM down. No figure is given: the repository records no
measured peak for `make images` (H69-01). No runbook line number is pinned by a test or tool.
