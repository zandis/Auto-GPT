# D-1357 A PRODUCTION box on the bench host carries the bench mark (H116)

- **Task:** lane H, card H-116 (the owner's ruling, relayed as 7124664930; the design agreed as 7124901315)
  · **Date:** 2026-11-24
- **Status:** proposed (the integrator gives the registry row when it merges)
- **Builds on:** H-106 (several test boxes on one host, D-none: its card page), H-94 (D-1091, the five kinds a PoC box
  stops for), D-127 (a box is PRODUCTION unless set otherwise)

## Decision

1. The owner's "validation mode for real data on the bench" is a **PRODUCTION box with a mark**, called **BENCH**,
   not an environment. `TB_ENV` stays `PRODUCTION`, so every rule that keys on PRODUCTION holds on it unchanged and
   no PoC leniency (D-1091) ever applies. "VALIDATION" is not used: it is already a PoC environment, on which the
   install, start and update paths warn where PRODUCTION stops, and the gateway lifts its daily limits.
2. The mark is shown everywhere as **"PRODUCTION · BENCH (real data, bench host)"**: on every console page (the
   banner and the footer), in `trialbox doctor` (a standing WARN line no setting turns off) and in the install's last
   lines.
3. **The mark is the install option's only.** `deploy/install.sh --bench` writes it into the box's own record,
   `deploy/site/bench-box.env` (`tools/trialbox/benchbox.py`), after `TB_BENCH=1` in `deploy/.env` beside
   `TB_ENV=PRODUCTION`, and only once the install is past every refusal that says nothing was changed: a refused
   install leaves no mark. The record is written by root (the installer), mode 0644, fsynced and renamed into place, and
   carries the install's trace: its first line, the folder it was written for, the time. It is checked at every
   install, at every start (`deploy/settings_guard.sh`, before the systemd unit and `tools/apply_update.sh` start
   the stack) and by doctor. A mark the option did not write is refused: `TB_BENCH` in the caller's environment (the
   install refuses to run), `TB_BENCH` in deploy/.env with no record, a record that is a link or not a regular file,
   owned by another user, writable by group or others, without the install's trace, or written for another folder.
4. **The one thing the mark changes** is H-106's "one box per host": test boxes may run beside a bench box. The
   container engine's listing (`tools/trialbox/testbox.py boxes`) names a box whose mark holds `bench`; a test box
   installs beside it, a PRODUCTION install with the mark goes on beside test boxes. A box whose mark is refused
   counts as PRODUCTION, and H-106's refusals both ways stand: an unmarked PRODUCTION box keeps one box per host.
   A bench box is the host's ordinary project (`trialbox`, port offset 0); test boxes beside it share no volume,
   network, published port or secrets volume with it (the third kind in H-106's invariant).
5. **Refused** on a box that is not PRODUCTION (`--bench` with `--environment TEST` or `VALIDATION`, or a box whose
   deploy/.env says so), on a test box, on a rehearsal box, and on a box with a **sending identity**: a mail relay
   that is not on the host (`SMTP_HOST` other than empty, `localhost`, `127.0.0.1`, `::1` or the test stack's sinks)
   or a relay login (`SMTP_USER`). A bench box sends no mail outside the host. A relay already in deploy/.env is
   refused before the mark is written; one the site's settings bring is refused when deploy/.env is written, before
   the stack starts.

## The protections a bench box keeps, each with its PRODUCTION test

The mark is read only where it is written, checked or shown
(`tests/unit/test_bench_box_h116.py::test_the_mark_changes_no_production_rule`: `TB_BENCH` appears in seven files,
named one by one, none of them a protection, and `environment_name` stays PRODUCTION). So each protection's
PRODUCTION test holds for a bench box as written:

| Protection | Its PRODUCTION test |
| --- | --- |
| encryption at rest: the site keys sealed under a KEK | `tests/unit/test_host_baseline.py::test_check_host_fails_on_plain_site_keys_in_production`; `tests/unit/test_audit_integrity.py::test_init_key_in_production_needs_the_kek` |
| the audit chain | `tests/unit/test_audit_integrity.py::test_a_removed_and_recomputed_line_fails_against_the_signed_head` |
| no egress | `tests/unit/test_egress_guard.py::test_internal_and_odd_addresses_are_refused`; `::test_http_only_in_dev_and_test` |
| the key handling | `tests/unit/test_audit_integrity.py::test_init_key_in_production_needs_the_kek` |
| retention and the backup off the box | `tests/unit/test_backup_schedule.py::test_in_production_a_box_with_only_local_targets_fails_and_stays_red` |
| the gateway's limits on patient mail and downloads | the limits read the site's settings and declared variables, never the mark: `tests/unit/test_bench_box_h116.py::test_the_mark_changes_no_production_rule` (the gateway is not among the seven readers) |
| no mail outside the host | `tests/unit/test_bench_box_h116.py::test_the_mark_is_a_production_box_s_with_no_sending_identity` |

## Not decided here

- A bench box beside a hospital's PRODUCTION box: there is none. A bench box is the bench host's one PRODUCTION box
  (the ordinary project), and a hospital's box keeps one box per host.
- Taking the mark off: a box is emptied and installed again without `--bench`; nothing removes the record in place.
