# B-1: the image gate takes the pinned engine image by its content, not only by its name

**Reader:** the people who build TrialBox: the integrator and the lane H lead. Findings for builders, so in one
language.

- **Card:** B-1 (lane B; blocker 2 of the owner's order of 2026-11-22: `make release-bundle` refused with 702 findings)
- **Date:** 2026-11-22
- **Ruling:** D-622 (one entry for every finding of the kernel headers package in the pinned model server image); the
  integrator's go of 2026-11-22 for option (d) on #639
- **Findings:** [`image-gate-pinned-content-2026-11-22/findings.json`](image-gate-pinned-content-2026-11-22/findings.json)
  (B1-01 to B1-03)
- **Tests:** `tests/unit/test_image_gate_pinned_content_b1.py`

## What the 702 were

A finding fails the image gate (`tools/supply_chain/vulns.py`) when it is CRITICAL, HIGH or unscored, has a fixed
version, and no allow-list entry accepts it. The pinned engine image carries 732 such findings with the scanner
database of 2026-11-22: 702 in `linux-libc-dev` 6.8.0-147 (663 HIGH, 39 CRITICAL) and 30 others (27 HIGH,
3 CRITICAL), each of the 30 a dated per-finding entry. The 702 are accepted by the one D-622 entry, which until this
card matched only a scanned reference whose text ends in the digest `deploy/images.lock` pins.

Measured offline on the report CI's image gates wrote for the pinned image on master 72a293ad (run 45017707606,
linux/amd64): at the pinned reference 0 findings fail; the same report under `vllm/vllm-openai:v0.32.0`, under the
linux/amd64 manifest digest or under any other digest fails exactly 702, all `linux-libc-dev`. So the bench's run
scanned the pinned content under its tag (a local image pulled by tag; the measured serving record names the engine
by its tag only). Which road set the tag on the bench was not verified.

## The change

- `allowlist.at_pinned_digest`: the D-622 entry applies when the scanned reference ends in the lock's digest, **or**
  one of the repository digests recorded for the scanned content (the image store's `RepoDigests`, the scanner's
  report) is that repository at that digest. A repository digest is the digest of the content as pulled, so a tag
  that points at other content still fails all of them; a name with no digest, a platform's manifest digest, the
  pinned digest under another repository, or an unreadable lock never passes.
- `vulns.gate(..., digests=)` passes them through; when the wide entry of the scanned repository did not apply and its
  package's findings fail, the gate adds one plain error: the reference's digest, the content's digests, the lock's
  digest, and "scan the pinned reference (tag@digest of the lock)".
- `release.run_gates` hands the image store's and the scanner's digests to the gate, and records the gate's errors
  in the image's row of `gates.json` (they were counted in `ok` but not written).

Unchanged: the threshold, every allow-list entry and its date, the per-finding entries (still matched by
repository), report mode, `bundle-check`.

## Not done here

- `deploy/security/known-image-findings.md` (lane H's) is not changed: its rows stand as written.
- No new waiver and no new date. All 732 fixable High/Critical findings of the pinned engine image remain covered
  only by the standing dated entries, which lapse on 2027-01-10 (B1-03).
