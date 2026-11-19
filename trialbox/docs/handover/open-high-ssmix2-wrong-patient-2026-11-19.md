# Three wrong-patient faults of the SS-MIX2 reader, registered by lane H (card H-57, 2026-11-19)

**Reader:** the people who build TrialBox

Lane H keeps the findings register. On 2026-11-19 at 14:00 UTC the integrator posted two independent reviews of lane
J's SS-MIX2 reader (PR #1095, merged on train 98, head 5a4ee5f9 against base 0de6b1d0), by two different reviewers,
here reviewer A and reviewer B, and ruled: "The wrong-patient ones (the misnamed file; the supersession across
patients; the lab fallback key without the patient) join your lake-id red in rc1's scope: no tag without them. …
Lane H: register the wrong-patient ones High." Lane J has no findings file for these on master, so this page is their
source. It quotes the reviews; nothing here was measured by lane H. All three rows are lane J's to fix and are open
([findings.json](open-high-ssmix2-wrong-patient-2026-11-19/findings.json)). All data named here is synthetic.

The basis follows the register's words: `shown` where reviewer A reproduced the fault by running the reader,
`hypothesis` where reviewer B read the code and did not run it. Each cited line was looked up on master at a7d6562b
(`trialbox/services/adapter/sources/ssmix2/source.py`): every one is where the reviews put it, with no drift
(1674 and 1665 in the extended-storage scan, 1208 and 900 in the diagnosis supersession, 1565 the lab number).

## H57-01: a file named for another patient becomes the folder patient's note

Reproduced by reviewer A by running the reader; reviewer B names it at `source.py:1665`. Reviewer A, verbatim:

> trialbox/services/adapter/sources/ssmix2/source.py:1674 | An extended-storage file whose standardized name belongs
> to another patient is stored as a note of the folder patient. | Folder 10000001 holds
> 10000002_20261001_DSC-01_D1_20261001090000000_01_1.txt containing 患者2の退院サマリ, and the note row is mrn 10000001
> with that text.

## H57-02: a diagnosis number is one diagnosis for every patient

Reproduced by reviewer A by running the reader; reviewer B names the same family at `source.py:1208` and `:900`.
Reviewer A, verbatim:

> trialbox/services/adapter/sources/ssmix2/source.py:1208 | Supersession treats a 病名番号 as one diagnosis for every
> patient, so a delta tombstone of one patient's copy deletes the other patient's still-current Condition of that
> number, and a second patient's removal is omitted when that number is already tombstoned. | Patient 10000001's
> 20261001 snapshot still has DX0001 and patient 10000002's 20261002 snapshot drops it: rows since 2026-10-02 are only
> 10000002/DX0002, deleted_rows is 10000002/DX0001, and both patients' DX0001 produce the same Condition id.

## H57-03: the per-day lab fallback key has no patient in it

Read by reviewer B, not run. Reviewer B, verbatim:

> `services/adapter/sources/ssmix2/source.py:1565` The new per-day lab fallback key omits the patient, so distinct
> results can overwrite one another because the mapper hashes `lab_no` alone. Two patients with `ALL9` lab files on
> `20261001`, each with `OBX-1=1` and no `OBX-21`, both produce `ALL9@20261001-1`.

## Not registered here

The two reviews' other findings: also reported, lane J's to triage; the integrator asked lane H for the wrong-patient
ones only, so they have no rows.

## When these close

Lane H does not change these rows by hand. Each closes when its fix is on master and seen closed: lane J's fix moves
the state, and `--sync-states` carries a state written in a findings file into the register; see the register's head.
