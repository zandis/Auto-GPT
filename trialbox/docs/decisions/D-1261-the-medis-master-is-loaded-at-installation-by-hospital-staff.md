# D-1261 The MEDIS disease-name master is loaded at installation by hospital staff, and every function that uses it is complete

- **Card:** 10B-22 (lane J; renumbered from 10B-21, a number another card holds), pull request #1246, branch
  `agent/10b21-medis-at-install` (the branch name predates the renumbering)
- **Date:** 2026-11-19 (the owner's decision, given to the lane J coordinator)
- **Status:** proposed. The step is the one new page the owner approved for this card.
- **Depends on:** card 10B-2c (#1238): `adapter.licensed.load_release` and its dry run. This pull request lands after
  #1238.

## The owner's decision

The MEDIS-DC "ICD10対応標準病名マスター" maps Japanese disease names to ICD-10. It holds the disease-name table, the
modifier table and the index table. It is NOT bundled with TrialBox, and it never enters this public repository.

At installation, hospital staff open MEDIS's download page from a link. They download the release themselves, hand it
to the box and approve, and the box loads it. The owner wants every MEDIS function done now.

## Licence facts

- MEDIS forbids redistributing the master without its permission, so TrialBox does not ship it.
- A medical institution may download it free and use it free.
- Download page (shown as a link; the person opens it, the box never fetches it):
  https://www2.medis.or.jp/stdcd/byomei/download2019.html
- Terms: https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html
- MEDIS publishes a new release twice a year, in June and December.

No row of the master is in the repository, a fixture, a document or a message: no real code and no real name. The
tests use an invented release in the release's shape (`tests/medis_fixture.py`), with codes starting Z or 99 and names
built from テスト and ダミー.

## Decision

### A. The step (`/site/codes/medis`)

1. **Where it appears.** The country layer gains a value and its reader, a MINOR step: the layer file goes from
   1.1.0 (D-1255) to 1.2.0.
   - The country layer says whether a site uses the master: value `P7` `medis_master`, read by
     `sitesetup.medis_release:applies` (D-1250).
   - At such a site, the site set-up pages register the step, and the local codes page links to it.
   - At any other site, the routes are not registered and every page is byte-identical to master.
   - A broken layer offers no step. The box's health already reports a broken layer in red.
2. **What the page says.** In plain words, in en, ja and zh-TW (`console.i18n_medis`):
   - what the master is and why the box needs it;
   - MEDIS's two links;
   - what skipping the step means: "coded diagnoses from SS-MIX2 that carry modifiers read as unknown until it is
     loaded".
   The step can be done later from the same page.
3. **The hand-over** uses the upload pattern of the other set-up pages: the browser uploads the file, the console reads
   it into memory up to a cap and sends it to the orchestrator. `sitesetup.medis_release.vet` reads the zip in memory
   and writes nothing (review A, M2):
   - **caps:** the zip at 32 MB, at most 64 members, each file the loader reads at 16 MB, and all of them together at
     40 MB (the real tables are about 11 MB). Each file is read in pieces and counted; a header that understates a
     size fails the zip's check and is refused as a damaged zip;
   - **refuses:** an encrypted member, a second file of one kind (a second `nmain*.txt`, whatever its digits: refused
     before it is read), and a file that is not a zip;
   - **reads by base name only:** `readme.txt`, `nmain*.txt`, `mdfy*.txt`, `index*.txt`, `ttl_*.txt`. A member's
     folder is never used; the specification's PDF and Word files are never read;
   - **runs nothing.** Once vetted, the zip itself (not an unpacked folder) is written to a temporary folder for the
     loader and removed before the call returns, after a refusal too.
   The zip's bytes are never kept. Only the zip's SHA-256, the version and the counts are kept.
4. **Read without loading.** The page then shows:
   - the version and the release date;
   - the rows of each table, and how many disease rows are current;
   - the first 50 lines the loader would skip, with the table, the line and the loader's reason, and their number
     (review A, M1: never every line). The reason is the loader's own words and may quote the cell it could not
     read; it is shown to the person who sent the file only and never written to the audit, which keeps the count.
   Nothing is written to the terminology store. The orchestrator records the read itself: the zip's SHA-256, the
   person and the time (the set-up store's `setting` table).
5. **Approval.** The person ticks "our institution downloaded this release from MEDIS and may use it under MEDIS's
   terms". Their name comes from their sign-in; the orchestrator takes the verified person, never a field.
   The person then chooses the same file again. Without the tick, or with another file than the one on the page, the
   console refuses before it sends anything. The orchestrator then refuses, by its own record (review A, L1), a zip
   that THIS person has not read in the last 30 minutes (`LIC-NOT-CHECKED`): a load without a read, a read by
   another person, or a read too long ago.
6. **Load.** `licensed.load_release(store, zip, by=person)` loads the three tables in one transaction. The result
   names the counts. The page then shows the loaded version, the release date, the day (the site's day, not UTC's)
   and the person. The Load button is sent once (`data-once` in `console.js`); a load asked while another runs is
   refused at once with a plain message (`LIC-LOAD-RUNNING`, the loader's advisory lock asked without waiting); the
   loader's own lock and unique index keep one active table (card 10B-2c).
7. **Update.** A newer release is loaded the same way. The release in use stays in use until the new one is loaded
   whole. Once the loaded release is MORE than seven months old, the page shows a reminder; a release with no date
   says "release date unknown: no reminder can be given".
8. **Audit.** Every event is a `terminology.load`, the kind every licensed load already writes, so the audit schema
   and ROLE_EVENTS do not change (review A, M3 and L4):
   - `stage: approved`, written BEFORE the load starts: `kind: medis_release`, `approved: true`, the approval's
     sentence, `again`, `sha256` and `output_sha` (the zip's SHA-256). If it cannot be written, nothing is loaded;
   - the loader's own event for each of the three tables, where the audit folder is set (`TB_AUDIT_DIR`, as in the
     shipped container): kind, version, file name, rows and skipped count;
   - `stage: loaded` with the version, the release date, the counts and the number of skipped lines, or
     `stage: failed` with the loader's code.
   So a successful load in the shipped container writes five events, a failed one two (or more, as far as the
   loader got). None holds a row of the release. The set-up store's `setting` table records the last load (the same
   fields and the person), so the page can show the release date and who loaded it.
9. **Refusals.** A refusal shows the loader's code and reason (`LIC-…`), never a traceback. The upload codes
   (`LIC-UPLOAD-*`, `LIC-APPROVAL`, `LIC-NOT-CHECKED`, `LIC-ALREADY-LOADED`, `LIC-LOAD-RUNNING`) are worded in the
   three languages. A reason given by the loader is shown as the loader wrote it.
10. **Who may open it.**
    - The account that changes site set-up today, the matrix row `site.setup` (coordinator, administrator).
    - Every other account gets the same answer as for `POST /site/codes`; the role walk proves it, cell by cell.
    - The route-table rows are the Japan table's, copying `POST /site/codes`.
    - The orchestrator's routes take the same row (`AS_SITE`). Where the layer does not use the master they are
      absent: a dependency declared before the person is checked answers exactly as an unknown route (404,
      `{"detail": "Not Found"}`) for every method (review A, L3).

### A2. From the run on the real release (lane J, 2026-11-20)

- **One fingerprint.** The loader is given the zip itself, not an unpacked folder, so the store's `sha256`, the
  page and the audit events show the same value: the zip's SHA-256. The audit detail names it (`sha256`) beside the
  version and the counts, as well as in `output_sha`.
- **The same release again.** At the read step the page says "this release is already loaded (version, date, by
  whom)" when the zip's SHA-256 is the loaded release's, and the load then needs a second tick, "load it again"
  (refused otherwise: `LIC-ALREADY-LOADED`). The loader keeps the release it replaced and deletes the codes of older
  ones (card 10B-2c), so a second load leaves no third copy.
- **One term, several diseases.** When a local code or name points at several diseases (two entries of one name
  with different ICD-10 codes, an index term naming several, the successors of a deleted code), every one of them is
  offered, ranked by confidence (below), then current before deleted, then 採択区分, then the management number. The
  first is the suggestion; the others are kept beside it and the local codes page shows each, with its own "Use"
  button, as "one of N for this term". None is ever picked in silence and none is ever dropped in silence. A group
  that gives no ICD-10-CM code does not hide a later group. One code that several entries give is one candidate,
  said as "one of N names for this term" (review B, M8).
- **A deleted code by its code.** A code whose every row is deleted offers its rows' successors by its code as by
  a name, labelled `licensed_successor`.
- **One key for the index.** The stored index term and the query use one function, `licensed.index_key` (NFKC,
  every blank removed, upper case; card 10B-2c), and so does the 病名表記: a term in lower case, full width or with
  blanks inside is found (review B, M1).

### A3. The ICD-10 target (lane J ruling H1, 2026-11-20)

- **The master's code is WHO ICD-10 (2013)** and is named so in the data (`who`), on the page and here. It is never
  taken for its ICD-10-CM namesake: the two can mean different diseases under one number.
- **Site set-up.** The target is the same-numbered ICD-10-CM code only when the shipped ICD-10-CM list holds it as a
  billable code; a code with codes below it (a category or subcategory) is never a target, and a test runs over the
  whole list. The page shows "WHO ICD-10 (2013) <code>" and "same-numbered ICD-10-CM code <code>: <its title>. Check
  that it is the same disease"; a three-character code is shown as the ICD-10-CM family. No such code: no suggestion.
  A person confirms every one.
- **Confidence** (named constants, `sitesetup.medis_master.CONFIDENCE`), every one at or below the level a related
  term had (0.80), strictly descending (review B, M7): by the exchange code 0.80; by the 病名表記 0.78; an index
  term (同義語区分 0) 0.76; a near synonym (1) 0.72; a misspelling or variant form 0.68; a deleted entry's successor
  0.64; a related term (2) 0.55; a code whose local name differs 0.50. Each has its own method and words on the page.
- **The OMOP store** (`omop.vocab_load.load_licensed`) never writes `Maps to` from a master code to an ICD-10-CM
  code: it writes only the three-character family link (`TB in CM family`), as master did. The box's vocabulary
  bundle has no WHO ICD-10 vocabulary with mappings of its own (the register's `icd10-who` row is a site-loaded list
  with no Athena name), so there is nothing to map through. **Remains: WHO ICD-10 in the vocabulary bundle** (a card
  of the vocabulary lane).

### B. Every use of the master

The meanings below are lane J's reading of the release's specification (field names only are quoted here).

| Use | File | State |
| --- | --- | --- |
| Where the master is read | `sitesetup/mapping.py` `suggest` | **Fixed here (review B, M4, M5).** Only at a site whose country layer uses it (`medis_release.here()`), only in the main workspace, only for the condition domain; by name only the local display, never the code's text. Elsewhere the master's tables are not read at all. |
| Site set-up's code suggestion by the master's code | `sitesetup/mapping.py`, `sitesetup/medis_master.py` | **Fixed here.** A code's current rows are read; a deleted entry (変更区分 1) is never suggested. A code whose every row is deleted stands for its rows' successors (移行先病名管理番号), followed to a current entry (`licensed_successor`). A loop, a missing successor or ten steps: nothing. The master's answer for its own code stands: no shipped table or name guess is tried after it. When the local display names neither a row of the code nor one of its index terms, the suggestion says the name differs (`licensed_name_differs`, the lowest confidence; review B, M6). |
| Site set-up's suggestion by a local name | the same | **Fixed here.** Compared by the index's one key. Order: a row's own 病名表記; then the index (`TermStore.lookup_term`): 同義語区分 0, then 1, then a misspelling or variant form (異字体区分 1, 2), then 2 (a related term, `licensed_related`). A related term is related whatever its 異字体区分 (review B, H2). 同義語区分 8 (advised against) and 9 (search only), the code `0000` and a modifier's spelling (病名修飾語区分 2) are never suggested. Through the index each exchange code's current rows are read; a deleted row's successor only when every row is deleted (review B, M2). |
| 採択区分 | the same | **Read.** 1 and 2 own their exchange code; 3 is a synonym that borrows a 1/2 name's code. The suggestion shows the 1/2 name and says "the hospital's name is a synonym of this name". |
| 使用分野 | the same | **Read as a hint, never a filter.** 2 (mainly Kampo) and 4 (mainly dental) are said beside the suggestion. The specification calls the field a guide only. |
| 単独使用禁止区分 | the same | **Read as a hint, never a refusal.** 01: "usually written with a modifier". |
| 保険請求外区分 | — | **Not read.** It concerns insurance claims (not claimable when used alone); TrialBox makes no claim. |
| The ICD-10 taken from the master | `tb_common/icd10_who.py` `comparable`; `sitesetup/medis_master.py`; `adapter/validate/jpcore.py`; `omop/vocab_load.py` | **Fixed here.** ＩＣＤ１０‐２０１３ is WHO ICD-10 (2013), stored as the release writes it. For comparison one shared function writes it: `A99` as it is; `A999`, `A9999` with the dot after the third character (`E119` -> `E11.9`); `A999` and one lower-case letter (a Japanese sub-classification) without the letter (`E109a` -> `E10.9`); `A99-9` (a hyphen inside) and an empty value give none, never a guessed code. The target and the OMOP link: A3 above. The JP Core check names the master's form when it warns on a WHO code not written with its dot. |
| A code the ICD-10-CM list lacks, or holds only as a category | the same | **Decided here (D-130).** Site set-up suggests nothing: the local code stays unmapped until a person maps it, and its records read unknown. The OMOP store links it to its ICD-10-CM family when the family exists, else to nothing. Nothing silently becomes a different disease. |
| The rows with no ICD-10, and the hyphen form | the same | **Decided here.** No suggestion, no OMOP link: "no ICD-10 in the master", unknown. |
| An exchange code whose current rows disagree on ICD-10 | the same | #1238 leaves the code without an ICD-10 (`icd_conflict`): no suggestion. |
| ＩＣＤ１０‐２０１３複数分類コード | `sitesetup/medis_master.py`, `sitesetup/store.py`, `templates/_site.html` | **Fixed here, as lane J ruled.** Further ICD-10 codes of the same name: every one written by the same function and carried beside the suggestion (`also`), shown on the local codes page, in the place of and to the readers of the suggested code, as "also classified as …". Never the suggested code, never used to pick another disease, never sent to the lake. |
| What the master says beside a suggestion | `sitesetup/store.py`, `console/site_pages.py` | **Stored here.** One nullable column, `local_code.medis_detail` (set-up store version 3; a row from before it reads as none): the WHO code, the ICD-10-CM title, family, further codes, the deleted entry replaced, synonym, hints, the names count and the further candidates. **The API and the sheet do not carry it; owner to decide:** `GET` and `POST /api/v1/site/codes` drop the column (their keys are master's, review A, L2), the XLSX matching sheet keeps its columns, and `omop.vocab_load` never reads it. |
| The JP Core check: which 病名 codes are real and current | `adapter/validate/jpcore.py` | **Fixed here.** A code missing from the loaded release is a warning, as before. A code the release marks deleted (every row of the code 変更区分 1) is a warning too ("deleted in the loaded release"), never an error. With no release loaded, one information line per resource: "MEDIS codes not checked: no release loaded" (review B, M9). |
| The status lines | `templates/site_medis.html` | **Done here.** The step's page names the master, its version, its release date (or "release date unknown"), the site's day, who loaded it, and the disease names (rows) and codes (concepts), each labelled (review B, L1 to L3). It says the master's codes are WHO ICD-10 (2013) and that a same-numbered ICD-10-CM code is only a suggestion to check (L6). |
| Spelling variants (頚/頸, dash and long-vowel marks) | — | **Remains (review B, L7).** Not folded: such a spelling gives no suggestion (a missed suggestion, never a wrong one). |
| The SS-MIX2 reader's use (modifiers, current rows, the ICD-10 shape) | `adapter/sources/ssmix2/` | **Not in this card.** Card 10B-2c owns it. Its `who_icd10` writes `E109a` as `E109A` and passes `A15-9` (review B, M3): the reader is to call `tb_common.icd10_who.comparable`; agreed with the 10B-2c worker, in whichever pull request lands second. |
| Storing the release (the loader) | `adapter/licensed.py` | **Not in this card.** Card 10B-2c owns it (#1238): `check_release`, `load_release`, `index_key`, one concept per exchange code with every row kept, the row caps and the load lock. |

### C. The orchestrator's routes

`GET /setup/terminology/medis`, `POST /setup/terminology/medis/check` and `/load` are in the `setup` group of
`route_callers.yaml` (the console only) and so in its `refuse` stage of `route_actors.yaml`: each POST takes
`require_actor("site.setup")` (`AS_SITE`), the check the neighbouring set-up routes use; an unsigned call is refused
(the orchestrator's walks and `test_medis_step_10b22`). The GET returns no patient (`reads_without_patient`). Outside a
layer that uses the master all three answer as an unknown route, before the person or the body is read.

## What remains

- **#1238 on master.** `licensed.check_release`, `load_release`, `index_key` and `TermStore.lookup_term` are #1238's,
  merged into this branch; this pull request lands after it.
- **WHO ICD-10 in the vocabulary bundle** (A3): a card of the vocabulary lane.
- **The owner's decision** whether the API twin and the XLSX matching sheet carry what the master says beside a
  suggestion.
- **The SS-MIX2 reader's ICD-10 shape** (review B, M3): 10B-2c's file.
- **Spelling variants** (review B, L7).
- **"Purchased"** (review B, L5): this card's texts call the master MEDIS's and free; `console/i18n_site.py`, another
  card's file, still says 病院が購入した / 醫院購買的 for the licensed code lists.
- **Not measured:** the console spooling an oversized body before its cap applies (the pattern of the neighbouring
  upload pages), and a slow upload holding the console's event loop.
