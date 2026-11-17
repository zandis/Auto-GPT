# The owner's rulings of 2026-11-16: the numbers they were relayed under, and their numbers now

**Reader:** the people who build TrialBox

The integrator relayed eighteen rulings of the owner to the lanes on 2026-11-16 as D-520 to D-537. Seventeen of those
numbers were already held by decisions on master. A number belongs to whoever has it on master, and the index allows
one text per number. So the integrator renumbered the seventeen: D-5nn became D-10nn, with the same last two digits.

- D-526 was free and keeps its number. D-1026 is not used.
- Each ruling has its own file `docs/decisions/D-10nn-<slug>.md` and a `merged` registry row.
- A bare D-520 to D-537 in code, a test or a record means the decision in the last column, except in the citations
  listed at the end of this page.
- D-1038 and D-1039 followed on the same day. D-1060 to D-1067 followed on 2026-11-17. The integrator's numbers continue from D-1068
  (lane E holds D-1040 to D-1059; lane H holds D-1100 to D-1119).

## The mapping

| Relayed as | Now | The owner's ruling | The decision on master that holds the relayed number |
| --- | --- | --- | --- |
| D-520 | D-1020 | Recovery shares for a TPM-sealed key-encryption key are approved | The key a rejected row is counted under holds no feed value |
| D-521 | D-1021 | REDCap may be downloaded for testing only, in lane E's private container | The OMOP path refuses a date whose year is not a western year |
| D-522 | D-1022 | Lane E may push its REDCap fix cards | A restore that is not complete holds the box's list jobs until a person releases the hold |
| D-523 | D-1023 | Lane W restarts now | On 409 the orchestrator's INGEST job follows the ingest that is running |
| D-524 | D-1024 | REDCap 13.7 is a supported version | The unused step engine, its outbox dispatcher and schema `wf` are removed |
| D-525 | D-1025 | The box-rehearsal check becomes a required check | A finished generation of the derived rows stays readable |
| D-527 | D-1027 | The plan's build dates are removed and the freeze is lifted | A number the mapping cannot compute is a rejected row, not the end of the night |
| D-528 | D-1028 | Terminology: code systems are loaded onto each box at install | On a delta night, a row the mapping now leaves out takes its earlier record with it |
| D-529 | D-1029 | Public-domain US government code data may be committed and shipped | A night dated after the site's today is refused |
| D-530 | D-1030 | The Windows P-0 media, BitLocker and the second-computer check | An outage of the reference data does not hold the night; the night says what it could not map |
| D-531 | D-1031 | The before-images of a record event are kept hidden until retention | The publish promotes the generation it built, or nothing |
| D-532 | D-1032 | The screening log of a never-consented patient | A running job holds a lease: one worker runs a job at a time, in every process |
| D-533 | D-1033 | No receiver for REDCap's Data Entry Trigger now | The scale gate's dense profile: about 500 records and 40 notes per patient |
| D-534 | D-1034 | The REDCap specification stays out of the repository | The limits lint lists every fixed wait, not only those above a minute |
| D-535 | D-1035 | Incremental backup with restic is approved on conditions | The first load says what a night says about its tables and its codes |
| D-536 | D-1036 | No supervised remote session into a hospital box for the pilot | A drug code is ATC only when its coding's system is the ATC system |
| D-537 | D-1037 | The outside review of master 828cb3d3, as the integrator judged it | Every file name in a backup is stored with its own bytes, also the second name of one file |
| D-526 | D-526 | Superseded the same day (by D-1031) | none: the number was free |

D-1037's file also holds its three lists (adopted now, build later, declined) and the fact that the charts at the
pilot hospital are mainly in English.

## Citations on master that mean the owner's ruling

These lines were written under the relayed numbers and mean the owner's ruling, not the decision that holds the
number. They belong to lane E, which corrects them to the new number. This change does not edit them. Found at
master `9d5853f3` by the number and the words around it; a line that cites the number without those words may be
missing.

| File | Lines | Written | Means |
| --- | --- | --- | --- |
| `docs/decisions/D-847-redcap-13-refusals-read-as-their-kinds.md` | 3 | D-521 | D-1021 |
| `docs/decisions/D-848-the-dictionary-has-redcaps-18-columns.md` | 3 | D-521 | D-1021 |
| `docs/decisions/D-849-a-group-users-token-works-with-a-group-link.md` | 3 | D-521 | D-1021 |
| `docs/decisions/D-850-the-instance-tool-fits-redcap-13-7.md` | 3 | D-521 | D-1021 |
| `docs/decisions/D-851-the-dictionary-keeps-calculations-and-places.md` | 3 | D-521 | D-1021 |
| `docs/decisions/D-852-redcap-13-is-supported.md` | 7, 15 | D-521 | D-1021 |
| `docs/decisions/D-852-redcap-13-is-supported.md` | 3 | D-524 | D-1024 |
| `docs/decisions/D-853-redcap-timeout-narrow-export-one-wait.md` | 7 | D-521 | D-1021 |
| `docs/decisions/D-853-redcap-timeout-narrow-export-one-wait.md` | 3 | D-527 | D-1027 |
| `docs/decisions/D-854-a-long-reason-is-refused-never-cut.md` | 3 | D-527 | D-1027 |
| `docs/decisions/D-855-lakefacts-is-tested-on-a-lake.md` | 3 | D-527 | D-1027 |
| `docs/decisions/REGISTRY.md` | 674 | D-524 | D-1024 |
| `services/rc_bridge/client.py` | 79 | D-521 | D-1021 |
| `tests/unit/test_dictionary_all_columns.py` | 3 | D-521 | D-1021 |
| `tests/unit/test_dictionary_keeps_calculations.py` | 6 | D-521 | D-1021 |
| `tests/unit/test_edc_018_timeout_narrow_retry.py` | 6 | D-521 | D-1021 |
| `tests/unit/test_group_bound_token.py` | 3 | D-521 | D-1021 |
| `tests/unit/test_redcap_13_refusals.py` | 3 | D-521 | D-1021 |
| `tests/unit/test_redcap_13_supported.py` | 4 | D-521 | D-1021 |
| `tests/unit/test_redcap_13_supported.py` | 1 | D-524 | D-1024 |
| `tests/unit/test_redcap_instance_on_13_7.py` | 3 | D-521 | D-1021 |
| `tools/redcap_instance.py` | 23 | D-521 | D-1021 |
