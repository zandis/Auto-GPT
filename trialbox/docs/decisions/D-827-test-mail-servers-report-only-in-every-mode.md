# D-827 the test mail servers are report-only in every mode

- **Task:** TEST-IMAGES, the integrator's red of 2026-11-15 from lane G's GPU-box build (#639)
- **PR:** this branch (`agent/TEST-IMAGES-report-only-in-every-mode`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-340 (every image a bundle carries blocks), D-348 (Mailpit)

## Decision

1. `make release-gates` in its default (block) mode failed on fixable findings in `axllent/mailpit` v1.33.1 and
   `greenmail/standalone` 2.1.15. Docker Hub on 2026-11-15: both are the newest releases (only Mailpit's `edge`
   is newer), so there is no patched tag to pin.
2. The images of `VULN_REPORT_ONLY` are report-only in every mode, as the integrator asked: their fixable
   CRITICAL/HIGH findings are recorded and shown, not failing. No bundle carries them (`make_bundle.sh` leaves the
   test compose file out; it refuses an image with a report-mode finding). No allow-list entry is added.
3. Every other image blocks in every mode, as before. Errors, unfixed and odd-severity findings still fail.

## Test

`tests/unit/test_test_images_report_only.py`: before, the two block-mode cases failed; after, all pass.
