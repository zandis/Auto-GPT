# D-485 Keys apart, first part: the key that signs people is its own secret, not a function of the console's service token

- **Card:** T-717 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-717-keys-apart`); built on T-716's branch (PR #326), which is built on #317 and
  #312: it shows their commits until they merge
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-138 (one token per service), D-143 (the signed actor), D-437 (the secret layout), D-483 (actor
  assertion v3)
- **Closes:** proposal TR-5 of `docs/reviews/2026-11-12-architecture/trust.md`, its first clause (see "Not done")

## The problem

The console signs the person of a call with `HMAC(console token, "tb-actor-assertion/1")`. The console sends its
token on every call it makes, to the orchestrator and also to the mail gateway and the adapter. Whoever holds the
token can compute the key: a service that only *receives* the console's calls can name any person, with any role
and any grant, to the orchestrator.

## The decision

(filled in with the build; see the pull request)
