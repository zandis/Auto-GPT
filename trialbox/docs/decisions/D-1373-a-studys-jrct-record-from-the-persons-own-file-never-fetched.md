# D-1373 A study's jRCT record from the person's own file, never fetched (10D-16a, the file half of 10D-16)

- **Task:** plan 10 card 10D-16 (`docs/plan/47-plan-10-2026-11-18.md`, line 559; review 14 card M14-15), its file
  half "10D-16a", lane K. **Date:** 2026-11-21. The number was set aside for this half in the lane K hand-over.
- **What the card asks for:** "jRCT intake: one record from a typed number or the person's own file; no names stored;
  no crawler", Decision 52 ("one record at a time, started by a person"), proof "A file with investigator names
  stores none". Review 14 (§5.2, M14-15): "a jRCT number typed, or the CSV the person downloaded", "must never store
  investigators' names or contacts"; jRCT's terms put names and contacts of researchers and review-board members
  outside the open-data licence and refuse crawlers. In a list:
  1. one record from a **typed number**;
  2. one record from **the person's own file**;
  3. no names stored; 4. no crawler; 5. one record at a time, started by a person.
- **What this half builds:** 2 to 5, file only.
  - `/studies/{rs}/registry-record` (and `GET /api/v1/studies/{rs}/registry-record`) shows the study's jRCT record;
    the page takes one CSV file (and `POST /api/v1/studies/{rs}/registry-record` takes the same file as a `text/csv`
    body, its content type checked before a byte of it is read). The page says in plain text, not as
    a link, where the person downloads the file themself: jRCT's website, the study's number, the terms, the search
    page's CSV download. **TrialBox never fetches jRCT data** (D-317): nothing here opens a connection, builds an
    address or reads a number a person types.
  - **The file is hostile input** (`tb_common.registry_file`): the request body is read up to 256 KB plus 16 KB and no
    further (a larger body is refused unread, so the form parser never spools it to disk); the file itself at most
    256 KB. Its **type is read from its content, never from its name**: ZIP/XLSX, PDF, old Office, gzip, UTF-16, a NUL
    byte, markup (a first character `<`: XML, HTML, SVG, a DTD with entities) and JSON (`{`, `[`) are refused; the text
    must be UTF-8 (a BOM allowed) or Shift_JIS and hold no control character but tab and line ends. **No XML or JSON
    parser runs on the file at all**, so no entity is expanded and no nesting is followed; nothing new is installed.
    The CSV is read strictly (`csv` with `strict=True`): at most 300 columns, 32,000 characters in any cell (a cell
    over Python's own csv limit is refused as too long too), the header in the first row, **a kept field present in
    more than one column refused** (one name twice, or two of its names such as `Title` and `Public Title`, or
    `jRCT番号` and `Trial ID`: which one is meant is not known, and a first-wins rule could keep a person's name as
    the title), a data row wider than the header refused, and **exactly one record** (a second data row is refused:
    Decision 52). A kept field holding a format character (direction marks and overrides, zero-width characters), a
    private-use or a control character is refused; a kept field starting with `=`, `+`, `-` or `@` is **refused, not
    rewritten**, so a later export can never turn it into a formula (a dash alone, "none", is kept). The record's number must be one jRCT number
    alone in its cell, as `tb_common.ctgov_record.registry_of` (D-1367) knows it; when the study's state page records
    a jRCT number, a file with another number is refused. The first rule broken refuses the file, with its own true
    message in en, ja and zh-TW (19 rules of the parser and `no_file`, `other_study`, `api_type`, `bad_form` and
    `store` of the console).
  - **Who reads:** exactly the readers of the study's state page (`/studies/{rs}/state`), the only page on master
    that shows the study's registry numbers and who changed them: the page and its API read ask that page's own check
    (`Helpers.state_reader`, set by `console.study_setup`), one choke point, so the administrator, the data steward
    and the privacy office read neither (as on master), and who read a file in is shown only to those who already see
    who changed the study's state. No read is widened.
  - **Who reads a file in:** the matrix's `study.state` row as it is (D-386: "change the study's state ... and its
    identifiers"): every coordinator who reads the study (the cell is `true`: the delegation log does not decide for
    a coordinator) and the PI the study's log names (the log decides for the investigator). It is asked before a byte
    of the body is read; a refusal is audited (`console.denied`). No row of the matrix changes. CSRF on the page; the
    form is on the field macro (9k-6a) with `data-guard`.
  - **Kept and where:** not the file: one JSON file per file read, holding the six kept fields, named `<sha256 of the file>.json` (a name the server chooses) in
    `<TB_CONSOLE_DIR>/registry_records/<STUDY>/`, folders 0700 and files 0600 owned by the console's own user, whatever
    the umask, as the box's other written files (`tb_common.firstrun`, `tb_common.kek`). It is written to a temporary
    name in the same folder and linked into place without replacing, so **the same file twice is kept once** (the
    second is audited as `same` and changes nothing on disk). A planted symbolic link in place of a folder is refused;
    a file in the folder that the box did not write (a link, or content whose study or SHA-256 is not its folder and
    name) is never shown, and a write over it is refused (`store`) instead of being reported as kept. The study code
    is matched whole (no trailing line end).
  - **The current record (keep-current):** the record of the file first read most recently, compared as times. A
    file read again, older or not, changes nothing on disk and is audited `same`; the page then says this file was
    read before and that the current record stays the one read last. The record's own "last update" date does not
    choose. No record is removed by this card (none is audited as removed).
    The upload's name is never used: not on disk, not in the audit, not on the page. The file's own bytes are never
    kept. Registered as not patient-linked (`outside:console_registry_records` in `tb_common.erasure`, O-16 in the
    record inventory).
  - **Audited before the page says so:** `console.registry_record` (`taken` with the jRCT number and the kept fields'
    names, or `same`) or `console.registry_record_refused` (with the rule's code: the parser's, `no_file`,
    `bad_form` for two file parts or too many fields, `api_type`, `other_study`, `store`), each with the account, the
    study, and the file's SHA-256 and size when a file was read; a body over the cap records `more_than` the cap (the
    rest is never read); never the file's content or name. A wrong CSRF token is refused (400) without an audit
    event, as every console form on master refuses one (no route audits it): it is a request the page did not make,
    refused before the file is looked at.
  - **Shown:** the six kept fields of the newest file, who read it and when, and the file's SHA-256; the files read
    before by number, day, account and the first 12 characters of their SHA-256. Every value from the file is
    escaped text; markup in a field is shown as its characters.
