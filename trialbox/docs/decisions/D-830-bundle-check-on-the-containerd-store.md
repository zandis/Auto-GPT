# D-830 bundle-check knows a pulled image on the containerd store; make_bundle says the space it needs

- **Task:** BUNDLE-CONTAINERD, the integrator's reds of 2026-11-15 from lane G's GPU-box bundle build (#639)
- **PR:** this branch (`agent/BUNDLE-CONTAINERD-check-matches-either-store`), stacked on #704 (D-828)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-570 (either image store), D-828

## Decision

1. `bundle-check` gives `bundle_problems` the local image's Id, its repo digests and its platform. A digest matches
   a passing entry's repo digest (the index the registry image was pinned by before its scan) on that entry's
   platform only. On the containerd store a pulled image's Id is its index digest, while the gates record its
   config digest: authelia, caddy, hapi and vllm read "not a passing image" though each passed.
2. `make_bundle.sh` runs `tools/bundle_space.py` before the first save: the images' docker size plus models, with
   10 % and 512 MB margin, in the staging folder (`$TMPDIR`) and the `--out` folder (twice when on one disk). Too
   little stops the build (exit 2) naming the size, the folder and `TMPDIR` / `--out`.

## Test

`tests/unit/test_bundle_check_containerd.py` (before, 4 failed), `tests/unit/test_bundle_space.py` and the new
disk case in `tests/unit/test_release_bundle.py`: all pass after.
