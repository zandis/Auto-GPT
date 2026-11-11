# 10. The patient twin

The twin is one JSON document per study patient, `tb_patient_profile` v1 (D-440, card T-204). It is assembled with no
model from one lake snapshot and the stored derived rows (§8), and it is the one stable read for the profile cards:
the cited profile page (T-311a), physician annotations (T-312), setpoints and gaps (T-313) and the de-identified
export (T-316c). Code: `services/patient_profile/twin.py`; schema: `schemas/profile.schema.json`; read route:
`services/console/twin_api.py`.

**Layers.** `record` (birth date, sex, death), `timeline` (encounters, conditions, observations, medications,
procedures, reports and notes by type, in date order), `phenotype` (each coded problem once, with first and last date,
count, latest status), `derived` (the stored scores with their inputs), and `eligibility`, `setpoint`, `gap`,
`similarity`. A layer is `null` until its card builds it, never left out; a built layer says the version that built
it (`timeline@1`). No free text enters the twin: note text, report conclusions and names stay in the lake.

**Every item cites its source.** `source` holds the source table and row hash the adapter stamped on the lake row
(T-106b; for a row no mapping made, the lake table and no hash), the lake table, the lake row id and the date. A
derived score cites its stored row (`derived.score_row`, the row's fingerprint as hash) and each input row. The
document's `basis` names the lake snapshot and the mapping versions of its rows; a reader is told the version, the
snapshot it was built from and the newest snapshot that gave the same content (`as_of`).

**When it is built.** After every ingest that passed, for the study patients (each study's candidate pool and
candidate registry), on the snapshot that ingest published. A fact confirmed on the box enters the lake at that
publish, so it is in the twin after that one build. A build of the same snapshot gives the same bytes; a snapshot
that changes nothing for a patient writes no new version.

**Opt-out.** A build reads the opt-out register first: an opted-out patient is never assembled, and every version of
their twin is erased. The read route refuses an opted-out patient at once (404), before the next build. The opt-out
worker (T-206a) erases with `ProfileStore.erase(pid)`.

**Who reads.** `GET /api/v1/studies/{rs}/patients/{pid}/twin`: matrix row `profile.read` and the account's own right
to read the study's patients (`phi.view` and the delegation log), or an open break-glass grant for that patient; the
patient must be on the study's list or in its registry. Every read is one audit event `console.twin_view` (role,
layers, snapshot, version). The `setpoint` and `gap` layers go only to the study's PI (`profile.research_layers`).

**Retention.** Every version is kept (record R-29 of `docs/validation/record-inventory.md`): a new version is written
only when the content changes, and the old one is marked superseded, never rewritten. All versions of a patient are
deleted when the patient opts out. The twin is a copy of the hospital data copy (R-25) and is never exported as such.

**For the cards that build on it.**

| Card | What to call |
| --- | --- |
| T-311a cited profile page | `ProfileStore.current(pid)` for the document and its `as_of`, or the route above from the browser; cite from each item's `source` |
| T-312 annotations | read the twin as T-311a; an annotation's confirmed row reaches the twin through the lake at the next build, like any confirmed fact |
| T-313 setpoints and gaps | fill the `setpoint` and `gap` layers in `assemble` with a new layer version; the route already limits them to `profile.research_layers` |
| T-316c de-identified export | `ProfileStore.current(pid)` per exported patient, after its own opt-out and k checks; never the route |
