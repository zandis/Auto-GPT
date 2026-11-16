# The owner's rulings of 2026-11-16 whose numbers were already taken (owner's D-520 to D-537)

**Reader:** the people who build TrialBox

The integrator numbers the owner's rulings. On 2026-11-16 it gave the numbers D-520 to D-537 to eighteen rulings.
Seventeen of those numbers already belonged to decisions on master (the fix cards of 2026-11-12 and 2026-11-13:
`docs/decisions/D-520-reject-key-value-free.md` to `D-537-every-name-in-a-backup-has-its-bytes.md`).

- A number belongs to whoever has it on master (the registry's rule), and `tools/decisions_index.py --check` fails
  when one number has two texts. So these rulings have no `D-nnn-<slug>.md` file and no registry row of their own.
- Their text is kept here so that it is on master. This file's name does not start with `D-`, so the index does not
  read it.
- The one free number, D-526, has its own file (`docs/decisions/D-526-superseded-the-same-day.md`). The rulings
  D-503 to D-519 were free too and have one file each.
- Until the integrator gives these rulings new numbers, cite one as "the owner's ruling D-5nn of 2026-11-16". On
  master, D-847 to D-850 and D-852 already cite the owner's D-521 and D-524 this way.
- A bare "D-520" to "D-537" in code or a test means the decision in the table's last column, not the ruling.

Every ruling below is the owner's, numbered and relayed by the integrator, dated 2026-11-16. The wording is the
integrator's record of it.

| Owner's number | The ruling | The same number on master is |
| --- | --- | --- |
| D-520 | Recovery (escrow) shares for a TPM-sealed key-encryption key are approved (D-894 lands). | the rejected-row key (NEW-B-1) |
| D-521 | The rule that REDCap is never downloaded by a session is lifted for testing only, in lane E's private container. Nothing of REDCap's source, SQL or text enters the repository, a PR, CI, an image, the bucket or the external worker. | the OMOP load refuses non-western years (NEW-B-2) |
| D-522 | Lane E may push its REDCap fix cards (our code and synthetic tests only). | the restore hold (NEW-B-3) |
| D-523 | Lane W restarts now (lifts "after PoC-1"). | the ingest follows a running run (NEW-PERF-2) |
| D-524 | REDCap 13.7 is a supported version (the hospital's production version). | the step engine removed (NEW-ARCH-2) |
| D-525 | The box-rehearsal check `rehearse-result` becomes a required check; the owner sets it in the repository settings. | derived generations readable (NEW-B-4) |
| D-527 | The plan's build dates are removed and the freeze of plan 33 section 3.2 is lifted: every card may be built now, ordered only by what it depends on. | a number too long is a rejected row (NEW-B-6) |
| D-528 | Terminology: code systems are loaded onto each box at install by a loader with a manifest. The site's own code lists are the primary source and never enter the repository. NHI open data may ship with attribution. LOINC, WHO ICD-10 and ATC are loaded at install and not committed. (Amended by the owner's D-529.) | a delta row left out is gone (NEW-B-7) |
| D-529 | Public-domain US government code data (ICD-10-CM, ICD-10-PCS) may be committed and shipped, each with a licence-register row. | no future snapshot (NEW-PERF-3) |
| D-530 | The Windows P-0 media: the public pre-release points to upstream sources for GPL/LGPL programs and is deleted after P-0. P-0 does not turn BitLocker on on the owner's personal PC (moves to P-10). No second-computer check in P-0 (moves to P-14). | a reference-data outage does not hold the night (NEW-B-8) |
| D-531 | `omop.tb_record_event`'s before-images of an opted-out patient are kept hidden until retention and blanked at retention (the rule of D-513). `omop.tb_record` is a keep entry. `tb_record.extra` gets the same check. It supersedes the owner's D-526 of the same day. | publish promotes its generation (NEW-B-10) |
| D-532 | The screening log of a never-consented patient: the row and its number are kept, the pseudonym is replaced by a random token, the investigator's free text goes. A trial subject's rows stay. | the job lease (NEW-B-11) |
| D-533 | No receiver for REDCap's Data Entry Trigger now; revisit after the pilot. | the scale gate's dense profile (T-687) |
| D-534 | The REDCap specification stays out of the repository in every form. | the limits lint lists every timeout (NEW-B-12) |
| D-535 | Incremental backup with restic is approved on conditions: the repository password is a sealed box key covered by the escrow shares; the target holds ciphertext only; restore is rehearsed in the box rehearsal; restic is pinned in the offline media and the licence register. | first-load completeness (NEW-B-13) |
| D-536 | No supervised remote session into a hospital box for the pilot; revisit after the pilot with the hospital's IT. | ATC is the ATC system (NEW-B-16) |
| D-537 | The integrator judged an outside review of master `828cb3d3`; its three lists are below. PR #813 stays parked. | every name in a backup has its bytes (NEW-B-17) |

## The owner's D-537: the outside review of master 828cb3d3

**Adopted now:**

- its CI findings, as input to lane D;
- no self-hosted runner while the repository is public;
- the TFDA pre-fill rule, checked against our design;
- an independent check of the masker with an open-source de-identification tool, in measurement only;
- shadow mode with an effectiveness report, as a design card;
- provenance on every AI output, as a design card.

**Build later (in the plan, `docs/plan/42-plan-2026-11-16.md` section 4):**

- ICH M11 / USDM with CDISC's rules engine;
- a FHIR validator as a separate process;
- an HL7 v2 library and an integration engine, when a site needs them;
- FHIR-to-CDISC mapping for eSource;
- a trial-retrieval A/B;
- a load-test tool;
- a published Taiwan evaluation set.

**Declined:**

- an MCP endpoint;
- a sponsor A2A interface;
- an ePRO app;
- an identity provider inside the box;
- prompt-optimisation and RAG-scoring tools.

## A fact the owner gave with these rulings (2026-11-16)

The charts at the pilot hospital, and in Taiwan generally, are mainly in English on a zh-TW site. It is a fact, not a
ruling, and has no number. It bears on the gold set (D-517: English first, then zh-TW) and on the masker's check.
