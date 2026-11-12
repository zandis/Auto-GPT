# D-560 The nightly is green again: the test stack's embed service runs as TEST, the public data is fetched, the random order runs in the unit shards

- **Task:** ENG-002 (deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/03-code-quality-se.md`; plan
  TB-PLAN-07 v7.2, wave 0, lane D)
- **PR:** this branch (`agent/ENG-002-nightly-green`), stacked on T-747 (D-475, PR #306) for the shards
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI, after PR #306)
- **Builds on:** D-429 (T-607: the stub embedder is refused in PRODUCTION), D-206 and T-653 (the nightly jobs),
  D-201 (the random-order run), D-475 (T-747: each test file in exactly one shard)

## Why

The nightly workflow `trialbox-e2e.yml` was red on 2026-11-10 and 2026-11-11 and nothing reacted. Three causes, read
from the job logs of run 43086595086:

1. `compose` stopped at `make up-test`: the test stack ran the embed service in PRODUCTION (the base file's
   default), where the stub embedder is refused (`EmbedderRefused: TB_EMBED_MODE hash is the CI stub`). The refusal
   is right for a box (ENG-003 gives the box a real embedder). The test stack is synthetic and must say so.
2. `public-e2e` stopped with `FileNotFoundError: .cache/medtxt/Test collection/...`: the public-data site reads the
   MedTxt corpus, which is fetched at run time and never committed, and no step fetched it.
3. `random-order` was cancelled by its 45-minute limit at 87 % (5,748 tests on two runner cores), with one failure
   it never named.

## Decision

1. **The test stack is a TEST stack.** `deploy/docker-compose.test.yml` sets `TB_ENV` to `TEST` for `embed-service`,
   as it does for the mail gateway and the model gateway. A unit test reads the merged compose set and fails when a
   service of the test stack that refuses a stub in PRODUCTION is left on the base file's default.
2. **The public data is fetched by a named step.** `make public-data` fetches the MedTxt corpus into `.cache/medtxt`
   (public, CC BY 4.0, 1.4 MB). The nightly `public-e2e` job runs it before the walk and keeps the folder in the
   runner's cache. When the corpus is missing, the public-data site stops with one line that names the command, not
   with a file error.
3. **The random-order run uses the unit shards.** The nightly job `random-order` runs `make test-random SHARD=i/N`
   in the same shards as the pull-request gate's `unit-shard` (the count is read from one place by a test, so the two
   cannot drift). No time limit is raised: the limit of each shard is the one the gate's shards have, which D-475
   derived from the measured suite. A failure now ends its shard with the test's name and the seed in the log.
4. **A red nightly is the next day's first card** (plan v7.2, wave 0). It is lane D's.

## Consequences

- The tests that need the real database image, HAPI, the mail servers and a browser run again every night.
- The random order runs to completion; an order dependence is named, with its seed.
- The nightly needs the MedTxt host to answer once per cache period; a failed fetch fails `public-e2e` with the
  reason.

## Not done here

- The pgvector tests in the pull-request gate (the review's fix 4 for ENG-002): a card of its own.
- The embed image and the PRODUCTION start test: ENG-003.
