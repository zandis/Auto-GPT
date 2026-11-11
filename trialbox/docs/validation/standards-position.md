# Standards position: IEC 62304, IEC 82304-1, ISO 13485

*Card T-215 (deep review REG-029, REG-027). Decision D-344. Status: living. No signature (D-311).*

TrialBox is not a medical device and makes no diagnosis (`docs/plan/intended-use.md`; TB-DS-16). None of these three
standards is required. This page says which ones TrialBox follows as good practice, how far, and what would make one
of them required.

| Standard | Edition | Position | Why |
| --- | --- | --- | --- |
| IEC 62304 | 2006 + Amd 1:2015 | **followed as good practice**, in a light form | It gives a recognised shape to the records a sponsor or a hospital asks for: classification, plan, SOUP, problems, configuration |
| IEC 82304-1 | 2016 | **adopted as guidance** for the product level | It is the product standard for health software that is not a device; it gives the pack a known frame for use requirements, validation, accompanying documents and post-market |
| ISO 13485 | 2016 | **not adopted**; a trigger is written (§3) | A device QMS is not needed for a non-device pilot; the QMS-lite of `qms-lite.md` (this folder) covers what the pilot needs |
| GAMP 5 | Second Edition, 2022 | followed (the VMP, `docs/plan/25-vmp.md`) | the validation frame the sites and sponsors expect |

## 1. IEC 62304 (light)

**Class.** The internal class of each path is in `software-safety-classification.md` (this folder, card T-654): the
screening core is class B, everything else class A. The research-profile module (condition C12 of the intended use) is
class A while it shows cited summaries to research staff only; it is classified again before a clinician ever sees its
output. This page does not repeat that record.

**The records, with their paths.** The five records the deep review asked for (REG-029), and where each lives:

| 62304 clause | Record | Path |
| --- | --- | --- |
| §5.1 Development planning | the development plan | `development-plan.md` (this folder, T-654) |
| §5.2 Software requirements | the user requirements and the functional specification | TB-PLAN-05 §5; `functional-spec.md` (this folder) |
| §5.3 Architecture, incl. SOUP and segregation | the architecture and the segregation argument | `docs/ARCHITECTURE.md`; `software-safety-classification.md` §3 (T-654) |
| §5.5 to §5.7 Verification | the CI suite and its results; the traceability matrix | `development-plan.md` §3 (T-654); `docs/plan/25-traceability.csv` |
| §6, §8 Maintenance, configuration and change | change classes, release records, the staged roll-out | `change-control.md` (this folder); `release-records/` |
| §7.1.3, §8.1.2 SOUP | the SOUP list, with purpose and known problems; the model weights are SOUP | `soup.csv` (this folder, T-654) |
| §9 Problem resolution | the problem log | `problems.csv` (this folder, T-654) |

**What is not done.** No 62304 clause is claimed as met by audit. The records are kept by the pull requests that
change the code; none is signed (D-311 B14).

## 2. IEC 82304-1 (guidance)

Adopted as guidance, not claimed. How its parts map to TrialBox:

| 82304-1 part | TrialBox |
| --- | --- |
| §4 Product requirements (use requirements, intended use) | `docs/plan/intended-use.md`; TB-PLAN-05 §5 |
| §5 Software life-cycle processes (points to 62304) | §1 above |
| §6 Product validation | `docs/plan/25-vmp.md`; `docs/VALIDATION.md` |
| §7 Identification and accompanying documents | `release.json`; the about page; `docs/USER_GUIDE.md`; `docs/RUNBOOK.md`; the NOTICE page |
| §8 Post-market activities | the problem log; the drift chart and canary; the periodic review (VMP §8); support (`docs/RUNBOOK.md` §7) |

## 3. ISO 13485 trigger

ISO 13485 becomes necessary, and this page is reopened, when any of these is true:

1. A module is claimed to diagnose, to decide eligibility on its own, or to recommend a treatment (TB-DS-16 §4,
   TB-PLAN-06 §0.3 item 3).
2. The research-profile module, or any output, is shown to clinicians for the care of a patient.
3. A site, a sponsor or a regulator asks for TrialBox as a device, or for a device QMS certificate.

Japan's QMS ordinance (MHLW Ordinance No. 169) and Taiwan's medical-device QMS rules are both aligned with ISO 13485,
so one QMS would serve both sites. Until a trigger fires, `qms-lite.md` (this folder) is the quality system.
