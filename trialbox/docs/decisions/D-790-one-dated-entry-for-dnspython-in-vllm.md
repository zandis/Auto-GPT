# D-790 One dated allow-list entry for CVE-2026-128089 (dnspython) in the vLLM image

- **Task:** VLLM-DNSPYTHON, the `images` check red on trains 16 and 17
- **PR:** this branch (`agent/VLLM-DNSPYTHON-one-dated-entry`)
- **Date:** 2026-11-15
- **Status:** accepted (the owner's yes, typed in lane D's session on 2026-11-15)
- **Builds on:** D-340 (the image gate blocks; dated per-image entries), D-622 (the vLLM image's entries)

## Context

The image gate found CVE-2026-128089 in dnspython 2.9.0 inside the pinned `vllm/vllm-openai` image (pulled in by
`fastapi[standard]` -> `email-validator`), fixed in dnspython 2.9.2. No stable vLLM image is built with the fix yet.

## Decision

1. One entry in `deploy/supply-chain-allowlist.yaml`: this id, package `dnspython`, image `vllm/vllm-openai` only,
   `review_by: 2026-12-10`, owner the security owner. No package-wide or image-wide entry.
2. Its reason can be checked: the flaw is in zone-file text parsing (`from_text` of WKS records); the model server
   never runs it (no vLLM module imports `dns`); no egress (D-340).
3. By 2026-12-10 the image moves to a patched vLLM release tag pinned by digest, or the entry is reviewed again.
4. `deploy/security/known-image-findings.md` names it in the vLLM row.

## Test

`tests/unit/test_vllm_dnspython_entry.py`: before, 3 failed; after, 4 passed.
