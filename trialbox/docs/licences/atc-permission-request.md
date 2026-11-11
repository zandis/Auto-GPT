# ATC permission request (ready to send, not sent)

| Field | Value |
| --- | --- |
| Document ID | TB-LIC-02 |
| Version | 1.0 (2026-11-10, card T-617b, finding STD-044 point 2) |
| Register row | `atc` in `docs/licences/register.csv` (status `permission-to-ask`) |
| Send to | the WHO Collaborating Centre for Drug Statistics Methodology (WHOCC), Oslo, through the contact on <https://atcddd.fhi.no> |
| Sender | the owner, for Aimedics (fill in the signature block) |
| Contains | no patient data and no hospital data |
| State | written only. Nothing has been sent from this repository. When it is sent, set the row's `status` and `evidence` to the date and the answer. |

---

**Subject:** Permission to include ATC codes and names in clinical research software for hospitals

Dear WHOCC team,

Aimedics ([legal entity name], registered in [country]) develops TrialBox, software that helps hospitals find
patients who may fit a clinical study. It is installed inside each hospital, on the hospital's own server or an
appliance we supply. No patient data leaves the hospital. The first two hospitals are in Taiwan and Japan (2027).
TrialBox is a commercial product.

TrialBox uses the ATC classification to group medicines in study criteria, for example "any drug in ATC group
L04AB" (TNF-alpha inhibitors). For this it ships:

1. **ATC codes** in study value sets and in maps from local drug codes (Taiwan NHI drug codes, Japanese YJ codes)
   to ATC.
2. **The English ATC names** of the codes it uses, so that staff can read what a criterion means. Today this is a
   subset of 33 codes (the demo list), not the full index.
3. **No DDD values.** We do not ship or show DDDs.

We credit the WHOCC wherever the codes appear ("ATC codes: WHO Collaborating Centre for Drug Statistics Methodology,
Oslo, Norway").

Could you tell us:

1. **Codes.** May we include ATC codes in the software and in its value sets and maps, as described above?
2. **Names.** May we include the English ATC names of the codes we use (a subset, not the full index)? If not, is
   there a licence for it, and what does it cost?
3. **Updates.** May we update the subset each year from the new ATC/DDD index, and is there a machine-readable
   copy we may license for this?
4. **Hospitals.** The software runs inside each hospital. Does each hospital need its own permission, or does
   our permission cover the software as installed at a hospital?
5. **Attribution.** Is the credit line above the wording you want, and where should it appear (about page, notice
   file, reports)?

If you cannot grant permission for the names, we will ship the codes only and take drug names from the open
national lists (Taiwan NHI, Japan MHLW).

Kind regards,

[name]
[title], Aimedics
[address]
[email]
