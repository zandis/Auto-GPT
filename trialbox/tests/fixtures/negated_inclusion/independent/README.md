# Independent line sets for the inclusion hold

Labelled synthetic inclusion-criterion lines written on 2026-11-19 by four testers who had not seen the code
(or, where the file name says `informed`, who had read one recogniser's data file and wrote against it). They
exist so that the next change to the hold is measured on lines its author did not write. Every line is
synthetic; none comes from a patient record or a real protocol.

Each file is tab-separated with a header row and is read by `python -m tools.negated_inclusion_score <file> --rows`
(the scorer arrives with card 10A-1c, D-1246). Columns: `text`, `concept` (the coded concept's name), `expect`
(`held`: the concept is not a present fact about this patient, so the line must be held for a person; `runs`: a
plain assertion), and where given `lang`, `hold_class` (the tester's own class name), `synonyms`, `others`
(other concepts named on the line, separated by `;`), `domain`.

| File | Lines | Written how |
| --- | --- | --- |
| `tester1_round1.tsv` | 295 | blind; negation, prefixes, uncertainty, hypotheticals, family, resolved |
| `tester1_round2.tsv` | 73 | after reading the cue rules of 10A-1c's first head |
| `tester2_round1.tsv` | 316 | blind; wider than negation: stopped drugs, plans, other persons, headings, marks |
| `tester2_round2.tsv` | 104 | aimed at what round 1 showed weak |
| `tester3_blind.tsv` | 348 | blind; 150 of them realistic plain assertions |
| `tester3_informed.tsv` | 85 | after reading the 10A-1d draft's data file |
| `tester3_clauses.tsv` | 12 | a non-fact in a second clause |
| `tester4_informed_held.tsv` | 410 | with the 10A-1d draft's code open; every line labelled `held` |
| `tester4_realistic_runs.tsv` | 100 | realistic plain assertions, not tuned to any rule |
| `tester4_arguable.tsv` | 20 | lines the tester would not label with confidence; not counted anywhere |

## What was measured on them (lines that must be held but run as present)

| | tester 1 (186 / 57) | tester 2 (194 / 73) |
| --- | --- | --- |
| master 73835e62 | 60 / 53 | 121 / 62 |
| 10A-1c at 65f0753c (D-1246) | 0 / 0 | 71 / 40 |

Tester 1's 73 misses were shown to 10A-1c's author and are also that card's regression fixtures; no other line
here was shown to that author. The 10A-1d draft (D-1248, not adopted) was measured on all of them; its record
gives those counts.

## Rules for using these files

- A count is a count on the named file, never a property of the reader. Write "0 of 186 on tester1_round1",
  not "no misses".
- Once a line has been shown to the author of a change, it measures nothing about that change. Say which files
  the author had seen. For a new measurement, have new lines written; do not tune to these and then quote them.
- The labels are one tester's judgement. A label believed wrong is discussed and changed in its own commit with
  the reason, never silently.
- Do not add lines taken from a real record or a real protocol.
