## Gate 1: what it guarantees, what calls it, what is still in the ratchet

On first extraction, `admit_presence` reads the whole eligibility item in English, Traditional Chinese or Japanese. It can release one named diagnosis, procedure or medication for this patient when the terminology agrees with the name and the complete predicate fits the passage. It accepts exact day or week look-backs. For a present-tense diagnosis it filters out explicitly resolved conditions. An explicit requirement for active disease goes to review because the engines count a missing status. A recorded human approval of the same passage, logic and code set also supplies evidence. Every release requires available terminology and a successful audit receipt.

The compiler locates the passage and its governing text before extraction. Alignment and retries keep that source even if the retry prompt contains only the child. Fresh criteria receive their final IDs before admission, so their audit receipts identify the criteria in the artifacts. When the evidence is insufficient, the criterion carries `presence_requires_review` and a question in the source language.

The AST check scans `libs/`, `services/` and the offline ruleset builder for IR construction, class and logic writes, reuse, mapping, publication and predicate generation. It compares individual statements with `tools/presence_bypasses.json`. When the detector changes, it scans the Git base with the same detector to distinguish newly discovered sites from newly introduced ones.

## Open for later slices

| Finding | Inventoried site | Work remaining |
| --- | --- | --- |
| 2 | `terminology/mapper.py`, `Terminology.map` | Independently verify the membership of mapped code sets. The shipped stroke set misses I61.9 and the rheumatoid arthritis set includes M06.4. |
| 5 | `service.py`, `Compiler.compile` | Bind incremental reuse to the complete governing passage so moving an approved child under a family-history heading triggers review. |
| 6 | `service.py`, `Compiler._approve` | Keep shared ValueSets pinned for untouched criteria when an edited extraction proposes different codes under an existing name. |
| 7 | `service.py`, `Compiler._approve` | Apply admission to the final edited class and logic before a note can become executable. |
| 8 | `tools/build_rulesets.py`, `offline` | Bind the rebuilt artifacts to the reviewed code sets and criterion decisions before carrying an approval forward. |
