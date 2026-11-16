# D-1031 The before-images of a record event are kept hidden until retention

- **Task:** an owner's ruling, numbered by the integrator and relayed by the integrator
- **Date:** 2026-11-16
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-16)
- **Number:** Relayed to the lanes on 2026-11-16 under the number D-531, which was already taken by "The publish
  promotes the generation it built, or nothing"; cite it as D-1031.

## Ruling

1. `omop.tb_record_event`'s before-images of an opted-out patient are kept hidden until retention and blanked at
   retention (the rule of D-513).
2. `omop.tb_record` is a keep entry.
3. `tb_record.extra` gets the same check.
4. It supersedes D-526 of the same day.

## Where the wording comes from

The integrator's session.

## Used by

The erasure registry (lane C2).
