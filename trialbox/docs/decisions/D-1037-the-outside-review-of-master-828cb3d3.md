# D-1037 The outside review of master 828cb3d3, as the integrator judged it

- **Task:** an owner's ruling, numbered by the integrator and relayed by the integrator
- **Date:** 2026-11-16
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-16)
- **Number:** Relayed to the lanes on 2026-11-16 under the number D-537, which was already taken by "Every file name
  in a backup is stored with its own bytes, also the second name of one file"; cite it as D-1037.

## Ruling

1. An outside review of master `828cb3d3` was judged by the integrator. Its three lists are below.
2. PR #813 stays parked.

## Where the wording comes from

The integrator's session.

## Used by

`docs/plan/42-plan-2026-11-16.md` sections 4a, 4f and 4g.

## Adopted now

- its CI findings, as input to lane D;
- no self-hosted runner while the repository is public;
- the TFDA pre-fill rule, checked against our design;
- an independent check of the masker with an open-source de-identification tool, in measurement only;
- shadow mode with an effectiveness report, as a design card;
- provenance on every AI output, as a design card.

## Build later (in the plan)

- ICH M11 / USDM with CDISC's rules engine;
- a FHIR validator as a separate process;
- an HL7 v2 library and an integration engine, when a site needs them;
- FHIR-to-CDISC mapping for eSource;
- a trial-retrieval A/B;
- a load-test tool;
- a published Taiwan evaluation set.

## Declined

- an MCP endpoint;
- a sponsor A2A interface;
- an ePRO app;
- an identity provider inside the box;
- prompt-optimisation and RAG-scoring tools.

## A fact the owner gave with these rulings (2026-11-16)

The charts at the pilot hospital, and in Taiwan generally, are mainly in English on a zh-TW site. It is a fact, not a
ruling, and has no number. It bears on the gold set (D-517: English first, then zh-TW) and on the masker's check.
