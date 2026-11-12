# D-622 One dated entry may accept every finding of one package in one third-party image

- **Task:** VLLM-HEADERS (the owner's ruling of 2026-11-12, given in the build session)
- **PR:** this branch (`agent/VLLM-HEADERS-one-package-entry`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-186 (the allow-list: a finding is accepted only by a written, dated entry), D-340 (dated
  per-image entries for the third-party images)

## Context

The pinned model server image, `vllm/vllm-openai` v0.32.0, carries Ubuntu's kernel headers package
`linux-libc-dev 6.8.0-147.147`. The headers are build-time files; no kernel of that image runs on a box. Every
time the vulnerability database gains kernel findings the gate fails on them: on 2026-11-12 a fresh database
added 135 ids at once and the image gates of the merge train went red on both platforms, with every image of
ours passing. The allow-list already held 257 entries for this one package in this one image, one per id, all
with the same reason.

## Decision

Written when the card is complete.
