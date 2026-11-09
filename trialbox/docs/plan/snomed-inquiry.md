# SNOMED CT licence inquiry (ready to send)

| Field | Value |
| --- | --- |
| Document ID | TB-LIC-01 |
| Version | 1.1 (2026-11-09; review TB-REV-SA-01 S-19, S-23 answered) |
| Decided by | owner decision of 2026-11-09 ("Data model", SNOMED CT row: ask about a licence; Aimedics holds it for the product; get a quote now); TB-PLAN-05 WS-15.3, Q-22 |
| Send to | info@snomed.org (SNOMED International's public contact). **First register Aimedics in MLDS** (the Member Licensing and Distribution Service), through which the affiliate licence itself is requested. Copy the national release centre of Japan or Taiwan **if either country has become a member**. Neither was a member (checked on snomed.org, 2026-11-09), so SNOMED International answers for both; the first question asks it to confirm. |
| Sender | Changfu Kuo, Aimedics (fill in the signature block) |
| Contains | no patient data and no hospital data |

---

**Subject:** Affiliate licence enquiry: on-premises clinical research software for hospitals in Japan and Taiwan

Dear SNOMED International licensing team,

Aimedics ([legal entity name], registered in [country]) develops TrialBox, software that helps hospitals run clinical research. It is installed inside each hospital, on the hospital's own server or an appliance we supply. It reads the hospital's records into a research database (OMOP CDM v5.4) and helps research staff find patients who may fit a study. No patient data leaves the hospital, and Aimedics never holds patient data. Two hospitals start in 2027: Chang Gung Memorial Hospital in Taiwan and one hospital in Japan. We expect up to [N] more hospitals a year in both countries. Staff use TrialBox through a browser; the browser application runs on the hospital's own server.

We would like SNOMED CT concepts in the research database, so that diagnoses and findings map to the standard vocabulary used in OMOP. Aimedics would hold the licence for the product. Could you tell us:

1. **Territory.** Are Japan and Taiwan non-member territories today? If either has a national release centre, please forward this message or tell us whom to contact.
2. **Licence holder.** Please confirm the sub-licence model for our case: Aimedics holds the affiliate licence and the hospitals use SNOMED CT inside our product. Who reports the deployments, and who pays?
3. **Fee basis.**
   a. How is the fee counted for our case: per hospital, per server, or per "data processing system"? One hospital runs TrialBox in containers on a shared server; the other on one appliance.
   b. Does a test copy at the same site count as another system?
   c. Your public fee table lists US$1,954 per hospital per data processing system per year in Band A. Does that apply to both countries? Please give the 2027 fee in writing.
4. **Development and testing.** May we use SNOMED CT in development and in automated tests (synthetic data only) before the first hospital goes live, and under which terms?
5. **Research network.** May data coded under our licence be shared with a consortium member in another territory, and does the receiver need its own licence?
6. **Translations.** Are there approved Japanese or Traditional Chinese descriptions we may use, or may we add our own as a local extension?
7. **Process.** What do we need to send to get a written quote, and how long does it usually take?

Thank you. We are happy to give more detail or join a call.

Kind regards,

Changfu Kuo
Aimedics
[address, e-mail and phone]

---

## Notes for the sender (not part of the message)

- Until a licence is in place, ICD-10-CM plus the WHO ICD-10 bridge stays the condition standard (owner decision). v1 ships without SNOMED CT (Q-22).
- Record the answer, the fee and the holder decision in TB-PLAN-05 WS-15.3 and in DECISIONS.md.
- The fee quoted in item 3 comes from SNOMED International's public licensing page as read for `docs/reviews/2026-11-09-holistic-02-commercial-regulatory.md`; check it again before quoting it to a hospital.
