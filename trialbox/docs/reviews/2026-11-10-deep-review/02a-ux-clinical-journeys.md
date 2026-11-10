# TB-DR-02a UI/UX and the clinic pipeline: clinical roles, hands-on

| Item | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | origin/master `ca8f287` (the review branch) |
| Method | Ran the one-command demo (`python -m tools.demo`, the default of `demo/Dockerfile`) locally without Docker on 127.0.0.1:18200 and drove it with Playwright (Chromium, deviceScaleFactor 1). Walked PI (`pi`), sub-investigator (`subpi`) and CRC (`crc`) in ja, zh-TW and en, at desktop 1280 px, tablet 768 px and phone 390 px. Read the templates, catalogues and the two earlier UX reviews. |
| What was run | 616 page loads (3 roles × 3 languages × desktop and phone × 28 pages, plus tablet for PI and CRC in ja and zh-TW), with axe-core 4.10.2 (from cdnjs) on 504 of them; 183 timed task runs (plus 6 consent, 2 EDC and 6 flag runs by separate scripts) (sign-in, digest, candidate list, criterion review, three marks, excluded-list flag, referral, SAE acknowledgement, EDC switch, call outcome, consent form, referral answer, EDC draft-confirm-sign-send, SAE register, screening-log download, sign-out; errors: wrong password, 403, unknown study, network drop, expired session); a keyboard-only pass; catalogue wording checks on all 2,339 keys × 3 languages; `pytest tests/console/test_excluded_page.py test_team_pages.py test_sae_pages.py` (20 passed). Scripts, JSON metrics and 250 screenshots: the session scratchpad folder `scratchpad/02a-ux/` (`walk-full.json`, `walk-tab.json`, `tasks-*.json`, `shots/`). |
| What was not run | The Docker image (no Docker daemon here) and the hosted Render / Cloud Run demo. Real models (the demo has the stub model only). TOTP / SSO sign-in (the demo is TB_ENV=DEV). Idle-session expiry in real time (the demo's console clock is frozen, so I simulated expiry by deleting the cookie). Screen readers (NVDA, VoiceOver), real phones, Safari, Windows font fallback. Human testers: every time below is machine time; human times are estimates (section 8). |
| Start-up note | The demo did not start on this checkout until I fetched the CQL translator jars into a scratch folder (UX-001). Postgres had to live under `/var/tmp` because the scratch folder is not readable by the `postgres` user. Both are deleted. |

## 1. Summary

The clinic core is now good and much better than on 11-08: the phone patient sheet with a sticky mark bar, a required reason and Undo for "Not suitable", the IRB warning before Approach, error pages with a heading and three buttons, a language choice on the sign-in page, the excluded list with "send to review", the referral flow, the SAE acknowledgement and the EDC review with sources and a password signature all work in three languages. No page scrolls sideways, every page has `lang` set and one H1, and axe finds only one minor rule.

What stops a clinician PoC today is the demo, not the screens: it does not start from a clean checkout, it wipes all work on restart (and the free host restarts after 15 minutes idle), it runs on mixed clocks so dates contradict each other, it serves one Taiwanese synthetic hospital to both sites, it has one shared `pi` account, no feedback button, and the two-model signal the clinicians are meant to judge never appears.

Counts: **Blocker 3, Critical 0, High 7, Medium 17, Low 14** (41 findings).

Top 5:
1. UX-001 Blocker: the demo crashes at start on a clean checkout (needs `.cache/jvm` jars that no Dockerfile fetches).
2. UX-002 Blocker: every restart erases the PoC; the free host sleeps after 15 minutes and the seed takes 203 s.
3. UX-006 Blocker (PoC): no in-product feedback; two clinicians cannot leave a comment or rating per screen.
4. UX-003 High: three clocks in one demo; past visits shown as "next 2 weeks", decisions dated before the patient was listed, EDC refuses a visit the page shows as done.
5. UX-008 High: 17 to 18 of 25 criterion rows show no evidence: a coded "met" has no value, code or date to check.

## 2. Findings: the demo as a PoC platform

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| UX-001 | Blocker | The default demo (`TB_DEMO_TOOL=demo`) fails at start on any checkout without `.cache/jvm/cql-translator/lib/quick-*.jar`: the in-process box uses `FakeTranslator`, but `build_artifacts` still reads FHIRHelpers from the jar, so the protocol compile fails and `list_demo` asserts. `demo/Dockerfile` only runs `fetch_fonts.py`; `.cache` is not in git, so a Render or Cloud Run build from the repository cannot start. | By a run: `RuntimeError ... FileNotFoundError: FHIRHelpers-4.0.1.cql not found in the cql-translator jars` then `AssertionError: ('GOUT-COH', 'failed')` (`tools/list_demo.py:153`). By reading: `tests/inproc_box.py:168`, `services/criteria_compiler/service.py:241-242`, `services/criteria_compiler/compile_cql/translator.py:50-54`, `demo/Dockerfile:30-33`. Worked after `mvn dependency:copy-dependencies` into a scratch dir and `TB_CQL_TRANSLATOR_LIB`. | Ship FHIRHelpers-4.0.1.cql as a pinned file in the repo (or skip it when the translator is the fake one); add a CI job "fresh clone, `python -m tools.demo --no-serve`" that must pass; build the demo image in CI from a clean context. | new | yes |
| UX-002 | Blocker | The demo resets on every restart ("every restart rebuilds the data"), the README's Render free plan sleeps after 15 minutes idle, and the seed takes 203 s, not the "about 30 s" / "about 70 s" written. Two clinicians testing on different days lose every mark, referral, consent and EDC signature, and wait about 4 to 5 minutes on a cold link. | By a run: `e2e_simple PASSED in 203.0 s` before "console on". By reading: `demo/README.md` ("sleeps after 15 minutes", "about 30 seconds"), `demo/Dockerfile:35-37` ("about 70 s"), `tools/demo.py:47-49` (`rmtree` of the work dir). | For the PoC: an always-on host (Cloud Run min-instances 1 or a small VM), a persistent work dir and database, a seed that runs once and is kept, an "admin: reset demo" action instead of reset on boot. Update the README times. Acceptance: restart the service, the PI's marks from yesterday are still there. | new | yes |
| UX-003 | High | Three clocks in one demo. The console's clock is frozen at the demo day (`list_demo.py:50`), the box and the job times use the real date, and the site zone is Asia/Taipei. Seen: week page "SCREEN run of 2026-11-10" vs excluded page "run of 2026-11-02" for the same list; PI decisions dated 11-02 for patients "first listed" 11-10; "Clinic, next 2 weeks" lists visits on 11-04 (past); CRC tasks "due 2026-11-01"; participant page shows visit v1 "done 2026-11-09" but EDC refuses visit date 2026-11-09 "not in the future"; sponsor SAE report due 11-03 shown as "open", not overdue; consent dated 11-10 accepted. | By a run: screenshots `walk-pi-ja-desktop-_week.png`, `task-crc-zh-TW-edc-flow.png`; EDC message `来院日を入力してください（未来の日付は不可）。 edc.visit_date` for 2026-11-09, accepted for 2026-11-02. By reading: `tools/list_demo.py:50,134,210`, `services/console/home.py:292`. | One clock for the demo: shift the synthetic data so the demo day is the real day at start, and give box, console and mail the same clock. Acceptance: no date on any page is after "today" or before the first listing for a decision. | new (UTC "today" family: CR-049, CR-050 registered) | yes |
| UX-004 | High | One synthetic hospital for both sites: "示範醫院B", Asia/Taipei, with zh-TW note text. Dr Makoto in ja reads Chinese note quotes as evidence (excluded page: 「過去一年僅於…有一次痛風發作」) and a Taipei clock on the SAE page. The Japan SS-MIX2 synthetic data exists only inside e2e stage 13, never served. | By a run: `/studies/GZQO/excluded?src=notes` in ja; SAE page "施設の日付（Asia/Taipei）". By reading: `tests/inproc_box.py:116`. | Two demo instances (or two sites in one): Japan with Japanese synthetic notes, SS-MIX2-shaped data and Asia/Tokyo; Taiwan with zh-TW notes and Asia/Taipei. Each clinician gets the site of their country. | new | yes |
| UX-005 | Medium | The SAE regulator follows the user's language, not the site: on the same Taipei site, ja shows PMDA, zh-TW shows TFDA, en shows "PMDA / TFDA". Follow-up column shows "8/0" with no legend. | By a run: `/sae` in the three languages. | Take the regulator and its rules from the site's country (`site.country`), name it the same in every language; spell the follow-up rule in words. | registered CR-009 (related) | yes |
| UX-006 | Blocker | No in-product feedback: no per-screen comment, rating or "this is wrong" anywhere except the excluded list's "send to review". A two-clinician PoC cannot collect structured feedback, and anything they write elsewhere loses the page, language and patient context. | By reading: `grep -ril feedback services/console/templates` = none; only `ex.wrong` in `i18n_review.py`. By a run: no such control on any of the 28 pages walked. | A "Feedback" control in the header of every page: rating (1 to 5), free text, category (wrong result, wording, slow, missing), auto-captured page path, language, role, time and pseudonym on patient pages; a warning not to type patient identifiers; stored in the trial database and exported as CSV for the owner; plus a per-criterion "I disagree" on the patient page. Acceptance: a ja and a zh-TW entry show up in the owner's export with their page. | new | yes |
| UX-007 | High | The two-model signal never appears for listed candidates in the demo: 0 opinion blocks on all 78 patient pages ("First check / Second check" renders only when opinions exist), so the clinicians cannot judge it. At the same time the excluded page labels 5 exclusions "記録の文章（2 つのモデルが一致）" that the stub produced, with no "test model" disclosure. | By a run: `scan.js` over 78 pages, `opin=0`. By reading: `templates/week.html:69`, `templates/_criteria.html:11`. | Seed the demo with recorded opinions from the real pair (from the G1 run) including agree, disagree and low-confidence cases; in DEV show "test model" next to any model-derived verdict; explain "first / second check" once on the page. | registered CR-003 (stub cannot disagree), new for the UX part | yes |
| UX-040 | High | One shared `pi` account and one shared password for every role (admin included). The two clinicians would share an identity: their marks, signatures and feedback cannot be told apart, and either can sign in as `admin`. | By reading: `tools/feas_demo.py:46-52`, `tools/demo.py:51`, `tools/e2e_simple.py:858` (`subpi`). | Seed named investigator accounts for the PoC (one per clinician, each PI of their own site's study, with a delegation-log entry), separate passwords, no admin password handed out. | new | yes |
| UX-014 | Medium | The demo has no IRB approval date and no consent-form version, so every Approach in the PoC is recorded as an override "with your name" (three seeded already). It teaches clinicians to click through a compliance warning. | By a run: `/studies/GZQO/irb` all "–"; Approach note "IRB 承認日がない 現在の説明文書の版がない". | Seed IRB approval number, dates and ICF version in the demo; keep one study without them to show the warning on purpose. | new | yes |

## 3. Findings: PI and sub-investigator journey

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| UX-008 | High | Evidence column empty for coded facts: on the patient page 17 to 18 of 25 rows have an empty "Evidence (verbatim, dated)" cell. "BMI ≥27: met · coded records" shows no BMI value, no date; the excluded list shows only "コード化された記録から 記録 1 件". A PI cannot verify a coded "met" or a coded exclusion without opening the EMR. | By a run: `tasks-pi-*.json` "emptyEvidence=17/25", "18/25". By reading: `templates/_criteria.html:11` (renders quote and date only). | Show for coded facts the value, unit, date and code (for example "BMI 29.4 kg/m² · 2026-09-12", "M10.9 · 2025-10-08", "ALT 34 U/L · 2026-10-01"); the same on the excluded list. Acceptance: no met / not met row without a value or a quote. | new (PI-list items in CR-086) | yes |
| UX-009 | High | English in ja and zh-TW pages where the clinician acts: criterion short labels (Age ≥18, Gout diagnosis, Willing to self-inject, Pregnancy), the full criterion text, the to-do lines ("confirm flare dates with patient", "ask injection willingness"), the feasibility meta ("patients with ≥1 encounter in the last 36 months"), the delegation-log history ("screen,approach,refer,enter_data"), the participant trail ("consent", "enrolment"), the entry form list ("demographics", "baseline"), the registry ("tier", "high", "review", "rc-bridge"). | By a run: `walk-full.json` leaks per page (Appendix A). | Make per-language short labels and to-dos a required step of approval (the label editor exists); translate the history codes and form names; show the criterion text in the site language with "original" on tap. | open since F-09, J-22 (R-72) | yes |
| UX-017 | Medium | ja verdict words read ambiguously for a clinician: inclusion met = 「該当」, exclusion present = 「該当（除外）」, exclusion absent = 「該当なし」, not met = 「非該当」; the same word 該当 is good on one table and bad on the next. 「人の確認」, 「記録の文章」 and the icon letter "P" for "for a person" are unclear. | By reading: `services/console/i18n.py` keys `verdict.*` (ja); `templates/week.html:66` (`'pending_human': 'P'`). | ja: inclusion 「満たす / 満たさない」, exclusion 「該当なし / 該当（除外）」, unknown 「不明（記録なし）」, person 「要確認（担当者）」, notes 「カルテ記載」, coded 「コード化データ（病名・検査・処方）」; replace "P" with an icon or "人". zh-TW 「需人工」 → 「需人員確認」. | new | yes |
| UX-015 | Medium | Sub-investigator: the Approach button is silently missing when the PI did not tick "approach"; nothing tells the doctor why or who can do it. | By a run: `subpi` markbar has Need info, Not suitable, Next only. By reading: `templates/_mark.html:32-36`; the help text `team.mark.help` exists but is not shown there. | Show `team.mark.help` (or "Approach is delegated to the PI; ask the PI") where the button would be. | new | yes |
| UX-013 | Medium | Referral after Approach is accepted: PI marked Approach (with the IRB override), then requested a referral; the patient now carries "Approach" and "waiting for the doctor's answer" and the CRC already has the call task. The treating doctor is bypassed by order of clicks. | By a run: screening log rows GZQO-0010, GZQO-0011 ("声をかける · … / 主治医の返事待ち"). | Requesting a referral suspends an existing Approach (confirm sheet: "Approach is paused until the doctor answers"); the CRC call task waits; test both orders. | new | yes |
| UX-034 | Medium | Treating physician: no account (by design) and no artefact. The referral leaves nothing the CRC can hand or send to the doctor (why the patient fits, what is asked, the study contact), so the CRC retells it by phone. | By reading: `i18n_team.py:69` ("the doctor needs no account"); no print or copy action on `/studies/{rs}/referrals`. | A "Copy request for the doctor" text and a one-page print in the doctor's language (study, criteria met, what is asked, CRC contact; chart number only after a recorded reveal). | new | yes |
| UX-019 | Low | Referral wording: ja 「紹介依頼」 and zh-TW 「轉介」 mean sending a patient to another doctor; here the study asks the treating doctor's agreement before contact. | By reading: `i18n_team.py:263-269` and zh-TW block. | ja 「主治医への了承依頼」, zh-TW 「徵詢主治醫師同意」. | new | yes |
| UX-016 | Low | The staff-directory select on the referral form shows "Choose a reason" (理由を選んでください) as its placeholder. | By reading: `templates/team_candidate.html:40` (`mark.reason.choose`). | Use a "Choose a doctor" key. | new | yes |
| UX-028 | Medium | SAE: the case page says "Waiting for the investigator's acknowledgement" but has no acknowledge button (it is only on the home / week banner); the trail line is raw developer text (`system:sync aware=, due=irb:2026-11-17 …, form_at=2026-11-10T18:09:07+08:00, form_by=console:crc, grave=0`); the register does not show the AE term. | By a run: `/studies/GZQO/sae/GZQO-0003/ae1` as `pi` (en). | Acknowledge button on the case page; a translated trail ("Entered from the AE form by crc on …; deadlines …"); the AE term and seriousness in the register row. | registered CR-104 (fixed part), CR-012 (trail) | yes |
| UX-020 | Medium | Morning digest list shows the send time in UTC as raw ISO ("2026-11-01 22:00" for a 07:00 site-time mail) while the footer says "Times are site time"; "Open" goes to today's list, not the mail as sent. | By reading: `services/console/step4.py:215` (`a[:16].replace("T"," ")`). By a run: `/notices/received`. | Format with the site zone; add "View the mail as sent" (the stored body), keep "Open today's list". | new (same family as CR-049/CR-050) | yes |
| UX-037 | Medium | The PI's week page spends the first screen on the six-step stepper, the SAE banner and the delegation-log nag; on desktop ja the first patient row starts at y≈700 of 860. | By a run: `walk-pi-ja-desktop-_week.png`. | Collapse the stepper for the PI once set-up is done; one-line banners with "show". | new | yes |
| UX-029 | Medium | Help: examples name `GOUT-COH` while the PI's study is GZQO; "This page" says Home when opened from the week list; "role guides will be provided at installation": there is no user guide for the PoC. | By a run: `/help` as `pi` in ja. | Examples from the user's studies; per-page help keyed on the back URL; a two-page PoC guide per language (section 8 can be its base). | open since F-10 (partly fixed) | yes |
| UX-031 | Low | Excluded list, "a rule of the run": the same reason repeated 5 to 7 times for one patient. | By a run: `/studies/GZQO/excluded?src=rule`. | Deduplicate per patient and criterion. | new | yes |
| UX-032 | Medium | The excluded list is 2,941 patients with no sample: on a phone it is 19,539 px tall; "look through some each week" gives no way to pick a fair sample; a patient sent to review does not return to the PI list. | By a run: `walk-full.json` heights. | Weekly random sample of 10 with its own counter; filter by criterion. | registered CR-014 | yes |

## 4. Findings: CRC journey

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| UX-011 | High | Screening log and participant page disagree on consent. After the consent form was saved for GZQO-0005 and GZQO-0006, the participant page says "Consented since 2026-11-10" and the screening log still says "contacted" (GZQO-0004 updated). | By a run: `consent.js` then `/studies/GZQO/screening-log` and `/studies/GZQO/subjects/GZQO-0005` (en). | One state source for the log and the participant; a test that saves consent and reads both. | new | yes |
| UX-012 | Medium | Three ways to record consent and two pages called "Screening log": the registry status select on `/pilot/registry/GZQO` (with raw values candidate / contacted / consented and an MRN field), the consent form on `/studies/GZQO/entry`, and the participant lifecycle; the nav "スクリーニングログ" opens `/pilot/registry`, the study link opens `/studies/GZQO/screening-log`. | By a run: forms dump of both pages; nav links on `/home`. | One "record consent" action from the call task and the participant page (opens the consent form); retire the registry status select for clinical users; one page named "Screening log". | open since F-20, F-35 | yes |
| UX-010 | Medium | EDC review shows codes, not words: "Sex 1" (no label), REDCap variable names first (`brthdat DM.BRTHDAT`), sources as hashes ("observation 56a4b2e2…"), item labels in English on zh-TW (ja has 生年月日 but zh-TW "Birth date"); the send result "sent 0 … REDCap has no record 3" gives no next step. | By a run: `task-crc-zh-TW-edc-flow.png`; review page text in ja. | Show the coded value with its label ("1 · male"), the label first and the variable name small; a readable source line ("lab 2026-07-07: 9.75 mg/dL"); per-language item labels from the map; "Create the record in REDCap first" next step. | new | yes |
| UX-030 | Low | EDC error shows the internal code beside the sentence ("… 未来の日付は不可）。 edc.visit_date"). | By reading: `templates/_edc_err.html:3` (prints `err.code`). | Show the code only under "Technical details". | new | yes |
| UX-035 | Low | The CRC's "Approved and contacted" list says "You approved contact, or the coordinator has contacted them" (PI wording). | By a run: `/studies/GZQO/week?list=approached` as `crc`. | Role-specific help text. | new | yes |
| UX-033 | Low | Registry page: English status words and an MRN text field to "add to the registry"; this page is the nav's "Screening log". | By a run: `/pilot/registry/GZQO` (ja). | See UX-012; at least translate the statuses. | open since F-35 | yes |

## 5. Findings: errors, sessions, layout, accessibility, language

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| UX-021 | Medium | Expired session: a mark posted after the session ended goes to the sign-in page with no "your session expired" line; the typed note is lost; after sign-in the user lands on the week list top, not the patient. Idle timeout is 10 minutes, short for a clinic where a PI leaves a patient open between consultations. | By a run: `expired-session-then-post` in 9 runs (`/login`, then `/studies/GZQO/week`). By reading: `services/console/auth.py:41`. | `next=` return to the page, keep the unsent note in the page (sessionStorage), say "Signed out after 10 minutes without activity"; make the idle time a site setting with 10 as default. | new | yes |
| UX-022 | Low | Network drop on a mark: the browser's own error page; the note is lost; no retry. | By a run: `network-error-on-mark` (`chrome-error://chromewebdata/`). | Small script: on failure keep the form, show "Not saved: no connection. Try again". | new | yes |
| UX-023 | Medium | CJK line breaking in narrow cells: on desktop ja the week table's status pill wraps one character per line (確/認/待/ち); on zh-TW the EDC "退回" button wraps 退/回. | By a run: `walk-pi-ja-desktop-_week.png`, `task-crc-zh-TW-edc-flow.png`. | `white-space: nowrap` on pills and buttons, a minimum width for the status column, `word-break: keep-all` for CJK labels. | open since F-06 (residual) | yes |
| UX-024 | Low | One font stack for every language with "Noto Sans TC" before "Noto Sans JP" and no `:lang()` rule: where Noto Sans TC is installed, Japanese text gets Chinese glyph forms. | By reading: `services/console/static/console.css:14`. | `:lang(ja) body { font-family: system-ui, "Hiragino Sans", "Yu Gothic UI", "Meiryo", "Noto Sans JP", sans-serif }`, the TC stack under `:lang(zh-TW)`. | new | yes |
| UX-025 | Medium | Phone: the full patient page is 6,025 px with the mark bar below the fold (the week sheet has a sticky bar, the full page does not); feasibility 11,978 px; on the phone sheet the "主治医に確認 / 詢問主治醫師" link is clipped at the left edge. | By a run: `walk-full.json` heights; `task-pi-zh-TW-phone-open_candidate_ready_list.png`. | Same sticky mark bar on the full page; padding on the referral link; a summary-first feasibility. | open since J-21, F-14 | yes |
| UX-026 | Low | Keyboard: 31 Tab presses from page start to the first patient on the week page (F-41 counted 14); an invisible "menu" checkbox takes focus on desktop; 12 more Tabs from a patient row to the first mark button. Focus is visible on all 31 stops and the skip link works. | By a run: `kbd.js` (ja, zh-TW). | A second skip link "to the worklist"; `tabindex=-1` on the desktop menu toggle; access keys for Approach / Need info. | open since F-41 | yes |
| UX-027 | Low | axe-core: one rule only, `empty-table-header` (minor) on 78 of 504 loads (participant, EDC, notices received, reports, feasibility). No contrast, label, landmark or heading violations. | By a run: `walk-full.json` (axe). | Visually hidden header text for action columns. | open since F-29 (mostly fixed) | yes |
| UX-018 | Medium | zh-TW names the CRC three ways: 研究護理師 (24 strings), 協調員 (24, e.g. the mark panel's 「給協調員的備註」), 研究協調… (7). Smaller: 「知情同意」 (Mainland usage; Taiwan regulations say 告知同意 / 受試者同意), half-width punctuation and the English word "instrument" in `dc.builtin.help` / `dc.import.help`. ja: 「プロトコール」 (2) vs 「プロトコル」 (15). No simplified characters found. | By a run: `cat.py` term counts over `CATALOGUES`. | One term per role (zh-TW 研究護理師（CRC）, ja CRC); a catalogue test that fails on the banned variants. | open since F-21, F-22 (mostly fixed) | yes |
| UX-038 | Low | Native date inputs follow the browser locale, not the page: an English Windows browser shows mm/dd/yyyy on ja and zh-TW pages. | By a run: phone tasks with an en-US browser. | Show the expected format beside the field ("YYYY-MM-DD"), or a text input with a pattern. | open since J-25 | yes |
| UX-036 | Low | The candidate page shows the full 32-character pseudonym as "Identifiers". | By a run: `/studies/GZQO/candidates/{pid}?purpose=referral`. | Show the 8-character code; full value under "copy". | new | yes |
| UX-039 | Low | No 和暦 anywhere (ISO dates only). Fine on screens; Japanese site documents (screening log to the 治験事務局) may need it. | By reading: no 令和 in the ja catalogue. | Owner question Q3. | new | no |
| UX-041 | Low | Desktop banner still "TB_ENV=DEV · 合成データのみ (D0)"; the phone banner is plain ("テスト環境・実在の患者なし"). | By a run: any desktop page. | Use the plain text on desktop too. | open since F-31 (partly fixed) | yes |

## 6. Measured tasks (machine time, clicks, page loads)

Desktop 1280 px unless marked. "c" = clicks, "f" = fields filled, "l" = page loads. Times are the script's wall time on a shared 4-core machine; a human adds reading and decision time (section 8 gives estimates).

| Role · task | ja | zh-TW | en | Notes |
| --- | --- | --- | --- | --- |
| Sign in (password, from the sign-in page) | 1.1 s c1 f2 l2 | 0.9 s | 0.7 s | PI lands on the week list; CRC on Home. Language choice on the sign-in page: +1 click. |
| Wrong password | 0.5 s | 0.4 s | 0.5 s | Clear message with the 5-tries / 15-minute lock and the admin's address. |
| PI: open the morning digest list and open it | 1.7 s c2 l2 | 0.9 s | 1.1 s | The list only; the mail itself cannot be read (UX-020). |
| PI: "Ready to decide" → first candidate | 2.2 s c2 l3 | 1.4 s | 1.6 s | Phone: the chart opens as a sheet at the top (chartTop 0). |
| PI: open the full page and read a criterion | 1.6 s c1 l2 | 0.8 s | 0.7 s | Unknown is amber, met green, not met red, person blue. Evidence empty on 17-18/25 rows. |
| PI: Need info with a note | 1.7 s c1 f1 l2 | 1.5 s | 1.1 s | Toast "Sent to the coordinator's task list" + Undo. |
| PI: Not suitable with no reason | blocked | blocked | blocked | Browser blocks: reason required (F-03 fixed). |
| PI: Not suitable with a reason | 1.2 s c1 f1 l1 | 0.6 s | 0.6 s | Toast + Undo. |
| PI: Approach (IRB warning) | 1.7 s c1 l2 | 1.1 s | 1.2 s | Recorded as an override (UX-014). |
| PI: flag an excluded patient as wrong | 0.7 s c1 f1 | 0.4 s | 0.8 s | "Sent to review, recorded with your name". |
| PI: request a referral | 1.1 s c3 l3 | 1.1 s | 1.7 s | Suggested doctor pre-selected. |
| PI: acknowledge the SAE | 0.9 s c1 l2 | – | – | One click on the banner; register keeps the case. |
| PI: switch EDC prefill on | 0.4 s c1 f4 l2 | – | – | Four typed fields (reference, date, pages, accuracy). |
| Sub-I: Approach | absent | absent | absent | Not delegated: no button, no reason (UX-015). |
| CRC: home tasks | 0.4 s l1 | 0.3 s | 0.4 s | Tasks "due 2026-11-01" (UX-003). |
| CRC: call outcome "Reached, visit booked" | 1.7 s c2 l3 | 1.5 s | 1.7 s | Screening number assigned. |
| CRC: consent form (find record, open, fill, save) | 1.2 s c4 f5 | 1.0 s | 1.1 s | Clear error when a conditional date is missing. |
| CRC: record the doctor's answer | 0.4 s c1 l2 | 0.5 s | 0.3 s | "The PI may now approach". |
| CRC: EDC draft → confirm → sign → send | – | 2.8 s c7 f4 | – | Refused for the visit date the subject page shows (UX-003). |
| CRC: screening log XLSX | 0.3 s c1 | 0.3 s | 0.2 s | `screening_log_GZQO.xlsx`. |
| Any: 403 page / unknown study | < 0.1 s | < 0.1 s | < 0.2 s | H1, sentence, Home / Back / Help, admin address. |
| Any: expired session then a mark | redirect to sign-in, note lost | same | same | UX-021. |
| Page loads (616) | p50 124 ms, p90 417 ms, max 1,085 ms (`/week`) | | | No 500, no raw key, no "None", no sideways scroll at 390 / 768 / 1280 px. |

## 7. Earlier reviews: fixed or still open (clinical roles)

| Earlier finding | Status today | Seen how |
| --- | --- | --- |
| F-01 chart number on the CASE job page | fixed (CR-099 verified fixed); not re-run here | register |
| F-03 "Not suitable" records "other illness" by default | **fixed**: empty first option, required, Undo in the toast | run |
| F-05 lockout, help and language on sign-in | **fixed** (no caps-lock hint) | run |
| F-06 phone chart panel far below the list | **fixed** (sheet with Back / Next and a sticky mark bar); residual one-character wrap on desktop ja (UX-023) | run |
| F-08 phone header a third of the screen | **fixed** (menu button) | run |
| F-09 English on ja / zh-TW pages | **open** (UX-009) | run |
| F-10 generic help, wrong examples | partly fixed; examples still another study (UX-029) | run |
| F-12 error pages without heading or way out | **fixed** | run |
| F-13 targets under 44 px | mostly fixed: 1,005 of 4,737 visible controls on phones are under 44 px, mostly in the delegation-log and candidates tables | run |
| F-14 feasibility report too long | open (11,978 px on a phone) | run |
| F-15 CRC home clinic list before the study cards | **fixed** (capped, "show all 16") | run |
| F-16 every row identical | partly fixed: rows now differ (16/24 … 20/24, unknown counts) | run |
| F-17 reveal first on the patient page; "First/Second check" unexplained | reveal moved to the bottom with "recorded with your name" (fixed); first/second check still unexplained and never shown in the demo (UX-007) | run |
| F-20 several names per page | partly: "今週の患者" consistent; two "Screening log" pages (UX-012) | run |
| F-21 / F-22 ja and zh-TW vocabulary | mostly fixed (no 箱, ジョブ, ルールセット, コンパイル, 規則集, 編譯; ログイン; 作業; 試驗委託者); remaining UX-018 | catalogue |
| F-26 notice settings | **fixed** (practitioner id pre-filled, mail language = UI language, subjects translated) | run |
| F-29 axe | mostly fixed (UX-027) | run |
| F-30 13 px text | **fixed** (15-16 px body; 11 px only on chart axes) | run |
| F-31 DEV banner | phone fixed, desktop open (UX-041) | run |
| F-34 language select + Change button | open | run |
| F-35 registry page wording | open (UX-033) | run |
| F-36 outcome box for unapproved patients | fixed (no outcome control on a Need-info patient) | run |
| F-37 pages for unknown studies | **fixed** (404) | run |
| F-38 PI reveal rule | **fixed** (D-143: PI reveals with reason and name) | run |
| F-41 keyboard header | open, now 31 Tabs (UX-026) | run |
| J-11 PI cannot reveal | **fixed** | run |
| J-12 no excluded list | **fixed** (`/studies/{rs}/excluded` with reason, source, "send to review"); re-entry open (CR-014) | run |
| J-13 SAE banner and acknowledgement | **fixed** (acknowledge, register keeps it); residual UX-028 | run |
| J-17 raw actor `console:crc` | open (SAE trail) | run |
| J-21 phone patient page mark bar below the fold | open on the full page; fixed on the week sheet | run |
| J-22 site labels not on the feasibility page | open (UX-009) | run |
| J-25 mm/dd/yyyy date inputs | open (UX-038) | run |
| F-02, F-04, F-07, F-11, F-18, F-19, F-23 to F-25, F-27, F-28, F-32, F-39, F-40, J-01 to J-10, J-14 to J-16, J-18 to J-20, J-23, J-24, J-26 to J-29 | not checked here: admin, set-up, data-steward or authorisation scope (reviewer 02b) | – |

## 8. The PoC script: what Dr Makoto (ja) and Dr Wenn (zh-TW) can do today

**Today** means the demo as it is, run by someone who first applies the workaround of UX-001 and keeps the process alive (UX-002). Both doctors sign in as `pi` (UX-040). Dr Makoto uses 日本語, Dr Wenn 繁體中文, each on a PC and on a phone. "Machine" is the measured time; "human" is an estimate for a first-time user (reading, one decision, about 1.5 s per click), to be replaced by the measured times of the PoC itself.

| # | Step | What to do | Expected result | Machine | Human (est.) |
| --- | --- | --- | --- | --- | --- |
| 1 | Sign in | Open the link, tap 日本語 / 繁體中文, type user and password, Sign in | The week list "今週の患者 · GZQO" / 「本週病人 · GZQO」; page `lang` is ja / zh-TW | 1 s | 30 s |
| 2 | Wrong password once | Type a wrong password | Message with the 5-tries / 15-minute lock and the admin's mail | 0.5 s | 15 s |
| 3 | Morning digest | Menu → 受信した通知 / 收到的通知 → 開く / 開啟 | One row "TrialBox：… の外来の試験候補者 1 名"; Open shows today's list (not the mail) | 1-2 s | 30 s |
| 4 | Candidate list | Worklist 判断できる / 可決定 (2) → first patient | Chart panel (phone: full-screen sheet) with "why this patient fits", unknowns, to-dos, mark bar | 1.5-2 s | 1 min |
| 5 | Review the criteria | 詳細なカルテ表示を開く → table of 24 criteria | Each criterion with met / not met / unknown / person; unknown is amber and says it does not exclude; quotes only for note-based rows; coded rows have no value (UX-008); no first/second check shown (UX-007) | 1 s | 3-5 min |
| 6 | Need info | Note "flare dates?" → 情報が必要 / 需要更多資訊 | Toast "CRCのタスクに送りました / 已送到研究護理師的任務清單" + Undo | 1-1.5 s | 30 s |
| 7 | Not suitable | Press 今回は見合わせる / 暫不邀請 without a reason, then choose a reason | First press blocked (reason required); second: toast + Undo; patient leaves the list | 1 s | 30 s |
| 8 | Undo | Press 元に戻す / 復原 | The mark is withdrawn | 1 s | 10 s |
| 9 | Approach | Another patient → 声をかける / 邀請 | IRB warning (no approval date, no consent version) then "approved, CRC has a task" (recorded as an override, UX-014) | 1-1.7 s | 45 s |
| 10 | Ask the treating doctor | 主治医に確認 / 詢問主治醫師 → keep the suggested doctor → 紹介を依頼する / 送出轉介請求 | "紹介を依頼しました。スクリーニングログに載りました。" / 「已提出轉介請求，並列入篩選紀錄。」 Do this **before** Approach (UX-013) | 1-1.7 s | 1 min |
| 11 | Excluded patients | 除外された患者と理由 / 被排除的病人與原因 → filter 記録の文章 → type a note → 誤りなので確認に回す | "確認に回しました…" / 「已送回審閱…」; ja reader sees Chinese quotes (UX-004) | 0.5-0.8 s | 3 min |
| 12 | Reveal a chart number | Candidate page → reason → カルテ番号を表示 | Chart number shown once, recorded with name and purpose | < 1 s | 30 s |
| 13 | SAE | Banner → 確認済みにする / 確認 → SAE 台帳 / SAE 登錄簿 | Acknowledged by pi with time; deadlines per party (regulator name follows language, UX-005) | 1 s | 2 min |
| 14 | EDC prefill switch (PI) | EDC 事前入力 → fill the 4 fields → オンにする | "スイッチを変更しました" | 0.4 s | 1-2 min |
| 15 | Screening log | スクリーニングログ (study link) → Download XLSX | `screening_log_GZQO.xlsx` | 0.3 s | 30 s |
| 16 | Errors | Open `/studies/NOPE/week` and `/ops/users` | 404 and 403 pages in the user's language with Home / Back / Help | < 0.1 s | 20 s |
| 17 | Phone pass | Repeat 4, 6, 9, 10 on a phone | Sheet at top, sticky mark bar, Next patient | 1-1.7 s each | 3 min |
| 18 | Sign out | Menu → ログアウト / 登出 | Sign-in page | 0.7 s | 10 s |

Total per doctor: about 25 to 35 minutes for one pass, plus a second pass on the phone.

What they cannot do today: leave feedback in the product (UX-006); see the two-model signal (UX-007); check a coded value (UX-008); read Japanese notes (Dr Makoto, UX-004); come back the next day to their own work (UX-002); work under their own name (UX-040). A CRC role (consent, call outcome, EDC review and signature) can be shown by the facilitator with the `crc` account (section 6) but the EDC visit date must be on or before the frozen demo day (UX-003).

### 8.1 PoC prerequisites (must be done before the clinicians start)

1. **UX-001** the demo starts from a clean checkout (FHIRHelpers in repo or skipped for the fake translator; CI job).
2. **UX-002** always-on host with persistent state; no reset on restart; README times corrected.
3. **UX-006** a feedback control on every page with an owner export.
4. **UX-040** one named investigator account per clinician, separate passwords, no admin password shared.
5. **UX-003** one clock: demo day = real day; no contradictory dates.
6. **UX-004** a Japanese demo site (Japanese synthetic notes, Asia/Tokyo) for Dr Makoto, the Taiwanese one for Dr Wenn.
7. **UX-007** recorded real-model opinions (agree and disagree cases) in the demo, or a clear "test model" label.
8. **UX-008** values and dates on coded criteria (else the PoC measures trust in an unverifiable table).
9. **UX-014** IRB approval and consent version seeded, so Approach is not an override every time.
10. **UX-009** ja and zh-TW short labels and to-dos for the demo study's 24 criteria.
11. A two-page guide per language (from section 8) and a named contact for the PoC (UX-029).

## 9. What is good (do not change)

- The phone patient sheet with Back / Next and the sticky 48 px mark bar; the full-page and sheet views share one mark vocabulary.
- "Not suitable" needs a reason; every mark has Undo in the toast; Approach shows the IRB warning inline and records the override.
- Unknown is visibly different (amber "?") from not met (red), and the text says "no value recorded: not excluded, please check".
- The excluded list with criterion, source ("coded", "notes, both models agreed", "rule") and "send to review" is exactly the check a PI needs.
- Referral: the suggested doctor pre-selected, "nothing here is required", the CRC records the answer by channel; Approach waits for the doctor when the referral comes first.
- Error pages (403 / 404) with a heading, a reason, three ways out and the admin's address; sign-in errors that explain the lock.
- Every page: `lang` set, one H1, focus visible, no sideways scroll at 390 / 768 / 1280 px, axe clean apart from one minor rule, 15-16 px text.
- zh-TW uses Taiwan vocabulary (資料, 帳號, 預設, 設定, 連結, 儲存, 試驗委託者, 人體試驗委員會, 受試者同意書, 主治醫師, 協同主持人) with no simplified characters; ja uses GCP terms (治験責任医師, 分担医師, 説明文書・同意文書, 実施医療機関の長, 重篤な有害事象).
- EDC review: every value with its source, unknown never drafted as "No", reason required for a change, password signature, read-back after send.

## 10. Proposed task cards for TB-PLAN-06

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| T-POC-01 (new) | Demo starts from a clean clone | `services/criteria_compiler/service.py`, `compile_cql/translator.py`, a pinned `FHIRHelpers-4.0.1.cql`, `demo/Dockerfile`, CI workflow | Fresh clone + `python -m tools.demo --no-serve` passes in CI; demo image builds and answers `/login` | – | S | yes |
| T-POC-02 (new) | Persistent, always-on PoC host | `tools/demo.py`, `demo/README.md`, `render.yaml` or a Cloud Run / VM recipe | Restart keeps marks, signatures and feedback; cold start under 60 s after first seed; README times true | T-POC-01 | M | yes |
| T-POC-03 (new) | In-product feedback | `services/console/templates/base.html`, a new `feedback.py`, store table, i18n (3 languages), owner export | Entry from any page stored with path, lang, role, time; CSV export; no free-text PHI warning shown; test per language | – | M | yes |
| T-POC-04 (new) | PoC accounts and site-specific demos | `tools/demo.py`, `tools/feas_demo.py`, `tests/inproc_box.py`, synthetic Japanese notes generator | Two named investigator accounts per site; ja site Asia/Tokyo with Japanese notes; zh-TW site Asia/Taipei; IRB and ICF seeded | T-POC-01 | M | yes |
| T-POC-05 (new) | One demo clock | `tools/list_demo.py`, `tools/e2e_simple.py`, fixture date shift | No page shows a date after "today"; EDC drafts the visit date the participant page shows; week and excluded pages show the same run date | T-POC-01 | S | yes |
| T-POC-06 (new) | Two-model signal visible | demo fixtures with recorded opinions, `templates/_criteria.html`, `week.html`, i18n | At least one listed patient shows first and second check with quotes, one with disagreement; DEV pages label the test model | G1 results | S | yes |
| T-UX-01 (new) | Evidence for coded facts | matching output (value, unit, date, code per criterion), `_criteria.html`, `excluded.html` | No met / not met row without a value or a quote; tests in ja / zh-TW / en | – | M | yes |
| T-UX-02 (extend R-72 / F-09 work) | Site-language labels, to-dos and history words | approval page label editor (required step), `i18n_team.py`, `i18n_review.py`, registry and life templates | Walk test: no English token outside an allow-list on ja / zh-TW clinical pages (reuse the leak check of this review) | – | M | yes |
| T-UX-03 (new) | Clinical wording pass (ja verdicts, zh-TW CRC term, referral words, プロトコル) | `i18n*.py` | Catalogue test with banned variants; a native ja and zh-TW clinician signs off the 40 clinical strings | – | S | no |
| T-UX-04 (new) | Workflow fixes | `home.py`, `team.py`, `_mark.html`, `team_candidate.html`, screening-log state | Referral after Approach pauses the Approach; sub-I sees why Approach is absent; screening log equals participant state after a consent save | – | M | yes |
| T-UX-05 (new) | Session and network robustness | `auth.py` (`next=`, message), `base.html` script (keep unsent form) | Expired session returns to the same patient with the note kept; a network drop keeps the form | – | S | no |
| T-UX-06 (new) | SAE and notices readability | `sae_pages.py`, `sae_case.html`, `step4.py:215` | Acknowledge on the case page; translated trail; site-time notices; regulator from site country (with CR-009) | CR-009 fix | S | no |
| T-UX-07 (new) | Layout polish | `console.css`, `week.html`, `_mark.html` | No one-character wrapping in pills and buttons (screenshot test ja / zh-TW); `:lang()` font stacks; sticky mark bar on the full patient page; second skip link | – | S | no |
| T-UX-08 (extend T-310 / CR-014) | Weekly excluded sample | `excluded.html`, store | 10 random excluded patients per week with a counter; sent-to-review returns to the PI list | – | S | no |

## 11. Questions only the owner can decide

1. **Where does the PoC run?** Recommended: one always-on small VM or Cloud Run with min-instances 1 per site language, synthetic data, persistent disk; not the Render free plan.
2. **Do the two clinicians test as PI only, or also as CRC?** Recommended: PI accounts for both, and a facilitator-led 15-minute CRC segment (consent, call outcome, EDC signature) with the `crc` account, because that is where most screens are.
3. **Do Japanese site documents need 和暦?** Recommended: ISO dates on screen; 和暦 only in exports the 治験事務局 files (screening log XLSX), if the site asks.
4. **Is a 10-minute idle sign-out right for clinic PCs?** Recommended: keep 10 minutes as the default, make it a site setting, and return the user to the same page after sign-in.
5. **Should the PoC show real-model opinions recorded from G1, or wait for the live pair?** Recommended: recorded opinions now (clearly labelled), live pair after G1b.

## 12. Assumptions

- The hosted demo is built from `demo/Dockerfile` on a clean clone; if the owner builds it locally with `.cache/jvm` present, UX-001 does not show there, but UX-002 still does.
- `tools.demo` (the Dockerfile default) is the demo the clinicians will use, not `tools.role_demo`.
- The frozen console clock in the demo means idle expiry never fires there; production uses the 10-minute idle of `auth.py:41`.
- "Treating physician" has no account by design (`i18n_team.py:69`); I reviewed what the CRC can give the doctor, not a doctor login.
- Human times in section 8 are estimates; the machine times are measured on a shared 4-core machine with other agents running.
- Synthetic pseudonyms quoted here (for example 150f7c12) come from the demo's made-up hospital.

## Appendix A. English tokens found on ja and zh-TW pages (desktop walk)

Week list, patient page, candidates: "Gout diagnosis", "≥2 flares /12 mo", "Pregnancy", "Current flare", "Willing to self-inject", "Planned surgery", "Other trial ≤30 d", "Pancreatitis", "Bariatric surgery", "Malignancy", "MI/stroke", "confirm flare dates with patient", "ask injection willingness", "ask about planned surgery", and the full criterion sentences ("Male or female participants aged 18 years or older at screening."). Excluded list: the same labels with ids. Feasibility: "hospital: patients with ≥1 encounter in the last 36 months" and every criterion label. Delegation log history: "screen,approach,refer,enter_data". Participant trail: "consent", "enrolment", "visit", "withdrawal". Entry: "demographics", "baseline". Registry: "tier", "high", "review", "REDCap record", "rc-bridge". EDC: "event_1_arm_1", REDCap labels "Sex", "Body weight (kg)", "Serum uric acid (mg/dL)" (zh-TW also "Birth date"). Source: `walk-full.json`, field `leaks`.
