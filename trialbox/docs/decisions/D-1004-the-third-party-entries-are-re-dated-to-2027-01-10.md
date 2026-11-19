# D-1004: the third-party allow-list entries are re-dated to 2027-01-10

Status: reserved (lane D, card REDATE)

## Context

The 63 dated entries of `deploy/supply-chain-allowlist.yaml` for the third-party images lapse on 2026-12-10. Their
owner read "security owner (to assign)". On 2026-11-17 the owner named himself the security owner (D-1067). No patched
upstream tag has cleared them since. On 2026-11-19 he said "ok" to the date lane D proposed, 2027-01-10. The checker
allows a date up to 180 days ahead (`MAX_AHEAD_DAYS`).

## Decision

Each of the 63 entries gets `owner: Chang-Fu Kuo (the owner, D-1067)` and `review_by: 2027-01-10`. The entries cover
vllm/vllm-openai (30), hapiproject/hapi (21), authelia/authelia (8, plus 1 `os_packages_unreadable`) and caddy (3). No
entry is added, removed or widened, and no reason changes. The allow-list's comment says when and by whom the entries
were re-dated.

`deploy/security/known-image-findings.md` names the owner and the date. A new section gives one reason per group for
standing until 2027-01-10. Six tests that pin the date or the owner are moved to the new values. Nothing is weakened:
each still checks every field it checked before.

## The allow-list edit

The edit to `deploy/supply-chain-allowlist.yaml` is applied by the integrator, because lane D cannot edit that file.
The commands and the comment hunk are on #639. Without that edit, the six moved tests fail on purpose.

## Checks

On a scratch copy of master a44a39dac with the whole change applied:
- `tools.supply_chain allowlist-check`: PASS (96 valid entries);
- every test that reads the allow-list or the findings page: 192 passed, 3 skipped (uv 0.13.7 not on PATH).

## Remains

On 2027-01-10 each image has moved to a patched tag or each entry is reviewed again.
