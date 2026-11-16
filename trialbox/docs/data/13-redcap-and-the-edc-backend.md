# 13. REDCap and the EDC backend

TrialBox already reads and writes a REDCap project through `services/rc_bridge` (the study link and the data core).
This section is the second door, added in D-915: one interface, `services/edc_backend`, that talks either to the
hospital's REDCap or to an internal EDC. The internal service is not in this repository. It is a separate program
that exposes REDCap's documented `/api/` (a token and `content=` on a POST). The door stays shut until
`TB_EDC_BACKEND` is set, so the demo and the study-link page behave as they did.

| `TB_EDC_BACKEND` | What it calls |
| --- | --- |
| unset | nothing. `connect()` returns no connection |
| `redcap` (or `external`) | the hospital's REDCap, `https` only |
| `internal` | the on-box service. `http://` is accepted only for `127.0.0.1`, `localhost` and `::1`, and only with no user or password in the URL. The egress guard still applies: plain `http` outside DEV and TEST is refused |

Shorter names work when the `TB_` one is empty: `EDC_BACKEND`, `REDCAP_API_URL`, `REDCAP_API_TOKEN`,
`EDC_INTERNAL_URL`, `EDC_INTERNAL_TOKEN`, `REDCAP_TOKEN_<ref>`.

## What the hospital sets on REDCap

The API is REDCap's ordinary one: `POST {server}/api/` with the project token in the body, never in the URL or in
a log line. One token is one project. A token is 32 hexadecimal characters, from the project page **API** (or
**API Playground**), for a user who has the rights below. TrialBox stores it as `TB_REDCAP_API_TOKEN` or as
`TB_REDCAP_TOKEN_<ref>` / `TB_REDCAP_PROJECT_TOKENS` (`gzqo:<token>,rabio:<token>`). The ref is a short name
(`gzqo`), not the REDCap project id.

Rights on that user, per project:

- **API Export** for reads (version, project, data dictionary, records, files, instruments, events, arms, the
  form-event map, repeating instruments, reports, the log).
- **API Import/Update** for record import and file upload. **Create Records** as well when TrialBox should add a
  record (`forceAutoNumber`).
- **Data Export**: *De-identified* or *Remove identifier fields* when the feed must not carry identifiers. That
  right is applied by REDCap before the bytes leave it. The connector also blanks any field the dictionary marks
  `identifier=y`, except the record-id field, which a row cannot spare. Turn the blanking off only with
  `export_records(drop_identifiers=False)` or `copy_records(..., keep_identifiers=True)`, and only for a migration
  the site has approved.
- **Survey Distribution Tools** for a survey link (`content=surveyLink`). The connector drops a link that contains
  the API token.
- A data access group, if the project uses them: the token then sees that group's records only, unless the user is
  allowed every group.

