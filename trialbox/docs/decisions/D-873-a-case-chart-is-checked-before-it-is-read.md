# D-873 A CASE job checks its subject against the opt-out register before the chart is read (ERASE-D, part 1)

- **Task:** ERASE-D, lane C2's backlog: the opt-out is checked before use. D-862 named the gap: the CASE scenario read and parsed the attached chart (`read_charts`: the parser and the text the model reads) before it resolved the chart number and refused an opted-out subject (`refuse_opted_out`, D-441). · **Date:** 2026-11-16
- **Decision:** the subject is resolved and checked first. An opted-out patient's chart never reaches the parser or the model; the refusal is audited as before (`case.opt_out_refused`, no pseudonym). The rest of the run is unchanged; the check at publish (`refuse_opted_out_now`) stays.
- **Left:** `objects:attachments` stays owed for the files kept with a job until retention (D-513), such as a chart attached for a patient who opted out after it came. `mail.send_keys` (queued or uncertain rows) and `outside:sitesetup_space_omop` are the next parts of ERASE-D.
- **Held by:** `tests/unit/test_a_case_chart_is_checked_before_it_is_read.py` (failing output on master kept: `erased-fail.txt`).
