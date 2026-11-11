# D-449 S2b reads the vector store behind the flag `vec.s2b` (off): the pinned snapshot's notes or the on-the-fly path, recorded per patient

- **Task:** T-203b (`docs/plan/28-master-plan-v6.md` §6.2, wave 3; part b of T-203, TB-ASSESS-01; safety core)
- **PR:** this branch (`agent/T-203b-s2b-vector-store`)
- **Date:** 2026-11-11
- **Status:** proposed (in review)
- **Closes:** CR-068 (part: screening reads the vector store)
- **Builds on:** D-439 / T-203a (schema `vec`, `VecStore.search`), D-429 / T-607 (the embedder is chosen at G1; the
  S2b threshold is refitted after it), T-305a (a job reads the snapshot it pinned), D-378 (only `tb_lake` reads
  `vec`), D-90 (S2b below never excludes on an inclusion), D-147 (opt-out)

(Text in progress: the decision is written in full before the pull request leaves draft.)