The server must be reachable from the box over HTTPS. A private address is declared for this call only (the host
in `TB_REDCAP_API_URL`); link-local and metadata addresses stay refused. The connector caps itself with
`TB_REDCAP_MAX_PER_MINUTE` (0 means no client cap; REDCap's own cap still answers 429, which becomes `RC-RATE`)
and `TB_REDCAP_MIN_INTERVAL_MS`. A file larger than `TB_REDCAP_FILE_MAX_BYTES` (default 26214400) is refused.
Tokens, file bytes and record values are not written to the log. An error from REDCap is reduced to a kind of
failure; REDCap's sentence, which can quote a value, is not kept.

`python -m rc_sim` is the local stand-in (loopback, fixtures, no hospital data). It is not started by the demo.
It answers the reads the study link uses, plus instruments, users, a survey link, and file export, import and
delete. It refuses a data-dictionary import, on purpose.

## Versions: 13.7.23, and what "17" is

Public release notes and site upgrade logs, read on 2026-11-16:

- **13.7** was a long-term support line. Vanderbilt's REDCap consortium test records include 13.7.15. A hospital
  on **13.7.23** is on that line.
- Later long-term lines in public upgrade logs include 14.0, 14.5, 15.0, 15.5, 16.0 and **17.3**. One site lists
  LTS **17.3.25** installed on 2026-11-13. **16.0** was still receiving patches in 2026 (a site lists 16.0.47 on
  2026-08-18).
- The standard line moves faster. One site lists **17.5.11**, released 2026-11-10. So "17" is the current major,
  not a future one. The study-link page already accepts 14, 15, 16 and 17 (`RedcapClient.check_version`).

The methods this backend calls (version, project, metadata, record, file, instrument, event, arm,
formEventMapping, repeatingFormsEvents, dag, user, report, surveyLink, log) are the documented `/api/` surface
and are present on 13.7. `connect()` therefore accepts majors **13 through 17**. The study-link page does not:
`check_version` still rejects 13, including 13.9, so a site that only uses that page still needs 14 or newer.
Pointing that page at this backend is later work. It is not done here, and the nightly read is not pointed here
either.

Differences that matter in practice:

- **File import, `repeat_instance=new`.** REDCap 17.4.0 accepts the literal `new` and allocates the next instance.
  13.7 does not. Send the instance number. The simulator does the same: `new` works only when it is showing 17.4
  or later.
- **Export rights and date shifting** are a property of the token's user on every version here. De-identified
  export is how a site keeps dates from leaving REDCap in the clear. The connector cannot reconstruct that
  shifting, and does not try.
- **Logging** (`content=log`) has been in the API since well before 13.7. A project with no log rights answers
  with an error; the connector reports the kind, not the text.
- **CDIS** (Clinical Data Interoperability Services) and any FHIR read REDCap adds beside `/api/` are not this
  connection. See the mapping below.
- A public 2026 notice describes a critical survey-passthrough flaw in REDCap 13.3.0 and later, fixed on the
  vendor's patched lines (named there as 16.0.49 LTS, 17.3.10 LTS and 17.4.4 standard). 13.7.23 is older than
  those lines. Upgrading is the hospital's change, on Vanderbilt's instruction. This repository does not carry
  REDCap's code and does not describe how the flaw is used.

## How a dictionary maps

`EdcConnection.mapped(study)` reads the data dictionary, the project, the events, the arms, the form-event map
and the repeating instruments, and returns:

- one FHIR R4 Questionnaire per instrument, through the data core's existing reader (`datacore.forms`). Field
  names are `linkId`. Codes stay REDCap's raw codes. Identifier fields are left off the questionnaire.
- visits: each event (`unique_event_name`, arm, day offset). A classic project has none.
- the schedule: which instrument is collected on which event.
- repeating instruments and repeating events, unchanged.
- `identifiers_not_stored`, `file_fields`, `calculated_fields`.

| REDCap | TrialBox |
| --- | --- |
| project | a study the site attaches. The ruleset id is the `study` argument, not REDCap's project id |
| instrument / form | a CRF, stored as a FHIR Questionnaire |
| event | a visit |
| arm | an arm on that visit schedule |
| repeating instrument or event | a repeating CRF. Rows keep `redcap_repeat_instrument` and `redcap_repeat_instance` |
| record | a flat row, `redcap_event_name` when the project is longitudinal |
| file field | bytes in and out (`content=file`). The questionnaire types it as an attachment. The data core does not type the bytes into an answer |
| calculated field | REDCap's value on export. This connector does not recompute it |
| `identifier=y` | not stored on the questionnaire; blanked on export unless the site turns that off |
| branching logic | kept on the questionnaire as TrialBox already keeps it. It is not executed by this connector |

Eligibility rules are not in the dictionary. They stay in the ruleset. Consent, enrolment, screen-fail and
withdrawal stay on the study link, which reads those fields as the outcome of screening.

**FHIR.** The questionnaire is TrialBox's FHIR shape for a CRF. QuestionnaireResponse remains the data core's
export. REDCap's own FHIR pull (CDIS) maps fields to an EHR inside REDCap; TrialBox does not call that module.

**OMOP.** The OMOP store is the hospital record and is read one way. CRF rows from this connector are not written
into it.

**CDISC.** The data core already exports ODM 1.3, with CDASH tags on the built-in forms (demographics, vitals,
labs, adverse events, inclusion/exclusion, disposition). REDCap can export the same records as ODM
(`format=odm`). The connector's record calls use JSON flat so a row round-trips. They do not add a second ODM
writer.

A copy from one backend to the other is `copy_records`. It exports, blanks identifiers unless asked not to, and
imports with `overwriteBehavior=normal`, so a blank does not erase a value already there. Replacing a
dictionary (`import_dictionary`, a data-dictionary CSV, the column names REDCap's API and its CSV export both
use) is for an empty internal project. Do not point it at a production REDCap unless the site means to replace
that dictionary. The simulator refuses the import.

## Security, the IRB, and personal data

Patient data in this repository stays synthetic or public. A live token and a live export never belong in a
commit. The box is on the hospital's network; this connector does not add a route off it. REDCap remains where
the site put it. The internal service, when it exists, is on the same box.

For an IRB and for Taiwan's Personal Data Protection Act (個人資料保護法): export the minimum the protocol needs,
prefer a de-identified or identifier-removed token, and keep the copy on the box. The connector's blanking of
`identifier=y` fields is a second belt, not a substitute for REDCap's export right. Record ids are kept because
the row cannot be joined without them; do not use a chart number as the record id if the export is meant to be
de-identified (the study link's `mrn` mode is already refused).

Part 11 and ICH-GCP expectations for an electronic record (who changed which field, a reason, a signature, access
control) belong to the system that stores the CRF. For data TrialBox stores, that remains TrialBox's own EDC.
This connector is a pipe: it does not sign a record and it does not replace that audit. The internal service has
to provide its own audit, roles and timestamps; this door only speaks the API. Wiring the study-link page and the
03:00 read to the door is later work, so the 2026-11-17 demo does not take this path.

## rea

[rea](https://github.com/morluto/rea) (also `rea-agents` on npm, and a Cursor / Claude / Codex plugin) is an agent
toolkit for inspecting software without its source: native binaries (through Hopper, Ghidra, IDA or Kuna),
JavaScript and Electron, .NET, Android packages, websites, and saved network captures. The GitHub API on
2026-11-16 described a TypeScript repository created 2026-04-14, MIT licensed, with on the order of 460,000 stars
and 1,500 open issues, and text that says it changes quickly. It does not list PHP application source as a
target.

REDCap's integration surface is a documented HTTP API. Building this connector did not require, and does not
use, a reverse-engineering tool. Reading or reimplementing Vanderbilt's PHP would also fight the licence: that
source is not distributable, and this repository is public. rea is not a dependency of TrialBox, not at runtime
and not in the image.

The one place it could help a developer is a closed client whose behaviour is not published (a vendor applet, a
compiled external module). That is optional, on a machine that is allowed to hold the file, as a dev-time MCP
server the person starts themselves. It is the wrong tool for the hospital's REDCap, and it must not be pointed
at REDCap's source.

## What is left

1. The internal EDC itself, in its own repository: the same `/api/`, plus the audit, roles and signatures a CRF
   store needs. This door already speaks to it when `TB_EDC_BACKEND=internal`.
2. Point the study-link page and the 03:00 read at `connect()`, including 13.7 on that page. Not done here.
3. Create arms, events and repeating instruments through the API when a new internal project is empty. Record
   and dictionary copy are in; the schedule still has to exist on the destination.
4. Stream large files instead of holding them, if a site's uploads exceed the cap often.
