# Software safety classification

*Card T-654 (deep review ENG-001). Status: living; changed in the same pull request as a change to the paths it
lists. No signature: D-311 B14 removed the signing step.*

TrialBox is not a medical device and makes no diagnosis (`docs/plan/intended-use.md`). This record still sorts the
code by IEC 62304's classes, as an internal working rule, so that the code whose failure could change what a
research team does gets more testing than the rest.

## 1. The classes

| Item | Internal class | Why |
| --- | --- | --- |
| The screening core (section 2) | **B** | A wrong "criteria not matched" can drop a patient from a candidate list, so a trial option is not offered. No injury follows from TrialBox alone: a principal investigator reviews every candidate, and every patient is screened again by the site before consent. The harm is "not serious" in 62304's terms, so B, not C. |
| Everything else (console pages, mail, reports, deliverables, operations tools, the demo) | A | A failure shows wrong text or stops a job. It cannot change a match on its own: every match goes through the core. |

The research-profile module (condition C12 of `docs/plan/intended-use.md`) is in class A today: it shows cited
summaries to research staff only. If a clinician ever sees its output, it is classified again first.

## 2. The class B paths

The same list as the safety-core block of `.github/CODEOWNERS` (information only, D-311). A pull request that
changes one of these paths says so in its template.

| Unit | Paths |
| --- | --- |
| Matching and the cascade | `services/matching/`, `services/orchestrator/scenarios/screen.py`, `services/orchestrator/scenarios/screen_cascade.py`, `services/orchestrator/scenarios/evaluate.py`, `libs/tb_common/reasons.py` |
| The criteria engines (IR, SQL, CQL) | `services/criteria_compiler/`, `schemas/criterion_ir.schema.json` |
| The guard | `services/guard/`, `services/model_guard/`, `libs/tb_common/phi_guard.py`, `services/lake/sqlguard.py` |
| Access control and sign-in | `libs/tb_common/authz.py`, `services/console/auth.py` |
| The prefill path | `services/edc/`, `services/console/edc_pages.py` |
| What the core rests on | `libs/tb_common/audit.py`, `services/adapter/pidmap.py`, `libs/tb_common/labvalue.py` |

## 3. Segregation

The class B units are separate modules with their own tests. Class A code reaches them only through their public
functions: the console asks the orchestrator for a screen and shows the result; it does not compute a verdict. The
guard and access control sit in front of every class A route that reads patient data. A class A failure therefore
cannot change a verdict; at worst it fails to show one. Where that argument is weak today (permission checks inside
the console's large page functions, deep review CR-024 and ENG-012), the fix is card work, not a change of class.

## 4. What class B adds

For each class B unit, on top of what every change needs (green CI):

1. **Unit acceptance criteria**: the rule each unit keeps (for example "unknown never excludes") is written as a
   test, and the property tests of `tests/unit/test_safety_properties.py` check it on generated inputs.
2. **Mutation testing**: the mutants of the deep review (§3.3 of `docs/reviews/2026-11-10-deep-review/04-engineering-quality.md`)
   are killed by unit tests (cards T-650, T-652).
3. **Engine agreement**: the SQL and CQL engines and the Python path give the same verdicts on the same lake.
4. **One automated adversarial review** of the pull request (D-311 owner answer 3). No named human reviewer.
5. **A design note** for a new unit: what it decides, from what inputs, and which test shows each rule. It sits
   in the module's docstring.

## 5. When this record changes

A pull request that adds a class B path, moves one, or changes what a unit decides updates the table of section 2
and the safety-core block of `.github/CODEOWNERS` together.
