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
   (`chiken`, `tokutei`, `shishin`), the committee and what this box records: an approval (治験, 特定臨床研究) or
   the head of institution's permission (指針 study). It is on for a site whose country is Japan (`site.tz`, as the
   SAE study types already read it). `tb_common.committees` holds the rule, pure, and reads the record from the
   trial database for the orchestrator.
2. **The record.** Per study:
   - the kind;
   - internal or external, and the establishing body (設置者, text);
   - the contract date when external;
   - the protocol version in use now;
   - the version the committee approved, and the date;
   - central review yes or no;
   - documents by title and date only (no upload);
   - optionally, a date by which what is missing is to be recorded.

   Per site (the box's `TB_SITE_ID`; with none, no permission is recorded): the head of institution's permission
   date and the version it covers. A permission is changed only when its fields are given, and cleared only on
   purpose, with a reason, audited. History rows live in schema `team` (version 4). The page is
   `/studies/{rs}/committee` with its `/api/v1` twin. Outside the Japan profile they answer as a route the console
   does not have, except that an anonymous API POST is first asked for its session (401), as every state-changing API
   route is (D-444).
3. **One rule, read where a study opens and where a list is made.**
   - **A move into open** (start-up or paused to open, a close taken back to open) is refused when the study kind is
     not chosen; when a 治験 or 特定臨床研究 lacks its committee's approval of the current version; and when a 指針
     study lacks this site's permission for it.
   - **The orchestrator's open check before every list** (`require_open`, and the timer's hold) holds a study with
     no recorded state for every such refusal, and a study recorded open for every refusal but an amendment's.
   - So a 指針 study without the permission date cannot screen. A study whose kind is set to 指針 after it opened
     stops listing until the permission is recorded, and the state and IRB pages say so.
   - A date after the site's today does not count.
   - The refusal is a plain sentence naming what is missing and that a hospital coordinator or the study's PI (研究責任者
     for a 指針 study) records it.
   - An external committee without a contract date warns.
4. **Amendments warn; they do not stop an open study.** A new current version makes the recorded approval and
   permission "for an earlier version" and says what is needed. As for every amendment today (D-311, D-364), an open
   study keeps screening on the version before. Reopening it (from paused, or a close taken back) needs the current
   version's approval and permission.
5. **The transition rule (the lane coordinator's ruling; for the owner to confirm).** A study already open and
   running when this rule arrives (no committee record yet, or the profile switched on later) keeps running. The
   state page and the IRB page show what it still lacks as a refusal in waiting, with the date by which to record it
   only if the site sets one. Nothing stops by itself; only a recorded fact does.
6. **No new right.** Recording follows the IRB record exactly: the matrix's `irb.edit` for hospital staff; a written
   reason for a change; audited as `console.irb`, action `committee`, with the old and new values. Reading follows the
   IRB page. The API returns the fields and findings, not who recorded them, as the IRB API does. The route rows copy
   those of the IRB routes, for lane C2 to confirm.
7. **With the profile off nothing changes.** A non-Japanese site has no committee page, no new item and no new
   refusal, and the IRB, state, set-up and team pages render byte for byte as before.

## What is recorded is not every requirement

These are the project's readings of public texts, to be confirmed by the first site's trial office. Article numbers
were read on 2026-11-18 and have not been re-verified against the consolidated texts.

| Statement | Public source (project's reading) |
| --- | --- |
| A 治験 needs the IRB's approval before it starts | GCP省令 (平成9年厚生省令第28号) 第27条, 第32条 |
| A 治験 also needs the head of the institution's decision (指示・決定) and the trial contract. Not recorded here | GCP省令 第13条; 統一書式5 |
| A 特定臨床研究 needs the CRB's opinion on its 実施計画 | 臨床研究法 (平成29年法律第16号) 第5条, 第23条 |
| A 特定臨床研究 also needs the 実施計画 submitted to the Minister and published in jRCT, and the 実施医療機関の管理者's approval. Not recorded here | 臨床研究法 第5条; 施行規則 |
| A 指針 study needs the 研究機関の長's permission after the ethics committee's review; 一括審査 for multicentre research | 人を対象とする生命科学・医学系研究に関する倫理指針 第6 (article numbering of the 2026 text not verified) |
| An external committee is not always under a contract (for a 指針 study the 指針 asks for the committee's procedures, not a contract); the contract warning is the project's reading | 指針 第6; GCP省令 第27条 (for a 治験) |

The page and the refusal say so in each language: "recorded here: ...; other requirements are the site's own (see the
Japan pack)".

## Consequences

- The study kind overlaps the SAE rule set's Japanese types (`jp_gcp`, `jp_gcp_ii`, `jp_crb`, `jp_guideline`): two
  settings that could disagree. Reading one from the other is left to 10C-25.
- The 病院長's 指示・決定 date, and an external IRB's SOP and roster versions, are not in this card.
