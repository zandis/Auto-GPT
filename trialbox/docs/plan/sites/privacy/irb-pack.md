# IRB pack (倫理審査用資料 / IRB 送審資料)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-04 |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| For | the PI, when a committee asks how TrialBox handles patient data |
| Status | Draft. No committee step is on this plan (D-311): CGMH is covered by the owner's CGRD approval; the Japan committee is the partner physician's own matter. This pack is what the PI hands over if asked. |
| Builds on | `docs/plan/design/14-ethics-pack.md` (the older pack, parts A to J); its §4 notices are replaced by TB-PRV-05 |

## 1. What goes in

| Part | Content | Where |
| --- | --- | --- |
| 1 | Protocol text: one paragraph on the tool, for the study's own protocol | §2 below |
| 2 | Data-flow figure | §3 below |
| 3 | The one-pager "what this system does with charts", rendered from the site's settings | `python -m tools.onepager --settings deploy/settings.yaml --lang ja` (or `zh-TW`); TB-PRV-06 |
| 4 | The opt-out notice | TB-PRV-05 |
| 5 | Questions committees ask | §4 below |
| 6 | Screening-log columns | §5 below |
| 7 | Record of processing and DPIA, if the committee asks | TB-PRV-01, TB-PRV-02 |
| 8 | The incident plan, if the committee asks | TB-SITE-11 |
| 9 | The legal-basis memo, once counsel signs one | TB-PRV-03 (empty slot) |

## 2. Protocol text

> Candidate patients are identified with TrialBox, software installed on the hospital's own computers. TrialBox
> copies the hospital's records into a pseudonymised research database each night, reads clinical notes with a
> language model that runs inside the hospital, and prepares lists of possible candidates with the record passages
> they rest on, for the investigator's review. TrialBox does not decide whether a patient is eligible; the
> investigator does, under this protocol. Chart numbers are shown only to study staff with the right to see them,
> and every view is recorded. The treating physician is asked before any patient is contacted. Patients who opt out
> under the hospital's notice are no longer included from the next night.

## 3. Data-flow figure

```text
 hospital systems (EMR export, CGRD, SS-MIX2)
        |  nightly, inside the hospital network
        v
 [adapter] -- chart number -> pseudonym; the pid map is encrypted, its key under the KEK
        |                                  (D4 stays here)
        v
 research database (OMOP rows, lake snapshots, scrubbed notes)          (D3)
        |
        +--> local language model (inside the hospital; no cloud)        (D3)
        |
        +--> feasibility counts, small cells shown as <5 ----------------> (D1) study team, sponsor
        |
        +--> candidate lists with passages ------> investigator, coordinator (D3, signed in)
                     |
                     +--> reveal of one chart number (audited) --> treating physician asked --> patient
 audit chain: every view, reveal, export and mail, 10 years on the box
 nothing crosses the hospital boundary except counts the PI releases
```

## 4. Questions committees ask

| Question | Answer |
| --- | --- |
| Does patient data leave the hospital? | No. Only counts the PI releases, with small cells suppressed. The language model runs inside the hospital. |
| Can the vendor see patient data? | No. Support uses a bundle with no patient data (D-405); a remote session is supervised by the hospital (RUNBOOK §21). |
| Does a computer decide who may join? | No. The investigator decides under the protocol. Every output cites the record passage it rests on. |
| What does the model read? | Clinical notes, after names and identifiers are scrubbed, to find passages that relate to a criterion. |
| Who sees chart numbers? | Study staff with the right for that study; a doctor of another department only where the committee approved it (D-395). Every view is recorded. |
| What if a patient opts out? | From the next night the patient's records are no longer used for counts, lists or summaries (TB-PRV-05 N8). The notice is published only once the box keeps that promise on every path. |
| What happens after an incident? | The hospital's incident plan, fed by TrialBox's (TB-SITE-11): the vendor tells the hospital within 1 hour for a serious case. |
| Is it a medical device? | No. The intended-use statement is on every page and report (TB-IU-01). |

## 5. Screening-log columns

The screening log the box exports (record inventory R-03) is pseudonymous; the site's registry resolves the chart
number.

| Column | Meaning |
| --- | --- |
| Screening number | the study's own number for the screened patient |
| Pseudonym | the box's code; never the chart number |
| Study and protocol version | the ruleset and its release |
| Date listed | when the patient first appeared on a list |
| Criteria summary | counts of criteria matched, not matched and unknown; no verdict word |
| PI mark | the investigator's decision and its date |
| Treating physician asked | date and answer |
| Contact outcome | approached, declined, not reached, enrolled |
| Reason not enrolled | a category from the study's list |
| Consent date and form version | from the consent record (R-05) |
