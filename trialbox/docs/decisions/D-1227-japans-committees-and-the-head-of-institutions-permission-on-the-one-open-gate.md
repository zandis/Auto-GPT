# D-1227 Japan's committees and the head of the institution's permission, on the one gate a study passes to open

- **Task:** card 10C-4 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C, the Japan profile; source JP-3 of
  root review 11, `docs/reviews/2026-11-root/11-japan.md`, sections 6.4, 8 (P3) and 9 (G2, G4))
- **Date:** 2026-11-19 (revised after the lane coordinator's review the same day)
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
   (`chiken`, `tokutei`, `shishin`), the committee and what this box records. Every kind needs both records to open:
   the committee's approval, and this site's head-of-institution record.
   - For a 治験, that record is the 実施医療機関の長's 指示・決定 after the IRB.
   - For 特定臨床研究, the 実施医療機関の管理者's 承認 after the CRB.
   - For a 指針 study, the 研究機関の長's 許可 (実施許可) after the ethics committee.

   This follows the card. It is the lane lead's ruling of 2026-11-19 until the owner says otherwise; to change it,
   edit `needs` in the profile (one line per kind).
2. **One reading of the site.** `tb_common.committees.here` gives the site id (`TB_SITE_ID`; none: no site record is
   kept) and its country (`TB_TZ`). Both the console and the orchestrator use it. The profile is on for a site in
   Japan.
3. **The record.** Per study:
   - the kind;
   - internal or external, and the establishing body (設置者, text);
   - the contract date when external;
   - the protocol version in use now;
   - the version the committee approved, and the date;
   - central review yes or no;
   - documents by title and date only (no upload);
   - optionally, a date by which what is missing is to be recorded.

   Per site: the head-of-institution record's date and the version it covers. It is changed only when its fields
   are given, and cleared only on purpose, with a reason, audited.

   Each opening under the rule is recorded (table `committee_open`: the kind and the version that passed). So are
   the marks of the studies open when the rule first applied at the site. All tables are history rows in schema `team`
   (version 4).

   The page is `/studies/{rs}/committee` with its `/api/v1` twin. Both are added only on a Japanese site, so a box
   elsewhere has the same route table, pages and walks as before this card.
4. **One rule, read where a study opens and where a list is made** (`tb_common.committees`).
   - **A move into open** (start-up or paused to open, a close taken back to open) is refused when the kind is not
     chosen, or when either record is missing for the current protocol version.
   - **The orchestrator's open check before every list** (`require_open` and the timer's hold), state row or not:
     - a study neither opened under the rule nor marked open before it is held as a move into open would be;
     - a marked study is not held for a kind not chosen; once a kind is recorded on it, the whole rule applies;
     - a study opened through the gate is not held by an amendment (`earlier_*`) while its kind is the one it opened
       with: as for every amendment today (D-311, D-364), it screens on the version before;
     - a kind changed since the opening holds it until its records fit the new kind, even with a site record for an
       older version.
   - A 指針 study without the permission date cannot screen.
   - Dates after the site's today do not count.
   - The kind of an open study cannot be cleared (409 with the reason).
   - An external committee without a contract date warns.
5. **The transition rule (the lane's ruling; for the owner to confirm).** When the console first starts on a
   Japanese site (or first reads there), it marks every study open at that moment as open before the rule
   (recorded, audited `console.irb`, action `committee_baseline`). Those studies keep running, and the state page and
   the IRB page show what they still lack, with the date by which to record it only if the site sets one. Nothing
   stops by itself; only a recorded fact does. Until the console has taken a site's baseline, the rule has not
   arrived there and the orchestrator holds nothing.
6. **No new right.** Recording follows the IRB record exactly: the matrix's `irb.edit` for hospital staff, with a
   written reason for a change; audited as `console.irb`, action `committee`, with the old and new values. Reading
   follows the IRB page. The API returns the fields and findings, not who recorded them.

   The four route rows copy the IRB routes' rows (`tests/console/data/route_actions_japan.yaml`, for lane C2 to
   confirm). A walk at a Japanese site judges them, and its table `role_route_matrix_japan.md` equals the IRB rows.
7. **With the profile off nothing changes.** The pages render byte for byte as before. The route table, the role walk
   and the role × route matrix are master's.

## Known limits (no change)

- A manual list runs when the committee record cannot be read (a `DatabaseError`), as the existing state check
  allows; the timer holds.
- No approval expires here: an approval or a site record stays valid until a new version or a change is recorded.

## What is recorded is not every requirement

These are the project's readings of public texts, to be confirmed by the first site's trial office. Article numbers
were read on 2026-11-18 and have not been re-verified against the consolidated texts.

| Statement | Public source (project's reading) |
| --- | --- |
| A 治験 needs the IRB's approval before it starts | GCP省令 (平成9年厚生省令第28号) 第27条, 第32条 |
| A 治験 also needs the head of the institution's decision (指示・決定), recorded here as the site record | GCP省令 第27条; 統一書式5 |
| A 治験 also needs the trial contract. Not recorded here | GCP省令 第13条 |
| A 特定臨床研究 needs the CRB's opinion on its 実施計画 | 臨床研究法 (平成29年法律第16号) 第5条, 第23条 |
| A 特定臨床研究 also needs the 実施医療機関の管理者's approval, recorded here as the site record | 臨床研究法施行規則 (article not verified) |
| A 特定臨床研究 also needs the 実施計画 submitted to the Minister and published in jRCT. Not recorded here | 臨床研究法 第5条 |
| A 指針 study needs the 研究機関の長's permission after the ethics committee's review; 一括審査 for multicentre research | 人を対象とする生命科学・医学系研究に関する倫理指針 第6 (article numbering of the 2026 text not verified) |
| An external committee is not always under a contract (for a 指針 study the 指針 asks for the committee's procedures, not a contract); the contract warning is the project's reading | 指針 第6; GCP省令 第27条 (for a 治験) |

The page and the refusal say so in each language: "recorded here: ...; other requirements are the site's own (see the
Japan pack)".

## Consequences

- The study kind overlaps the SAE rule set's Japanese types (`jp_gcp`, `jp_gcp_ii`, `jp_crb`, `jp_guideline`): two
  settings that could disagree. Reading one from the other is left to 10C-25.
- The 病院長's 指示・決定 date, and an external IRB's SOP and roster versions, are not in this card.
