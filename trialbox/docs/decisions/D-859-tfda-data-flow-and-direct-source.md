# D-859 Prefill names its data-flow section, and a field recorded directly in the EDC is never prefilled

- **Task:** EDC-023 (the integrator's go on lane E's check of the owner's ruling D-1037 item 1, on #639)
- **PR:** this branch (`agent/EDC-023-tfda-data-flow`), stacked on EDC-019 (#870)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-160 (EDC prefill), D-368 (what a draft is built under; the switch), D-434 (copy-assist), D-857

## The guideline

TFDA (Taiwan Food and Drug Administration), 「電腦化系統與電子數據應用於藥品臨床試驗指引」 (*Guideline on
computerised systems and electronic data in drug clinical trials*), 中華民國 113 年 5 月 (May 2024), §4 「關鍵概念之原則與
定義」, §4.7 「數據擷取」 (data capture), p. 18, as read from the PDF TFDA publishes:

- ¶2: data fields are not prefilled or filled in automatically, unless they cannot be edited and are derived from data
  already entered (the guideline's example is body surface area). The protocol names the data recorded directly in
  the data collection tool, as source data.
- ¶3: the protocol or its documents give a flow diagram and a description of each transfer of electronic data: type,
  format, source and destination, who can access it, when it is transferred, and every use (validation,
  reconciliation, verification, review). A data-management plan is strongly recommended.
- ¶4: transfers and derivations stay traceable through processing and analysis.

An outside review had read ¶2 as "a prefilled value needs a link to its source and a person's confirmation". The
text has no such exception. A value TrialBox drafts from a record is not shown in the sponsor's form while a person
enters data: a delegated person decides and signs it in TrialBox, and only then is it written. That is a transfer of
electronic data, which ¶3 and ¶4 govern. Default off, never overwriting a value someone else wrote, and the copy aid
stand as they are.

## Decision

1. **Prefill on names the data-flow section (¶3).** Turning prefill `on` needs `dataflow_ref`: the section of the
   protocol or data-management plan that describes TrialBox's transfer to the EDC. Without it the switch is refused
   (`edc.dataflow_ref`), and the refusal is audited. The reference is kept with the switch and its event row (edc
   schema version 7), shown in the audit line, and kept when the switch goes off, like the acknowledgement.
   `copy` (D-434) does not need it, because a person types each value and nothing is transferred electronically.
2. **A ready description for the sponsor.** `docs/validation/edc-data-flow.md` describes, in our own words, what
   ¶3 lists for TrialBox's transfer: type, format, source, destination, path, who, when, uses and traceability, with
   a table for the study's own answers. A sponsor copies it into its data-management plan; its section is the
   reference of item 1.
3. **A field recorded directly in the EDC is never prefilled (¶2).** The study keeps the protocol's list of such
   fields with the protocol section that names them (`PUT /studies/{rs}/edc/direct_source`, the map's permission;
   append-only `direct_source_event`, the newest row holds; a field outside the study's dictionary or a missing
   reference is refused). Then:
   - the map refuses a drafted row of a listed field (`edc.direct_source`, with the items);
   - the send holds back a value of a listed field that was signed before the list named it (`direct_source`, a new
     send result, shown on the console in three languages);
   - the copy-assist sheet leaves it out, without counting it as waiting, and says which fields it left out.

   An undrafted map row of such a field stays allowed.
4. **Changed expectations.** The test kit's acknowledgement and the console and demo switch-on forms now carry a
   data-flow reference. Without one, prefill on is refused, which is item 1. The edc migration pin gains version 7.
