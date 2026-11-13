# D-530 An outage of the reference data does not hold the night; the night says what it could not map

- **Task:** NEW-B-8 (two findings of lane E's review of the nightly ICD-9-CM map, D-593, handed to the night and
  capacity lane on 2026-11-12)
- **PR:** this branch (`agent/NEW-B-8-unmapped-wording-and-refdata-outage`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-593 (the mapper asks the box's reference data; a map that could not be asked maps nothing and
  the row is counted under `<map>:unavailable`), D-580 (the nightly counter of values the mapping could not use),
  D-271 (a held night), D-587, D-590

## Context

Two things were left to this lane.

**Should the night be held when the reference data cannot be asked?** Since D-593 a diagnosis written in
ICD-9-CM gets its ICD-10-CM code from the box's reference data during the night. When that data does not answer
(no database, a pack being loaded), the row keeps its ICD-9-CM code only and is counted. A criterion that asks for
an ICD-10-CM code then does not find the diagnosis: the engines' answer for that patient goes to "unknown" (the
record cannot show the condition), never to a decided "met" or "not met" that the mapped code would have changed
the other way without a person seeing it.

**The log's wording.** The night logged D-580's counter as "rows dropped: values have no look-up row with a code".
The counter has grown: it also holds rows kept without a value (a unit that was not read, a value implausible
without a unit: D-590) and the rows of an outage. "Dropped" is wrong for them.

## Decision

1. **The night is not held for an outage of the reference data.** A hold withholds every table of the night
   (new lab results, new bookings, withdrawals of consent that the lists must honour) for the sake of one code
   system's translation, and the cost of not holding is the safe one: unknown, shown as unknown.
2. **The night says it by name.** The log has a line of its own per table: how many rows, which map, that the
   codes were not mapped and stay so until the row is sent again or the next full load, and that the night is not
   held (`adapter.pipeline.unmapped_lines`). The rows are in D-580's counter under `<map>:unavailable`
   (`unmapped_codes.json`, the audit event's `unmapped`), as lane E built it.
3. **It is not self-healing on delta nights, and the line says so.** A delta night reads only rows that changed:
   a row that met the outage keeps its unmapped code until it changes or a full load runs. After an outage the
   operator runs a full load of the table; nothing is built here to do that by itself.
4. **The counter's line calls nothing "dropped".** "N rows hold a value the mapping could not use (M distinct
   values): the row is left out or kept without that value, by the mapping's rule". Counts and the counter's own
   names only, never a code.

## Consequences

- The wording of one log line changes; the file, the audit event and the batch row are unchanged.
- An outage that lasts many nights grows the count each night and is visible in the same places as unknown codes.
  It does not page anyone: the doctor check for the reference data (lane D's) is where a standing outage shows.

## Not decided here

- A full load started by the box itself after an outage ends (it needs to know which tables met it: the counter
  has that). A follow-up if outages turn out to happen.
- Whether a share of `:unavailable` rows above some limit should hold the night after all. Not without a number
  that comes from somewhere (OD-10).
