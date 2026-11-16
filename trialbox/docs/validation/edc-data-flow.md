# TrialBox to the sponsor's EDC: the data-flow description

*Card EDC-023. Decision D-859. Status: living. For the sponsor's data-management plan (or the protocol's data
section), to be adapted to the study and referenced when prefill is switched on.*

TFDA's guideline on computerised systems and electronic data in drug trials (「電腦化系統與電子數據應用於藥品臨床試驗
指引」, May 2024), §4.7 「數據擷取」 (p. 18), asks the protocol or its documents to describe each transfer of electronic
data: its type, format, source and destination, who can access it, when it is transferred, and every use it may
serve, such as validation, reconciliation, verification and review (¶3). It also asks that transfers and derivations
stay traceable (¶4), and that data recorded directly in the data collection tool is identified as source data (¶2).
This page gives that description for TrialBox, in a form a sponsor can copy into its plan. The bracketed parts are the
study's.

TrialBox refuses to switch prefill on without the reference to the section that holds this description
(`edc.dataflow_ref`). Copy-assist does not need it: there a person types each value into the EDC, and nothing is
transferred electronically.

## 1. What is transferred

- **Type.** Values of the eCRF fields the study's item map names: demographics, vital signs and laboratory results,
  medical history and concomitant medication (present or not), and values read from clinical notes. Each value comes
  from the site's own records and has been decided (confirmed, edited or rejected) and signed by a delegated person.
  Nothing else is sent: no notes, no identifiers, no record that was not decided and signed. A field the protocol
  names as recorded directly in the EDC is never sent (§4).
- **Format.** One value per eCRF field, in the format of the field's validation in the EDC's data dictionary (for
  example a number with the field's decimal places, a date in its order, a choice as its code). A value the EDC would
  refuse is held back and listed, never reshaped.

## 2. From where, to where

- **Source.** The site's hospital records as TrialBox reads them inside the hospital: [the site's systems, e.g. the
  electronic health record and the laboratory system]. Each value carries its citation: the record, the row, the day
  and, for a note, the quoted words.
- **Destination.** The study's REDCap project [project name and server], through the REDCap API, one study per
  connection. An ODM 1.3.2 file of the signed values may be given instead, for an EDC that imports ODM.
- **Path.** Inside the hospital network only: TrialBox's server to the EDC's server, over HTTPS. [State the network
  path, if the EDC is outside the hospital.]

## 3. Who, and when

- **Who can see the values before they are sent.** The study's delegated staff, as the delegation log names them:
  [roles]. Monitors see what the EDC holds, through the EDC.
- **Who starts a transfer.** A delegated person, by pressing send, for one subject or for the study. Prefill is off
  by default; the principal investigator turns it on, with the sponsor's written acknowledgement and this section's
  reference on file, and the PI or an administrator turns it off at any time.
- **When.** Only after a value has been signed, and only when a person sends. Nothing is transferred on a schedule.

## 4. What is never prefilled

A field the protocol names as recorded directly in the EDC, as source data (§4.7 ¶2), is never a prefill target:
TrialBox refuses a map row that would draft it (`edc.direct_source`), holds back a value of it that was signed before
the protocol named it, and leaves it off the copy-assist sheet. The list is kept with the protocol section that names
it, and every change of it is kept. [List the fields, or say "none".]

TrialBox also never writes to a field someone else already filled in the EDC (the value is listed as a conflict and
left as it is), never fills an empty field with a default value, and never writes a calculated field: the EDC
computes those.

## 5. What the data is used for, and how it stays traceable

- **Uses.** Entry into the eCRF; the EDC's own validation checks; reconciliation of the EDC with the source records;
  source-data verification and review by monitors.
- **Traceability.** For each value TrialBox keeps, append-only: the source citation, the item map row and the EDC
  dictionary entry it was drafted under, who decided it and how (with the reason for an edit), the signature (name,
  role, meaning, time), and each send with the EDC's answer read back from the EDC. A value the EDC holds differently
  afterwards is shown, with both values. Every step is in TrialBox's audit trail; the EDC's own audit trail records
  the write under the TrialBox connection's user.
- **Reconciliation.** [How often the study reconciles the EDC with TrialBox's sent record, and who does it.]

## 6. To fill in for the study

| Item | The study's answer |
| --- | --- |
| Section of the protocol or data-management plan that holds this description | |
| Fields recorded directly in the EDC (source data in the tool), with the protocol section | |
| The site's source systems | |
| The EDC project and server, and the network path | |
| Roles that may decide, sign and send | |
| Reconciliation: how often, by whom | |