- **Kept fields (personal data):** a jRCT record names persons (the responsible and contact investigators, review-board
  members, their e-mail addresses and telephone numbers). **Kept and shown:** the jRCT number, the title, the health
  conditions, the recruitment status, the phase and the date of the last update, matched by the column aliases of the
  hospital's jRCT download loader (`tb_common.refdata_jp.JRCT_COLS`, D-317). **Not kept:** every other column,
  whatever it holds: all names, e-mail addresses and telephone numbers, the review board, the eligibility text and the
  summaries (the card needs none of them; the eligibility text belongs to a later card that compiles criteria from a
  registry record). **Not cleaned:** a title naming a person would be kept as written (titles name a study, not a
  person; no such title is known). That the aliases are the columns of jRCT's real download is **not verified**
  (review 14 "not examined"; no real download was made or fetched); the fixtures are synthetic.
- **Left to the owner's ruling (not built, not even a disabled field):** part 1, a typed jRCT number making the box
  fetch that one record. It needs a new outbound host and the use of jRCT's terms, against D-317 ("TrialBox never
  fetches or ships jRCT data") while the help desk's permission is pending (plan 10 card 10G-27). The question: "May a
  typed jRCT number make the box fetch that one record from jRCT?" Recommended answer: no; a number only names the
  record in a file the person gives.
- **For the owner (not changed here):**
  - master's `tb_common.refdata_jp.parse_jrct` (D-317, `site-load jrct --file`) keeps every column of a hospital's
    jRCT download in its row's `record`, stored in the reference data's `trial.record`: investigators' names and
    contacts are stored when the download carries them, unlike the ClinicalTrials.gov rows (`strip_names`, D-1367).
    It needs its own card.
  - the open point: `study.state` lets a hospital coordinator who reads the study read a file in even when the
    study's delegation log does not name them, the same as editing the study's identifiers on master's state page; a
    condition "on the log as CRC" would be a new condition of the matrix (`tb_common.authz`) and is asked, not built.
- **The invariant:** an intake never opens a network connection and never writes outside its own folder.
  `tests/console/test_registry_record_10d16a.py::test_an_intake_never_opens_a_network_connection_and_never_writes_outside_its_own_folder`
  makes every internet socket the process tries to create raise (and `getaddrinfo`, `create_connection`), sends
  hostile file names (`../../`, absolute, backslashes, encoded) with hostile contents through the page and the API,
  and compares the box's folder, a private temporary folder and the folders around them before and after: nothing
  changes outside `registry_records/`, and inside it only `GZQO/` (0700) and `<sha256>.json` files (0600).
- **Held by:** `tests/unit/test_registry_file_10d16a.py` (the hostile-file table: oversize, wrong type, entity
  expansion, external entity, deep nesting, a control character, a bad CSV, too wide, a cell too long, no header, a
  column twice, a wide row, no record, two records, bad numbers, path-like numbers, long fields; a file with
  investigator names stores none; markup kept as text; every message in three languages with the module's limits; the
  parser opens no socket, file or process), `tests/unit/test_registry_record_store_10d16a.py` (modes and owner under
  three umasks, the same file once, a planted link refused; run as root and as an ordinary user),
  `tests/console/test_registry_record_10d16a.py` (the readers equal to the state page's for every column of the role
  matrix, page and API read; every role on the page and its API twin, CSRF, audited before
  shown, the same file twice, names stored nowhere, markup escaped, the refusals in en/ja/zh-TW, the body cap,
  another study's number, the invariant), and the guards' rows (`role_route_matrix.md`, `route_actions.yaml`,
  `form_cases_9k6a.py`).
