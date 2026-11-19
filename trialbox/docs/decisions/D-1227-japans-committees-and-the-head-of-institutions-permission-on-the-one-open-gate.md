# D-1227 Japan's committees and the head of the institution's permission, on the one gate a study passes to open

- **Task:** card 10C-4 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C, the Japan profile; source JP-3 of
  root review 11, `docs/reviews/2026-11-root/11-japan.md`, sections 6.4, 8 (P3) and 9 (G2, G4))
- **Date:** 2026-11-19
- **Status:** accepted; the number is lane J's (block D-1220 to D-1319), reserved for this card
- **Builds on:** D-147 and D-380 (the study's IRB record and who keeps it), D-311 (the IRB record is a list, not a
  gate), D-364 (an amendment screens on the version before until its effective day), D-386 (the study's state; lists
  run only for an open study), D-415 (the one refusal of the move to open: the SAE type), D-1154 (the list of what
  comes before open), commitment C-7 (a country is data)

## Context

Japan has three review routes by study kind: a 治験 is reviewed by an IRB (治験審査委員会, GCP省令), a 特定臨床研究 by
a certified review board (CRB, 認定臨床研究審査委員会, 臨床研究法), and a study under the ethical guidelines (a 指針
study) by an ethics committee (倫理審査委員会), often one central review for many sites (一括審査), after which each
site's head of institution (研究機関の長) permits the study (実施許可) before the site starts. The box had one free-text
IRB record and no permission step (review 11, G2 and G4). These are the project's reading of the public sources named
in `libs/tb_common/japan_profile.json`, to be confirmed by the first site's trial office.

## Decision

1. **The Japan profile's committees part is data.** `libs/tb_common/japan_profile.json` names, per study kind
   (`chiken`, `tokutei`, `shishin`), the committee and what the site must hold: an approval (治験, 特定臨床研究) or
   the head of institution's permission (指針 study). It is on for a site whose country is Japan (`site.tz`, as the
   SAE study types already read it); no kind recorded is the other-country default. `tb_common.committees` holds the
   rule, pure and standard-library only.
2. **The record.** Per study: the kind, internal or external, the establishing body (設置者, text), the contract date
   when external, the protocol version in use now, the version the committee approved and the date, central review
   yes or no, and documents by title and date only (no upload). Per site (the box's `TB_SITE_ID`): the head of
   institution's permission date and the version it covers. History rows in schema `team` (version 4); a page
   `/studies/{rs}/committee` and its `/api/v1` twin, both 404 outside the Japan profile.
3. **The rule is added to the one gate.** The move to open (`console.study_setup`, beside the SAE type of D-415)
   refuses a 治験 or 特定臨床研究 without its committee's approval of the current version, and a 指針 study without
   this site's permission for the current version; lists run only for an open study (D-386), so such a study cannot
   screen. The refusal is a plain sentence naming what is missing and that a hospital coordinator or the study's PI
   records it. An external committee without a contract date warns; a kind not chosen warns. The start-up list of
   D-1154 gains the item.
4. **Amendments warn; they do not stop an open study.** A new current version makes the recorded approval and
   permission "for an earlier version" and says what is needed. As for every amendment today (D-311, D-364), an open
   study keeps screening on the version before; a study in start-up, or one paused and opened again, does not open
   until the current version has what it needs.
5. **No new right.** Recording follows the IRB record exactly (the matrix's `irb.edit` for hospital staff: a hospital
   coordinator, the logged PI; a written reason for a change; audited as `console.irb`, action `committee`, with the
   old and new values); reading follows the IRB page (every account but an aggregate-only one). A test compares every
   role on both.
6. **With the profile off nothing changes.** A non-Japanese site has no committee page, no new item, no new refusal,
   and the IRB and state pages render byte for byte as before.

## Consequences

- The study kind overlaps the SAE rule set's Japanese types (`jp_gcp`, `jp_gcp_ii`, `jp_crb`, `jp_guideline`): two
  settings that could disagree. Reading one from the other is left to 10C-25 (the profile as one layer).
- The 病院長's 指示・決定 date for a 治験, SOP and roster versions of an external IRB (review 11, JP-3's longer list)
  are not in this card (the plan's card text names neither).
