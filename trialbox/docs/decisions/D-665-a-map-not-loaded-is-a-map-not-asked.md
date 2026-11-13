# D-665 A reference map that is not loaded is treated as one that could not be asked

- **Task:** NEW-B-24 (a finding of the review of NEW-B-19 / D-660, placed by the integrator on 2026-11-13; with
  lane E's two functions of #474)
- **PR:** this branch (`agent/NEW-B-24-maps-present-before-a-load`), cut from origin/train/8 with lane E's #474
  (`5c0f3ccf`) merged in
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-593 (the mapper asks the box's reference data; "no entry" and "could not be asked" are counted
  apart), D-530, D-538 (a night's rows that could not be asked are read whole on the next delta night), D-660 (a
  first load whose rows could not be asked is held), lane E's `Mapping.concept_maps` and
  `refdata.has_map_or_none` (#474)

## Context

A night or a first load that runs **before the reference pack is loaded** asks a map that holds nothing. The
reference data answers "no entry" for every code. That is counted (D-580) and published, and nothing asks again:
a delta night reads only rows that changed, a first load reads its history once. When the pack is loaded later,
those rows stay without their mapped codes. D-538 and D-660 closed this for an outage ("could not be asked");
"not loaded" slipped past both because it looks like an answer.

## Decision

1. **The first time a map the mapping names answers "no entry", the load asks whether that map is loaded at
   all** (`adapter.pipeline.reference_maps`, which the night and the back-fill give the mapper). If it is not,
   the map is treated from then on in that run as one that could not be asked: the answer is None and the row
   is counted under `<map>:unavailable`.
2. **What then happens is what D-538 and D-660 already decide.** A night is not held and reads the table whole
   on the next delta night, until the pack is loaded. A first load is held before anything is published and,
   run again, reads its source again.
3. **Nothing holds or warns at the start, and nothing is asked of a site that does not need the map.** A
   mapping names a map for the sites that have such rows (ICD-9-CM years). A site without them never reaches
   the question and is never told to load a pack. For the integrator's question, "which of None and False
   holds the load and which only warns":
   - `False` (not loaded): never holds by itself. It makes the rows that need the map count as not asked; a
     first load with such rows is then held at its gate (D-660); a night goes on and heals (D-538).
   - `None` (could not be asked whether it is loaded): the "no entry" cannot be checked, so it is not taken for
     an answer: that row is counted as not asked, and the next code asks again. (Taken for an answer, the code
     would be published as "no entry", remembered so by the mapper for the rest of the run, and never asked
     again: shown by the reviewer on the real store, with a database that failed between the two questions.)
4. **The log says it once per run and map**: which map is not loaded and what follows; never a code. **A first
   load held for it says so in its reason**: "The reference map from X to Y is not loaded: load the reference
   pack, then run the back-fill again", not D-660's "when the reference data answers" (an outage to wait for).
5. **With no database configured nothing could be loaded**: answered as before ("no entry", D-593). A box always
   has its database.

## Consequences

- A box that takes its first nights before its pack is loaded reads the affected tables whole on each delta
  night until the pack is in (D-538's cost), then heals by itself. **If the pack is never loaded, this goes on
  for as long as the feed has such rows**: a whole read of the table and three log lines every delta night (the
  map that is not loaded, the count, D-538's line). The night's own D-538 line still says "the reference data
  did not answer"; the line before it names the cause.
- **The mapper asks by source system, not by map.** A source with two maps, one loaded and one not, is "not
  asked" for both once a code has no entry at all, and before that a code with an entry in the loaded map is
  answered from it (so the other map's gap is not seen for that code). No mapping shipped has two maps of one
  source; a mapping that gets one needs this looked at again.
- The first row that needs such a map is counted as not asked too: the reference data's "no entry" for it is
  replaced before the mapper sees it.
- The question costs one query per map and run, and only when a code got "no entry".
- A map that is loaded but really has no entry for a code is "no entry" as before (counted, published).
- Tests that stand in for the reference data with one function now meet a second question when their stand-in
  says "no entry": one stand-in of NEW-B-19's tests answers it (its pack is loaded).

## Not decided here

- A doctor line "the mapping names a map that is not loaded" (lane D's check of the reference data).
