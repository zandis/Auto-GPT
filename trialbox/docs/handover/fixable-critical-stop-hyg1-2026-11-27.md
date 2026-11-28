# HYG1: a fixable CRITICAL in a shipped image stops the release gates; the two third-party pins

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** release hygiene item 1 (the integrator's 7211450855): re-pin the proxy image and the FHIR server image;
  make a fixable CRITICAL in any shipped image a stop in the release gates
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Findings:** [`fixable-critical-stop-hyg1-2026-11-27/findings.json`](fixable-critical-stop-hyg1-2026-11-27/findings.json)
  (HYG1-01 to HYG1-03)

## Files outside the card

None. Lane H's own: `tools/supply_chain/vulns.py` (`gate`), the release-gates step's comment in
`.github/workflows/trialbox-images.yml`, and a paragraph at the end of `deploy/security/known-image-findings.md`.

The card's own: `tests/unit/test_fixable_critical_stops_the_gate_hyg1.py`, this page and its findings.

## The gate

In an image scan, no allow-list entry accepts a CRITICAL finding that has a fixed version. The finding fails, and an
error names it, the image and the fixed version. Not changed: a CRITICAL with no fix, a fixable HIGH (both keep the
dated entries), the audit of the locked Python packages (no image), and the test-only mail servers, which no bundle
carries and which stay report-only (D-827).

The allow-list entries carry no severity, so the tree does not say whether any of the 62 current entries (the model
server image 30, the FHIR server image 21, the identity image 8, the proxy image 3) is a fixable CRITICAL. If one
is, the next release-gates run fails on it (HYG1-03). It is to be reported, not silenced.

## The pins (not changed: the lead's ruling, pending the integrator's)

Read from public registry metadata, the Go vulnerability database and the upstream source tags on 2026-11-27. Nothing
was pulled or scanned.

- **The proxy image.** Pinned: `2.11.9-alpine` at
  `sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0`, the newest tag of its line (the newest
  upstream release tag is v2.11.9). The HIGH finding is CVE-2026-78661 (GO-2026-6860, x/net), fixed in x/net
  v0.62.0. v2.11.9 is built with x/net v0.60.0. Only the upstream main branch (679806f9) has v0.62.0. No published
  release fixes it (HYG1-01).
- **The FHIR server image.** Pinned: `v8.12.0-2` at
  `sha256:0ff86aac4c7bd13a1ee226444a70263bb46ed1c28ef543c30a44f865b80ca04e`, the newest of its line. The only newer
  image is `v9.0.0-1` (2026-11-26, `sha256:08afec00897a5813b165ff2e8b03ca075986493518bd7a279b9f7c0b89de152f`), a new
  major release. Whether it clears the 21 allow-listed findings is not shown here (HYG1-02).

## What was not verified

- The release gates on real images: the change is shown by the unit test on synthetic findings, not by a scan.
- Whether `v9.0.0-1` clears the FHIR server's findings, or works with the box: not pulled, not scanned, not run.
