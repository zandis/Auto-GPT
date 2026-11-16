# D-881 qualify on a box names its code by the signed release tree

- **Task:** CODE-IDENTITY, #735's question (the integrator's yes of 2026-11-15, #639)
- **PR:** this branch (`agent/CODE-IDENTITY-qualify-names-the-release-tree`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-734 (qualify without git), D-737 (qualify --box), D-837 (the poc host profile)

## Decision

1. `sudo python3 -m tools.trialbox eval qualify --box` on the host (a release tree: no services/) starts qualify in
   the trialbox-py image itself: the release tree (/opt/trialbox/current, resolved) read-only as TB_RELEASE_TREE,
   TB_CODE_IMAGE the image's id, every path it found or was given mounted where it is (--out read-write), the
   gateway's network, the operator's TB_* settings passed by name. In the image (or a checkout) it runs qualify as
   before.
2. `code_identity.head` names `release:<sha256>` from TB_RELEASE_TREE when the root has neither git nor sums; with
   no tree, `image:<id>` from TB_CODE_IMAGE.
3. serving_record accepts an image-only identity only under TB_HOST_PROFILE=poc and says "no release tree: code named
   by the image digest" (lane G's direct route); on any other box it is a problem, as `unknown` is.

## Test

`tests/unit/test_qualify_code_identity.py`: before, 5 failed; after, all pass. test_box_qualify passes unchanged.
