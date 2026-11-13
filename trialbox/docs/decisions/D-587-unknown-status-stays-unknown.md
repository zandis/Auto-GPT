# D-587 A status code the map does not know is unknown for diagnoses, visits and bookings, and it is counted

- **Task:** NEW-DIN-7 (finding DIN-007 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan v7.2 section 5, lane E, wave 0)
- **PR:** this branch (`agent/NEW-DIN-7-unknown-status-unknown`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-275 (a code the map does not know is `unknown`, never the default: lab and order status), D-142
  (a suspected diagnosis is kept and never coded), D-580 (codes nobody knows are counted every night)

## Context

D-275's rule covered the status of a lab result and of an order. Three elements of the shared mapping still fell to
their default: a diagnosis whose `status` is a site's own code (`X`, `D`) became `active`, a visit type the map does
not know became out-patient (`AMB`), a booking status the map does not know became `booked`. A deleted or ruled-out
diagnosis under a site's code counted as active and could include or exclude; a cancelled visit under an unknown
code stood on today's list as booked.

## Decision

1. **Diagnosis.** A `status` the map does not know gives the diagnosis no clinical status and the verification
   status `unconfirmed`. The lake keeps an unconfirmed diagnosis out of the coded table as it does a suspected one
   (D-142): it includes nobody and excludes nobody, and a person can still see the record. A suspected diagnosis
   stays `provisional`.
2. **Visit.** A visit type the map does not know has the class `UNK` of the HL7 v3 NullFlavor code system, never
   `AMB`. The visit itself is kept (its day and department are known).
3. **Booking.** A booking whose status the map does not know is left out: nobody can say whether it stands, so it
   is not shown as booked. The row is counted.
4. **No code at all is as before**: an empty status is `active`, an empty visit type out-patient, an empty booking
   status `booked`. A feed that has no such column must not lose every row. Blanks around a code are not part of it.
5. **Counted.** Every such row is counted with D-580's counter under the name `column:<column>`, once a source row:
   in `completeness.json`, `unmapped_codes.json` and the night's audit event. That includes the lab and order
   statuses of D-275, which were `unknown` but uncounted. The night is not held by these counts.
6. **The night's structure check accepts such a diagnosis**: it asks for a clinical status or a verification
   status (`adapter/validate/validator.py`, one line; it asked for a clinical status on every diagnosis, and a
   share of unknown statuses would have held the night).
7. **The codes stand twice, and the mapping checks it.** A `known:` / `unknown_to:` list repeats the codes of the
   `map:` on the same column. A mapping where the two differ does not load. A site's own codes go in the table's
   `values:` map (blanks around a site's code are not part of it there either).
8. Two small additions to the mapping language carry this: the conditions `known: [codes]` (blank, or one of the
   codes) and `unknown_to: [codes]` (a code that is none of them). A site that uses its own status codes names them
   in the table's `values:` map, as before.

## What a site must know

- A status code missing from the site's `values:` map used to pass as active, out-patient or booked. It now shows
  as a count in the night's report under `column:status` or `column:enc_type`, with the code. The repair is one
  line in the site mapping.
- **One full load after this release, and one after the map is repaired.** A delta night re-reads only rows that
  changed, and a row the night does not send keeps its earlier record: a diagnosis loaded as `active` from an
  unknown code stays so, and a booking whose status changes to an unknown code on a delta night stays `booked`
  in the lake until a full load. "Never shown as booked" holds from the full load on. (Sending a tombstone for
  such a booking on a delta night is the pipeline's part, lane B: sent to the integrator.)

## Not in this card

- The Japanese and MIMIC mappings (`mapping/jp_core`, `mapping/mimic`) write their own status elements; they are
  read in NEW-DIN-4 / -5.
- OMOP: a visit of class `UNK` has no standard visit concept (concept 0); its source value is `UNK`, not the
  site's code (the code is in the night's count).
- The count's wording in the night's log ("rows dropped: values have no look-up row") also covers these rows,
  which are kept: `adapter/pipeline.py`, lane B.

## Consequences

- A diagnosis under an unknown status no longer includes or excludes anybody. Where the code was a site's word for
  "active", an inclusion on it is missed until the map is repaired; the count is what shows it.
- Today's list loses bookings with an unknown status; the count shows how many.
