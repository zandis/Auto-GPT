## Gate 1: what it guarantees, what calls it, what is still in the ratchet

On first extraction, `admit_presence` reads the whole eligibility item in English, Traditional Chinese or Japanese. It can release one named diagnosis, procedure or medication for this patient when the terminology agrees with the name and the complete predicate fits the passage. It accepts exact day or week look-backs. For a present-tense diagnosis it filters out explicitly resolved conditions. An explicit requirement for active disease goes to review because the engines count a missing status. A recorded human approval of the same passage, logic and code set also supplies evidence. Every release requires available terminology and a successful audit receipt.

The compiler locates the passage and its governing text before extraction. Alignment and retries keep that source even if the retry prompt contains only the child. Fresh criteria receive their final IDs before admission, so their audit receipts identify the criteria in the artifacts. When the evidence is insufficient, the criterion carries `presence_requires_review` and a question in the source language.

The AST check scans `libs/`, `services/` and the offline ruleset builder for IR construction, class and logic writes, reuse, mapping, publication and predicate generation. It compares individual statements with `tools/presence_bypasses.json`. When the detector changes, it scans the Git base with the same detector to distinguish newly discovered sites from newly introduced ones. The ratchet holds **32 sites** (26 in the criteria compiler, 2 in the criterion contract, 1 each in the ruleset loader, the EDC service, the orchestrator and the offline builder); this round added none.

## The owner's ruling (2026-11-22) and what ships

The strict rule stands. The compiler proposes; a person approves each held line once; that approval is a recorded decision on the exact text, and `admit_presence` releases the line only while the record still matches. Decomposing alternatives and time windows is for later slices.

A recorded approval (`services/criteria_compiler/ir_extract/presence_approvals.py`) binds the protocol, the criterion ID and kind, the exact text and its SHA-256, the class, the coded logic, the notes question, the compiler's flags, and each coded ValueSet's codes (their count and the SHA-256 of the sorted `system|code` lines) and code families. The text is compared code point by code point: no whitespace folding or trimming, no NFC, NFD or NFKC normalisation, no case folding. Any change, one character included, holds the line again. No approval releases a proposal the compiler flagged as negated, invalid, unread or already held. A malformed approvals file refuses the compile with one message key, `compile.presence_approvals_invalid` (en, zh-TW, ja); nothing falls back to releasing.

Each of the four synthetic protocols ships a file of labelled approvals in `services/criteria_compiler/ir_extract/shipped_approvals/`: GZQO 8, AD-MAB 3, NEUR-COH 2, RA-JAK 8. Each entry carries the label "synthetic demonstration approval, not a clinical sign-off", recorded by "shipped with the synthetic protocol", dated 2026-11-22. A shipped approval applies only to those four protocol IDs and only on a test box (`TB_ENV` DEV or TEST, read with `tb_common.config.environment_name`; unset is PRODUCTION). It is refused on PRODUCTION and VALIDATION.

The label travels with the line: the criterion's review record carries `released_by: recorded_approval; approval_label: …; recorded_by: …; actor: …; recorded_at: …; text_sha256: …`; the review report (`review.html`, `review.xlsx` summary) shows it; the audit receipt `compile.presence_admitted` has `basis: recorded_approval` and the label; and a person's approval of the draft keeps it in the approved ruleset, under the person's own comment.

A person records an approval of one exact line with `python -m tools.record_presence_approval --ruleset-dir DIR --criterion ID --actor NAME --approvals FILE --audit-dir DIR`. It writes the audit event `compile.presence_approval_recorded` (actor: the person, with the label) before the record, and records nothing when the event cannot be written.

| Of the 25 presence criteria of the four protocols | GZQO | AD-MAB | NEUR-COH | RA-JAK | All |
| --- | ---: | ---: | ---: | ---: | ---: |
| Released by the plain rule | 2 | 0 | 0 | 0 | 2 |
| Released by a shipped synthetic approval | 8 | 3 | 2 | 8 | 21 |
| Still held | 1 | 0 | 0 | 1 | 2 |

## Still held, with no shipped approval

| Criterion | Text | Why no approval ships |
| --- | --- | --- |
| GZQO-EXC-05 | Prior or planned bariatric surgery. | "Planned" is a hypothetical: the coded logic can see only surgery that happened. |
| RA-JAK-EXC-04 | Positive interferon-gamma release assay (IGRA) within 1 year without tuberculosis preventive therapy. | The line is negated in part: "without preventive therapy" is read from the absence of a record. |

A person may still approve either line with the tool above; the shipped files will not.

## Open for later slices

| Finding | Inventoried site | Work remaining |
| --- | --- | --- |
| 2 | `terminology/mapper.py`, `Terminology.map` | Independently verify the membership of mapped code sets. The shipped stroke set misses I61.9 and the rheumatoid arthritis set includes M06.4. |
| 5 | `service.py`, `Compiler.compile` | Bind incremental reuse to the complete governing passage so moving an approved child under a family-history heading triggers review. |
| 6 | `service.py`, `Compiler._approve` | Keep shared ValueSets pinned for untouched criteria when an edited extraction proposes different codes under an existing name. |
| 7 | `service.py`, `Compiler._approve` | Apply admission to the final edited class and logic before a note can become executable. |
| 8 | `tools/build_rulesets.py`, `offline` | Bind the rebuilt artifacts to the reviewed code sets and criterion decisions before carrying an approval forward. |

## Next slices, in order

1. A console screen for approvals: show the held proposal (its logic and codes, which the held draft does not keep today) and record a person's approval in the same form, audited. This round ships the tool only.
2. The compile reads a site's recorded approvals (a person's, from the tool or the screen) as it reads the shipped ones; today only the shipped files are read, so a person's record takes effect where a caller passes it.
3. Retries and recompiles, review edits (findings 6 and 7) and incremental reuse (finding 5) pass through the gate.
4. The offline builder (finding 8) and the terminology mapper (finding 2).
5. Decomposing alternatives and calendar windows, so fewer lines need a person.

No decision record was added in this round: the rows the gate cards may use in `docs/decisions/REGISTRY.md` were not certain, so the integrator numbers one if it is wanted.
