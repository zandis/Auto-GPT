# D-351 One forbidden-word list, checked everywhere, and the statement on every output

- **Task:** T-116 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5; the rest after T-506)
- **PR:** this branch (`agent/T-116-wording`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-143 (the "criteria not matched" list), TB-IU-01 §1 and §2 (`docs/plan/intended-use.md`), T-506
  (`libs/tb_common/wording.py`, the PI and CRC walk, the console footer)
- **Closes:** CR-078 (rest), FIT-006 (rest); REG-017 (the orchestrator's tier label), TB-IU-01 condition C1 (PDF,
  XLSX and mail)

## Context

T-506 put the verdict words ("excluded", 除外, 排除, "likely eligible") under a check on the investigator's and the
coordinator's pages, and the intended-use statement in the console footer. The rest of the TB-IU-01 §2 list (診断,
判定, 対象外, "diagnosis" and others) stayed in `LATER`, checked only on request. The orchestrator's mail and report
catalogue still said "likely eligible" and "excluded" (ja 適格の可能性が高い, 除外; zh-TW 排除). No PDF, workbook or
mail carried the statement.

Most hits of the full list were not verdicts. They named a record's field: "diagnosis code", 診断 as a column of a
hospital's list, 診斷碼. Two ways were open: widen `ALLOWED` with record terms, or name the field with a word that is
not on the list.

## Decision

1. **One list.** The words of `LATER` join `FORBIDDEN`; `LATER` is empty and kept only so old imports work.
   "diagnoses", AIが判定 and 建議治療 are added. `check` and `check_page` use the whole list by default.
2. **A record's field takes a neutral word, not an exception.** English "condition" (the FHIR and OMOP name),
   Japanese 病名 (already the Japanese label of the same fields), Traditional Chinese 疾病 or 病名. `ALLOWED` stays
   what T-506 made it: the statement and the protocol's own heading (除外基準, 排除條件, 排除標準). A wider `ALLOWED`
   would let a verdict hide inside an allowed phrase.
3. **The product's verbs.** What the box does with a note is "read" (読み取り, 判讀), what it does with codes is
   "match" (照合, 比對), what a person puts on a patient is a "mark" (マーク). 判定 is not used for any of them.
4. **不符合 stays.** It is the zh-TW answer of one criterion ("not met", ja 非該当), not a verdict on a patient. The
   patient-level name is 未符合條件 (D-143). The en and ja patient-level "not eligible" (対象外) on the site patients
   page and the ask page become "criteria not matched" in all three languages.
5. **Quoted text is the source's.** A criterion's protocol text and a note passage are shown as written; the walk
   reads the pages of the synthetic site, whose rulesets carry no listed word in their labels (checked by the
   criterion-label test of T-507).
6. **Where the list is checked.** The walk: every GET page of the five roles (admin, coordinator, investigator,
   viewer, CRO) in three languages. A catalogue test: every console catalogue (the merged one and each module's own
   table, so a shadowed value is read too), the orchestrator's catalogue, the case sheet's and the consent page's
   fixed words. A template test: the visible text of every console template. `check_file` skips `docs/plan/`,
   `docs/reviews/` and `docs/decisions/` by design (TB-IU-01 §2: only the risk file names the hazard plainly).
7. **The statement on every output** (TB-IU-01 condition C1), from `tb_common.wording.statement`:
   `ReportMeta.statement` closes each PDF (feasibility, screening summary, cohort) and adds one row to every sheet of
   each workbook (candidates, feasibility, NAV, trial simulation); the case sheet and the consent pages carry it in
   their footer; the mail gateway adds it after a signature separator to the text and HTML parts of every mail, its
   own auto-replies and the password mail. A send request carries no language, so the gateway reads it from the
   body's script (`text_lang`: kana is Japanese, five or more Han characters Chinese, else English).

## Consequences

- The literal grep of TB-ASSESS-01's acceptance (1) still prints the protocol heading 選択・除外基準 / 納入／排除條件
  and the template's `data-testid="excluded"`. Both are allowed by design (a heading kind; an attribute nobody
  reads). The tests read what a reader sees instead.
- The route `/studies/{rs}/excluded` keeps its path. Its alias and 301 are in `services/console/home.py`, which is
  T-512's while that card is open; it waits for T-512.
- NAV's sheet names (`likely_eligible`, `maybe_ineligible`) are contract keys of the reimbursement lists, not a study
  verdict; they are unchanged.
- The `.docx` reimbursement draft (RA-BIO template) has no statement field; adding one changes the template.
