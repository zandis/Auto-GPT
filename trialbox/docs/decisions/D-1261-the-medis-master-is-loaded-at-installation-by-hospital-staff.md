# D-1261 The MEDIS disease-name master is loaded at installation by hospital staff, and every function that uses it is complete

- **Card:** 10B-21 (lane J), pull request #1246, branch `agent/10b21-medis-at-install`
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

1. **Where it appears.**
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
   it into memory up to a cap and sends it to the orchestrator. `sitesetup.medis_release.unpack`:
   - **caps:** the zip at 48 MB, at most 64 members, and each table at 64 MB once unpacked (a header that understates the size
     fails the zip's check and is refused as a damaged zip);
   - **refuses:** an encrypted member, one table twice, and a file that is not a zip;
   - **unpacks by base name only:** `readme.txt`, `nmain*.txt`, `mdfy*.txt`, `index*.txt`, `ttl_*.txt`. A member's
     folder is never used, so a name that climbs out lands inside the box's folder;
   - **never unpacks** the specification's PDF and Word files;
   - **runs nothing.** The unpacked files go into a temporary folder that is removed before the call returns,
     after a refusal too.
   The zip's bytes are never kept. Only the zip's SHA-256, the version and the counts are kept.
4. **Read without loading.** The page then shows:
   - the version and the release date;
   - the rows of each table, and how many disease rows are current;
   - the lines the loader would skip, with the table, the line and the loader's reason.
   Nothing is written at this point.
5. **Approval.** The person ticks "our institution downloaded this release from MEDIS and may use it under MEDIS's
   terms". Their name comes from their sign-in; the orchestrator takes the verified person, never a field.
   The person then chooses the same file again: the box keeps nothing between the two steps, so it compares the
   file's SHA-256 with the one it read. Without the tick, or with another file, the box refuses before it sends
   anything.
6. **Load.** `licensed.load_release(store, folder, by=person)` loads the three tables in one transaction. The result
   names the counts. The page then shows the loaded version, the release date, the day and the person.
7. **Update.** A newer release is loaded the same way. The release in use stays in use until the new one is loaded
   whole. Once the loaded release is more than seven months old, the page shows a reminder.
8. **Audit.** The approval and the load are one `terminology.load` event. That is the kind every licensed load already
   writes, so the audit schema and ROLE_EVENTS do not change. The event holds:
   - `kind: medis_release`;
   - `approved: true` and the approval's sentence;
   - the version, the release date and the counts;
   - the number of skipped lines;
   - `output_sha`, the zip's SHA-256.
   It never holds a row of the release. The set-up store's existing `setting` table records the last load (the same
   fields and the person), so the page can show the release date and who loaded it.
9. **Refusals.** A refusal shows the loader's code and reason (`LIC-…`), never a traceback. The upload codes
   (`LIC-UPLOAD-*`, `LIC-APPROVAL`) are worded in the three languages. A reason given by the loader is shown as the
   loader wrote it.
10. **Who may open it.**
    - The account that changes site set-up today, the matrix row `site.setup` (coordinator, administrator).
    - Every other account gets the same answer as for `POST /site/codes`; the role walk proves it, cell by cell.
    - The route-table rows are the Japan table's, copying `POST /site/codes`.
    - The orchestrator's routes take the same row (`AS_SITE`) and answer 404 where the layer does not use the master.

### B. Every use of the master

| Use | File | State |
| --- | --- | --- |
| Site set-up's code suggestion by the master's code | `sitesetup/mapping.py` `suggest`, `sitesetup/medis_master.py` | **Fixed here.** A deleted entry (変更区分 1) is never suggested. An entry with a 移行先病名管理番号 suggests its successor, followed to a current entry; the method `licensed_successor` says so on the page. A loop, a missing successor or a chain of more than ten gives nothing. Without a successor: nothing. The master's answer for its own code stands: no shipped table or name guess is tried after it. |
| Site set-up's suggestion by a local name | the same | **Fixed here.** The name is matched, after NFKC with blanks removed, to the 病名表記 and to the index's spellings of a disease (索引用語 -> 対応用語コード). A modifier's spelling never names a disease. A name of two diseases (different ICD-10) gives nothing. This runs before the other name tables. |
| The ICD-10 taken from the master | `tb_common/icd10_who.py`; `sitesetup/medis_master.py`; `omop/vocab_load.py` `load_licensed` | **Fixed here.** ＩＣＤ１０‐２０１３ is WHO ICD-10 (2013), written without the dot (`E119`). The box writes it `E11.9` before any comparison. Before this card, `vocab_load` compared `E119` with the ICD-10-CM list: a code ICD-10-CM holds got only the family link (`TB in CM family` E11) instead of `Maps to` E11.9. The SS-MIX2 reader already wrote it with the dot (`who_icd10`; complete, 10B-2c's file). |
| A code the ICD-10-CM list lacks | the same | **Decided here (D-130).** Site set-up suggests nothing: the local code stays unmapped until a person maps it, and its records read unknown. The OMOP store links it to its ICD-10-CM category (`TB in CM family`) when the category exists, else to nothing (unknown; baseline correction 3, unchanged). The SS-MIX2 reader keeps the WHO code and leaves `icd10cm` empty (D-314, unchanged). Nothing silently becomes a different disease. |
| The 22 rows with no ICD-10 | the same | **Decided here.** No suggestion, no OMOP link, no ICD-10 in the record: unknown. |
| ＩＣＤ１０‐２０１３複数分類コード | — | **Never taken as the entry's code.** It is a second classification of the same entry. Whether any function should read it waits for the specification's sentence (asked of the coordinator). |
| The JP Core check: which 病名 codes are real and current | `adapter/validate/jpcore.py` | **Fixed here.** A code missing from the loaded release is a warning, as before. A code the release marks deleted is now a warning too ("deleted in the loaded release"), never an error. |
| 採択区分, 使用分野, 単独使用禁止区分, 保険請求外区分 | — | **Not read yet.** Their meaning is asked of the coordinator from the specification, not guessed. |
| The status lines that say "not loaded" | `templates/site_codes.html`, `templates/site_medis.html`, `adapter.licensed status` | **Done here** for the step's page: it names the master, its version, its release date, the day and who loaded it. The local codes page lists the master by name with version and day, as before. |
| The SS-MIX2 reader's use (modifiers, current rows) | `adapter/sources/ssmix2/` | **Not in this card.** Card 10B-2c owns it. |
| Storing the release (the loader) | `adapter/licensed.py` | **Not in this card.** Card 10B-2c owns it. Two findings were sent to it: (1) the title ＩＣＤ１０‐２０１３ keeps its U+2010 hyphen through NFKC, so master's loader, given the release's own titles, stores no ICD-10; (2) an exchange code on two or three rows (642 in the release) is dropped as "two rows with different content". |

## What remains

- **Dry run.** `licensed.check_release` (#1238) is the dry run this card calls. Until #1238 is on master, the tests use
  a stand-in with the agreed signatures.
- **The loader's storage shape.** `sitesetup.medis_master.rows` is the one place that reads it: the index table, the
  successor, the shared exchange codes. It follows #1238 once that shape is confirmed.
- **The specification's sentences** on the four flag fields, on the 複数分類コード and on the index's flags.
- **The coordinator's run** against the real release: counts and shapes only.
