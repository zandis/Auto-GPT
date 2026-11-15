# D-791 The owner's acceptance of CVE-2026-111943 in Authelia becomes a "Not reachable" entry

- **Task:** AUTHELIA-NOT-REACHABLE, the step D-722 left for the owner
- **PR:** this branch (`agent/AUTHELIA-NOT-REACHABLE-the-owners-entry-replaced`)
- **Date:** 2026-11-15
- **Status:** accepted (the owner's yes, typed in lane D's session: when D-722 is on master, one entry, no other
  change)
- **Builds on:** D-574 (the Authelia image's entries), D-722 (Authelia trusts only the hospital's directory CA)

## Context

The owner accepted CVE-2026-111943 (intermediates `crypto/x509` should no longer trust) in the pinned Authelia image
on 2026-11-13, on condition that the real fix is built. D-722 built it and is on master since train 17: the
container's root list is the hospital's directory CA. The scanner reads the binary, not how the box runs it, so the
finding stays and needs an entry; D-722 asked the owner to replace the acceptance by a "Not reachable" entry.

## Decision

1. In `deploy/supply-chain-allowlist.yaml` the acceptance entry for CVE-2026-111943 in `authelia/authelia` is
   replaced by one "Not reachable" entry: same pinned digest, `review_by: 2026-12-10`, the same owner. Its reason
   is the fact D-722 makes true, and its limit: a PRODUCTION or VALIDATION box with the hospital sign-in on does not
   start without a usable CA file; with the sign-in off Authelia makes no LDAPS connection.
2. The comment above the Authelia entries and the Authelia row of `deploy/security/known-image-findings.md` say the
   same; they described the acceptance. The postgres base's entry for the same id is not touched.

## Test

`tests/unit/test_authelia_x509_entry.py`, whose reason test described the acceptance (its docstring said the entry goes
with the real fix), now asserts the "Not reachable" reason and its limit, and that the postgres entry of the same id
is untouched: before the edit, the new assertions failed on the acceptance entry; after, 4 passed.
