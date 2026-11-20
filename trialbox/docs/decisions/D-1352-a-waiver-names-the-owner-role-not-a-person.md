# D-1352 A waiver names the owner's role, not a person (H69)

- **Task:** lane H, card H69 (finding H10G8-08 of card 10G-8) · **Date:** 2026-11-20
- **Status:** accepted (the owner's ruling, relayed by the integrator on 2026-11-19)
- **Builds on:** D-1004 (the third-party entries re-dated, with the owner named in each), D-1067 (who holds the
  role), D-1339 (every waiver has an owner)

## Decision

1. The owner ruled: "a role, not a person's name." Every `owner` value of `deploy/supply-chain-allowlist.yaml` reads
   exactly `the project owner (D-1067)`.
2. Nothing else in any entry changes: no date, reason, review_by or match key. On 2026-11-20 that is 63 lines.
3. D-1004 had put the owner's personal name in each entry. D-1067 says who holds the role: the owner named himself
   the security owner of the allow-list's entries.
4. The tests that assert the allow-list's owner text take the new text. The release VEX carries the owner as the
   `trialbox:owner` property of each record, so it now names the role too.
5. Other tracked files that still hold the name are listed in the card's pull request, not changed here.

## Links

- Finding H10G8-08: `docs/handover/vex-from-waivers-2026-11-19/findings.json` (now fixed).
- Card page: `docs/handover/owner-as-role-and-images-memory-2026-11-20.md`.
