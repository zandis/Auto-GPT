# D-1372 The study package, format v1: canonical tar, header, hash list, Ed25519 signature (10D-3)

- **Task:** lane A2, plan 10 row 10D-3 (review 14 M14-2; the owner's decision 47: federation by a signed package;
  decision 50, ruled: transport is a signed file on media or internal mail). · **Date:** 2026-11-19
- **Builds on:** D-1366 (the protocol part, its canonical form and the criteria hash), D-77 and D-210 (the update
  bundle's Ed25519 signature and its `key_id`), D-1102 (the rule-set zip caps), D-1226 (signed alliance tables),
  D-555 (a refusal is a returned sentence)
- **The owner's yes:** 2026-11-19 20:20 UTC, relayed by the integrator (D-504): "10D-3 study package export: yes."
  The export is the package as this file lists it, nothing more (see "What leaves the box" below).
- **What this card does not do, plainly:** nothing on the live path reads a package. No import, console page, route
  or role changes; `tb_common.study_package` is called only by the tests and by the operator's host command
  `python -m tools.study_package`, which no console action calls. The one audit change is that command's own event
  `approve.study_package_exported` (H4 below), with its label in `console/i18n_audit.py`.
- **Decision:**
  - A study travels as **one file** that `tb_common.study_package.build` writes from a study folder `rulesets/<ID>/`
    and a coordinating-centre Ed25519 private key, and `verify` checks against the trusted keys its caller
    passes, each trusted only for the studies its entry names (H5). The tool: `keygen --out DIR` (`cc_ed25519.key`, PKCS8 PEM, mode 600; `cc_ed25519.pub`, SubjectPublicKeyInfo
    PEM: the formats of `tools/sign_bundle.py keygen` and `tb_common.crypto`), `write /data/rulesets/<ID> --key K --out F
    [--created YYYY-MM-DD] [--force] [--trust-file T] [--audit-dir D] [--lang en|ja|zh-TW]` (never as root; the key
    file is read once by descriptor; an encrypted key is refused; an existing `F` is replaced only with `--force`;
    and see "The export, audited" below), `verify F --trust-file T` (see "Trusted
    keys" below), `show F`
    (the header, **not verified**: the line "the signature is NOT checked" comes first, on stdout and on stderr,
    then the header with every character outside printable ASCII escaped (`ensure_ascii`, and DEL), and the exit
    status is **3, "shown, not verified"**, so a script that tests for 0 cannot take a shown package for a verified
    one; `show` takes no trust file). Exit status: 0 done, 1 refused (one sentence), 2 usage or an internal error
    (one sentence, "could not be read (internal)", never a traceback; `verify`'s refusal of step `internal` is such
    an error and exits 2 too), 3 shown, not verified, 4 the trust file cannot be used (unreadable, unsafe or not a
    `tb-study-trust/1` file), for `verify` and `write`, so a script does not take an operator's setup error for a
    refused package (review 4 of c1a78033, L8). Every message the command prints passes through `printable` at
    its one exit point, whichever subcommand raised it (review of b9937b0d, item 2: a study-folder file named with
    ESC and BEL put them raw on stderr in `write`); the root refusal alone, the command's own sentence in the
    operator's language, is printed as written. `keygen` creates both
    files in the folder's descriptor (`O_CREAT | O_EXCL | O_NOFOLLOW`): an existing name, a link among them, is
    refused and nothing is written through it (it may run as root); the folder must be the running account's and
    writable by nobody else, since another account could otherwise replace the public key the sites are given
    (review 4 of c1a78033, L6). It prints key ids, never key material. No new
    dependency and no new cryptography: Ed25519 through `tb_common.crypto`.
  - **What a package carries:** the protocol part of D-1366 and the protocol's files, nothing else. No site part:
    no `status`, `scopes`, `routing`, serving `models`, `review`, `irb_reference`, `irb_approved_on`, `equivalence`,
    `terminology_tables`, `terminology_refused`, no criterion's review record (an IR file is carried without it;
    `{"status": "rejected"}` stays, as D-1366 keeps it in the protocol part), no `tests/equivalence.json`, no other
    file of the folder. A test plants names, addresses, an IRB reference, practitioner and department codes,
    a serving model and comments in every site field and file of a folder and finds none in any byte of the
    package (UTF-8 and UTF-16, any case).
  - **The archive.** POSIX ustar, exactly this: members sorted by the UTF-8 bytes of their names; each one 512-byte
    header block, then its bytes, then zeros to a whole block; then two zero blocks and **nothing after** (no record
    padding to 10240 bytes). Each header block: name (bytes 0–99) the member name in ASCII, NUL-filled; mode
    `0000644\0`; uid and gid `0000000\0`; size 11 octal digits and NUL; mtime `00000000000\0`; checksum (148–155) six
    octal digits, NUL, space, over the block with that field as eight spaces; typeflag `0`; linkname empty; magic
    `ustar\0` and version `00`; uname and gname empty; devmajor and devminor `0000000\0`; prefix (345–499) and bytes
    500–511 zero. No pax or GNU extended header, no link, folder or device. A member name is at most 100 bytes, its
    parts joined by `/`, each of ASCII letters, digits, `.`, `_`, `-` and neither `.` nor `..`.
  - **The members:** `files/<path>` for each protocol file (`<path>` its path in the study folder, under D-1366
    rule 4); `hashes.json`; `header.json`; `protocol.json`; `signature.ed25519`. Nothing else is allowed.
    - `files/<path>`: the file **as its rule of the canonical form leaves it** (D-1366 rules 2–4: a JSON file as RFC
      8785; a text file without a byte-order mark and with LF; an IR file also without its review record), so the
      sha256 of the carried bytes is the file's entry in the protocol part's `files`
      (`study_manifest.carried`, added by this card; the form is a fixed point).
    - `protocol.json`: the protocol part with its `criteria_sha256`, RFC 8785 (`study_manifest.dumps`).
    - `hashes.json`: RFC 8785 of `{member name: lowercase hex sha256 of its bytes}` for `protocol.json` and every
      `files/` member (not the header, the hash list or the signature).
    - `header.json`: RFC 8785 of an object with exactly these fields, each a non-empty text but `pins`: `format`
      (`tb-study-package/1`), `package_id`, `study_id` (the manifest's `id`), `version` (the manifest's `version`),
      `protocol_version`, `criteria_sha256`, `created` (`YYYY-MM-DD`, given by the writer; the library reads no
      clock), `key_id` (`ed25519:` and the first 16 hex of the sha256 of the raw 32-byte public key, the update
      bundle's `key_id`), and `pins` (an object). `study_id`, `version` and `protocol_version` are texts in the
      protocol part too, equal to the header's as texts: the manifest schema takes them only as strings (an unquoted
      `1.0` in `manifest.yaml` is refused, not read as the number 1), and the writer refuses an empty one. `package_id`
      is `<id>-<version>-` and the first 16 hex of the sha256
      of `hashes.json`: it names the content, so the same content signed on another day or by another key keeps its
      id. **A v1 header is closed:** a field it does not list is refused, and so is any key in `pins`, because a
      v1 reader knows none (`KNOWN_PINS` is empty). 10D-26 adds its pins as names a newer reader knows; an older box
      then refuses that package with "asks for the pin …, which a v1 reader cannot check; it needs a newer release of
      the box" rather than adopting it unchecked.
    - `signature.ed25519`: the 64 raw bytes of the Ed25519 signature over `b"tb-study-package/1 signature\x00"`,
      then the length of `header.json` as 8 bytes big-endian, then `header.json`, then `hashes.json`.
  - **The same study gives the same bytes** (a test): the same folder, date and key write the same file (Ed25519
    signatures are deterministic). The whole file has one hash because the framing is canonical: the reader
    compares each header block with the one v1 writes for that name and size, requires zero padding and names in
    strictly increasing byte order, so padding, an unused header byte, record padding or bytes after the end blocks
    that an ordinary tar reader ignores are refused here.
  - **JSON nesting:** every JSON the verifier parses (`header.json`, `hashes.json`, `protocol.json`, and each
    `files/…json`, which `study_manifest` parses) is refused, before it is parsed, when its arrays and objects nest
    deeper than **200** (`STUDY_PACKAGE_MAX_JSON_DEPTH`; counted on the bytes, brackets inside strings not counted;
    the deepest shipped file, RA-JAK's ELM, nests 87). The writer refuses such a file in the folder the same way.
  - **Memory:** before the signature verifies, `verify` holds the package's bytes once (`read_capped` reads the
    file in one read of its size; the members are views into those bytes, and only the header, hash list and
    signature, each capped, are copied); after it, a copy of the members too, about twice the input, so at most about
    400 MB at the caps (review 4 of c1a78033, L3). The tool reads a file only after its size is checked.
  - **Verify, in this order, one sentence each** (`PackageRefused`, its `step`; nothing is written anywhere, a test
    blocks every file open during it): (1) `tar`, its sub-checks in the order the code makes them: the whole package
    at most 200,000,000 bytes (`read_file`: the file opened once, `O_NOFOLLOW | O_NONBLOCK`, a regular file on that
    descriptor, not a FIFO, device or folder, and at most the cap plus one byte read from it; the command's trust
    file the same way: `read_trust_file` is `read_capped` with its owner and mode checks run on that descriptor, so a
    folder is refused in one sentence and no descriptor is left open); whole 512-byte blocks, at least two; then for
    each block: the two end blocks and nothing after them, the checksum and size fields plain octal, the checksum,
    the `ustar` magic, a regular file, an empty prefix field, an ASCII name, the name rules, no duplicate, at most
    2,000 members, the member's size cap (100,000,000 bytes; **64 KiB for `header.json` and 1 MiB for
    `hashes.json`**, the two members read before the signature: the shipped packages' are at most 296 and 5,390
    bytes, so about 220 and 190 times that, and 1 MiB holds 2,000 entries; a larger one is refused from its tar
    header before a byte of it is scanned or parsed; 4 MiB for `protocol.json` and `signature.ed25519`), all members together at most 200,000,000 bytes, the member's bytes present, the
    canonical header block, zero padding and name order; then the four fixed members present, only allowed names, a
    64-byte signature, the header's nesting (`json_depth`: one pass over the bytes tracking string, escape and depth,
    no regular expression, so linear whatever the bytes; the regex it replaces took 38 s on an 80 KB header of
    escaped quotes, quadratic, with no signature needed), JSON, RFC 8785 form and v1 fields, the hash list's nesting, JSON, RFC 8785
    form and entries; (2) `signature`: the header's `key_id` is one of the trusted keys, that key's entry is for
    study packages (not `update`), the signature verifies with it, and the header's `study_id` is one the entry names
    (H5); (3) `hashes`: each member's sha256 is the listed one; (4) `members`: no member outside the list,
    none missing; (5) `protocol`: `protocol.json` holds no site field (named: `routing`, `scopes`, … ; review item
    12), is a protocol part that holds its own criteria hash (`study_manifest.protocol_refusal`), the header's `study_id`, `version`, `protocol_version` and
    `criteria_sha256` are its, each carried file is in its canonical form, the files' hashes are exactly the protocol
    part's `files`, the criteria hash computed again from them is the header's, and the header's `package_id` is the
    one its `study_id`, `version` and `hashes.json` give, and then (H3, the last check) the criteria the protocol part's
    manifest names are exactly the carried `ir/` files (`criteria_refusal`: each id once, each with its
    `ir/<id>.json` whose `id` is that id, no `ir/*.json` it does not name, and, when it names a CQL `library`, its
    `cql/<library>.cql` and `cql/elm/<library>.json` carried). The writer makes the same check before it signs.
    Then, **last** (review item 6), the writer's guards over the carried files (`content_refusal`): each JSON file
    through its model (IR, value set with item 9's systems and codes, ELM library keys), the test patients' allow-list
    and synthetic site (H1) and `tests/expected.json` (H2). So signature and hashes are checked before any content
    is parsed, as before; a package another writer signed is held to what this writer packs.
  - **"A changed byte fails verification"** is held by flipping every byte of a package (one bit, then all eight),
    and by named classes: header, hash list, signature, protocol part, a protocol file, a tar header's name, mode,
    mtime, owner, checksum and unused bytes, the padding, the end blocks, bytes appended, the archive cut short.
- **Test patients and the site-local code system (after the owner's yes):**
  - `SITE_LOCAL_CODE_SYSTEMS` names `https://trialbox.local/fhir/CodeSystem/department` as a hospital's own code
    system, not a protocol's: a criterion that uses it (GZQO `VS_RHEUMATOLOGY_OR_METABOLISM_CLINIC_VISIT`, NEUR-COH
    `VS_MEMORY_CLINIC_VISIT`) names codes each site maps to its own (10D-4). Such a value set still travels as it is;
    the format is unchanged.
  - **The writer's guard (an allow-list; reviews of 50a07a81 and 0a0f65b5 on PR 1183).** `build` refuses, with one
    sentence that names the line number and the last element the allow-list knows, never a value, an unknown key or
    an unknown resource type, a study whose `tests/patients.ndjson` holds, in this order: nesting deeper than 200; a
    UTF-8 byte-order mark anywhere in the file; a line that is not a JSON object (a key twice, `NaN` and `Infinity`
    are not JSON); **any key, at any depth, that is not an element name** `[A-Za-z][A-Za-z0-9]*` (checked over the
    whole line before any path is looked up, so a key holding `.` such as `"serviceType.coding.code"` cannot read as
    a path, and no `_` key, empty key or look-alike letter passes; the shipped files use no other key); a
    `resourceType` other than the twelve the shipped test patients hold, exact case (`Appointment`, `Claim`,
    `ClaimResponse`, `Condition`, `Consent`, `Coverage`, `DiagnosticReport`, `Encounter`, `MedicationRequest`,
    `Observation`, `Patient`, `Procedure`); any element outside `TEST_PATIENT_ELEMENTS` (for each type, the paths of
    keys the shipped files carry, an array's items taking the array's path; `contained` and a nested `resourceType`
    are outside it); an array where the shipped files hold none (`TEST_PATIENT_LISTS`, so an array at a leaf other
    than `meta.profile`, or an array inside an array), a single value where they hold an array, an empty array or
    object, an object where they carry a value, a value where they carry an object; a reference object with a
    `display` or an `identifier`; a code of the site-local department system other than exactly a
    `PLACEHOLDER_DEPARTMENTS` code (no trimming; a code that is not a text is refused too); then each leaf by its
    **measured type** (`TEST_PATIENT_NON_TEXT`): `Claim.insurance.focal` a boolean; `Claim.insurance.sequence` and
    `Claim.item.sequence` an integer from 1; `Observation.valueQuantity.value` and
    `Observation.component.valueQuantity.value` a finite number of magnitude at most 1,000,000,000 (the shipped
    largest is 416.21; `1e999999`, which Python reads as infinity, is refused); every other leaf a non-empty text
    of at most **200** characters (`TEST_PATIENT_MAX_TEXT`; the longest shipped text is 92, an
    `Observation.meta.profile`) with no control character, line or paragraph separator or byte-order mark; `null` is
    refused everywhere; `Resource.id` a FHIR id `[A-Za-z0-9\-\.]{1,64}`, matched whole; a `reference` not written
    exactly `<type>/<id>`, matched whole (`fullmatch`, so a trailing newline is refused), type one of `Claim`,
    `Coverage`, `Encounter`, `Organization`, `Patient`, `Practitioner`, exact case, id a FHIR id (so no URL, no `#`,
    no space); a `Practitioner/` id outside `PLACEHOLDER_PRACTITIONERS`; an `Organization/` id other than
    `hospital` and `nhi` (`PLACEHOLDER_ORGANIZATIONS`); a `system` that is not exactly one of the 21 of
    `TEST_PATIENT_SYSTEMS` (the standard terminologies ICD-10-CM, LOINC, UCUM, ATC and eight `terminology.hl7.org`
    code systems; the placeholder systems under `trialbox.local` and the reserved `.test` domain); a `meta.profile`
    other than the ten TW Core profiles (`TEST_PATIENT_PROFILES`). The lists, types, arrays and caps are measured
    from the five shipped files, and tests measure them again (equality for the lists and types). A test refuses
    each of the first review's fourteen bypasses and seven more, and each of the second review's shapes (33 cases: dotted
    keys, a list or an object or a number or `null` where a text is, lists of lists, a list at a leaf, a byte-order
    mark, an infinite or absurd number, a long text, an id with a space, a separator or over 64 characters, a
    reference with a trailing newline, unknown keys and types that read as names) with a `ValueError` whose sentence
    repeats none of them; all eight shipped studies still pack.
  - **The test patients travel in their text form, not re-serialised.** The criteria hash covers the file as text
    (D-1366: no byte-order mark, LF), and 828 of the shipped files' 30,551 lines are not RFC 8785, so carrying each
    line re-serialised from the checked object would change the shipped studies' criteria hashes. What travels is
    the checked line itself: whitespace between JSON tokens and the escapes inside a string are the only bytes that
    are not a checked value, and an escape decodes to a character the checks above saw.
  - **The test patients are the synthetic site's (review of f1d1fe3c, H1).** After every line passes the allow-list,
    `build` refuses, naming the line and never a value: a `Patient` whose `id` is not the pseudonym, under the
    **synthetic site's public key** (`SYNTHETIC_SITE_KEY`, the test stack's `site_hmac.key` of the Makefile and
    `tests/conftest.py`), of a **synthetic chart number** (`SYNTHETIC_MRN`: a site digit 1 to 9, then the patient's
    number in seven digits, 1 to `SYNTHETIC_MAX_PATIENTS` = 2,500, as `tools/make_fixtures.py` and
    `tools.synth_hospital` number them; `synthetic_pseudonyms()`, 22,500 HMAC-SHA256 truncated to 32 hex as
    `pid_for_mrn` takes them, on the chart number as written, so no chart-number setting of the box changes it); a
    `Patient` whose `identifier` is not exactly `[{"system": "https://trialbox.local/fhir/sid/pid/DEMO-A", "value":
    <its id>}]` (each entry; at least one); a `Patient` twice; and any line with a `Patient/` reference to a patient
    the file does not hold. Then (review of ec90c1b4, item 5) every record other than a `Patient` must name one of
    the file's patients in its own element, measured per type from the shipped files (`TEST_PATIENT_SUBJECT`:
    `subject` for Condition, DiagnosticReport, Encounter, MedicationRequest, Observation, Procedure; `patient` for
    Claim, ClaimResponse, Consent; `beneficiary` for Coverage; an `actor` among an Appointment's `participant`); its
    `id` must have the shape every one of the 29,551 shipped records has, 32 lowercase hex digits
    (`TEST_PATIENT_RECORD_ID`: the adapter's HMAC of the source record's id; only the shape is checked, since the
    source id is not in the file); and **every reference of any type must name a record of the same file** (same
    type and id), except the placeholder practitioners and organisations, which `_reference_refusal` already holds
    to their lists. Since the review of 02b55d8a (item 9) a reference must also name a record **of the same
    patient** as the record that holds it (a Claim cannot name another patient's Coverage), its type must be the one
    its element takes (`TEST_PATIENT_REFERENCE_FIELDS`, measured: e.g. `Claim.insurance.coverage` only `Coverage`,
    so `Patient/<pid>` there is refused), and no type and id is held twice. All five shipped files pass unchanged (each `Patient` is site-a's, chart numbers
    10000001 to 10000600), so no fixture and no criteria hash changed. This was chosen over a new marker stamped by
    the generator because a marker in the test patients would change them and so every shipped criteria hash
    (D-1366) and the goldens that pin them; the pseudonym scheme is already in every shipped file.
  - **What H1 proves, and what it does not.** It proves where the records were pseudonymised: by the test stack,
    from a chart number in the synthetic generators' numbering, under a key published in the repository. A box's own
    patients are pseudonymised under that box's secret key (D-09), so an export of a box's real ingested records is
    refused (the chance that a real pseudonym equals one of the 22,500 is about 22,500 in 2^128). It does **not**
    prove that the content is synthetic: the key is public, so anyone can compute a synthetic pseudonym and write a
    real person's dates, codes or report under it by hand; and a real hospital that numbered its chart numbers in
    the same range and ingested them under the public test key would pass. So `write` checks the box's own key
    where it can (review 4 of c1a78033, L5): when the run can read `site_hmac.key` in `TB_SECRETS_DIR` and its
    fingerprint is the public test key's, it refuses to pack; the audit event (`site_key`) and the success line say
    whether the key was compared at all. **In the supported run it is not**: the criteria compiler's container is not
    given the site key, and giving it (or the lake's fingerprint record) to that run would be a new read of a secret,
    which is the owner's to decide; there H1 rests on the box not running with the test key. `write` prints this limit to the
    operator at pack time, in one sentence (three languages): the check cannot prove the content is synthetic, and
    the person who packs the study answers for it. The leaves below still travel **as
    typed**, unchecked against any real record (each within the type and the 200-character cap above): the 32 hex digits of each record's `id`
    (their shape only, item 5; a reference names one of them or a placeholder), `Patient.birthDate`, `Patient.gender`,
    `Patient.identifier.value`, `Encounter.identifier.value`, every date and time (`birthDate`, `onsetDateTime`,
    `recordedDate`, `effectiveDateTime`, `performedDateTime`, `authoredOn`, `created`, `dateTime`, `start`, `end`,
    `period.start`, `preAuthPeriod`, `validityPeriod`), every `code` and `display` of a coding (but the department
    system's), `MedicationRequest.medicationCodeableConcept.text` and `dosageInstruction.text`,
    `Observation.valueCodeableConcept.text`, quantities (`valueQuantity` and `component.valueQuantity`: `value`,
    `unit`, `code`), the `status`, `intent`, `use`, `outcome`, `class.code` and `provision.type` codes,
    `Claim.insurance.focal` and the `sequence` numbers, `DiagnosticReport.conclusion` (free text: a report's
    conclusion) and `ClaimResponse.disposition` (free text). The shipped files carry no name, telecom, address,
    contact, photo or note, and those are refused. A coordinating centre that types real patients' details into
    those fields under synthetic pseudonyms gets them packed: that the content was generated (`tools.synth`) is the
    owner's rule (synthetic or public data only), which the writer supports but cannot see.
  - **`tests/expected.json` (H2).** `build` refuses, in one sentence that repeats no value, an `expected.json` that is
    not JSON or not an object of exactly `EXPECTED_FIELDS` (`engine`, `index_date`, `patients`, `ruleset`,
    `source`, `version`, and optional `agreement`); whose `ruleset` and `version` are not its manifest's; whose
    `index_date` is not a date; whose `engine` or `source` is not one of the closed sets measured from the eight
    shipped files (`EXPECTED_ENGINES`, 3; `EXPECTED_SOURCES`, 4: the synthetic generators' runs; a test holds both
    equal to the shipped labels); whose `patients` is not an object of 1 to 10,000 entries keyed by synthetic chart
    numbers (as above), each an object of criterion ids the manifest names to `true`, `false` or `null`; whose
    patients, when the study carries test patients, are not exactly the chart numbers of its `Patient` lines (the
    five shipped pairs match exactly, 200 each); and whose `agreement`, when present, is not exactly `all_equal` (a
    boolean), `known_differences` (empty: the writer's `KNOWN` table is empty, and its values would be words),
    `patients` (the integer number of patients) and `per_criterion` (criterion ids to a number from 0 to 100 with at
    most one decimal: the 14 shipped values each carry one, so no value carries digits of its own; review of
    ec90c1b4, item 7). So no free text and no identifier but a synthetic chart number travels in it. For the three
    studies with no test patients (AD-MAB, NEUR-COH, RA-JAK) the chart-number keys are only held to the synthetic
    numbering, not tied to records: within it they **travel as typed**.
  - **Protocol files a package carries (`PACKAGE_FILES`, `carriable`).** The criteria hash (D-1366,
    `study_manifest.PROTOCOL_FILES`, unchanged) covers every file the engine reads, including any file under
    `cql/elm/` and files in subfolders, so that a planted file changes the hash. A package carries only one file name
    directly in its folder, not hidden (no leading `.`), of ASCII letters, digits, `.`, `_` and `-`: `ir/*.json`,
    `valuesets/*.json`, `cql/elm/*.json`, `cql/*.cql`, `sql/*.sql`, and `labels.yaml`, `tests/patients.ndjson`,
    `tests/expected.json`. `build` refuses a folder holding a file that the hash covers, or that sits under `ir/`,
    `valuesets/`, `cql/` or `sql/`, and is not one of these (a hidden file, a subfolder, `cql/elm/` other than
    `.json`); the verifier's member rule (check 1, "only allowed names") takes the same narrower set. Each JSON file
    the hash covers must parse. Each `ir/*.json` must load as `CriterionIR` **strictly, as JSON, by its field names**
    (`model_validate_json(strict=True, by_name=False)`: extra fields forbidden at every depth, no lax type such as
    `"yes"` for a boolean, no Python name such as `class_` for an aliased field), as written and as carried; its
    `flags` must each be one word of the compiler's (`[a-z][a-z0-9_]{0,63}`, as 10D-28's rule-set export takes
    them); its `provenance` may hold only `calls`, each a call id (`[A-Za-z0-9\-\.]{1,64}`; nothing in the product
    writes `drafted_by`, `model_route` or `agreement`). Each `valuesets/*.json` must load as `ValueSetFile` (strict,
    extra fields forbidden: what `criteria_compiler.terminology.mapper.valueset` writes; no product model of the file
    existed), whose `extension` may only be the mapper's `FAMILY_EXT`
    (`https://trialbox.local/fhir/StructureDefinition/code-family`) with a `valueString` of `<system>|<code prefix>`
    (`https?://…|[A-Za-z0-9.-]{1,32}`), and whose `meta.tag` may only be `REVIEW_TAG_SYSTEM`
    (`https://trialbox.local/fhir/CodeSystem/review-flag`) / `needs_review` (a test holds both constants equal to the
    mapper's). Each `cql/elm/*.json` must be an object whose only key is `library`, holding only the ELM library's
    keys (`ELM_LIBRARY_KEYS`: `identifier`, `schemaIdentifier`, `usings`, `includes`, `parameters`, `codeSystems`,
    `valueSets`, `codes`, `concepts`, `contexts`, `statements`, `annotation`, and `localId`, which the shipped files
    carry). **The keys inside the library are not checked here:** the ELM node allow-list arrives with 10D-28
    (`ruleset_part`, PR 1174) and is needed by the importer, 10D-4; until then an ELM file's nodes, annotations and
    any string in them travel as written.
  - **The folder on disk.** `build_dir` reads through `read_folder`: the folder is opened once as a directory
    descriptor with `O_NOFOLLOW` (a symbolic link given as the folder is refused; the components of the path *to*
    the folder are resolved as usual), and walked by descriptor: each entry is examined with `stat(dir_fd=…,
    follow_symlinks=False)`, each subfolder opened with `O_DIRECTORY | O_NOFOLLOW` in its parent's descriptor and
    checked to be the folder listed, each file opened with `O_NOFOLLOW` in its folder's descriptor and checked on
    the open descriptor. So a folder or file swapped for a link between the listing and the open is refused, and one
    swapped after its folder is open is not followed (tests simulate both, as the reviewer's probe did). A symbolic
    link anywhere inside the folder and anything that is not a regular file or folder (a pipe, a device, a socket)
    refuse it. Only `manifest.yaml` and the files a package carries are read: a file with another name on the disk
    (`st_nlink` > 1, a hard link) is refused, and its size is checked against the cap before a byte is read (4 MiB
    for the manifest, 100,000,000 bytes for a protocol file, 200,000,000 together). The docx template, and a file
    the hash covers or under `ir/`, `valuesets/`, `cql/` or `sql/` that a package does not carry, refuse the folder
    without being read; every other file (`tests/equivalence.json`, notes, anything else) is not read at all.
  - The writer and the verifier both check the test patients (H1), `tests/expected.json` (H2), the models and the
    criteria set (H3): the verifier as the last check of step 5 (review item 6). The writer alone checks what only a
    folder has (hidden files, subfolders, links, the template, the manifest's `status`).
  - **No text of the sender before the signature, everything shown escaped (review of 02b55d8a, item 2).** A
    refusal before the signature never echoes text the sender chose: an unknown header field, a pin, a hash-list
    entry or a bad member name is named by its place (member, field index) and its length; so is a member named
    twice, a member over its size cap and a name a v1 package may not hold, even one that passes the name rules
    (review of b9937b0d, item 4: "holds files/ir/ALL-CHECKS-PASSED" was echoed): "member 3 (a name of 26 bytes)".
    Only the format's own fixed names (`header.json`, `hashes.json`, `signature.ed25519`, `protocol.json`) are named
    as they are; member names appear only after the signature verifies. Every `PackageRefused`
    sentence is printable ASCII (`printable`: each other character as its `\xNN`, `\uXXXX` escape), so a field
    shown after the signature (a study id a trusted key signed) cannot drive a terminal; the command's success lines
    are escaped the same way.
  - **Every failure of `verify` is a `PackageRefused` (review of 02b55d8a, item 3).** A signed member of the wrong
    JSON type (an IR file of `[]`, `null`, `1`, `"x"`), not JSON, not UTF-8 or out of range (`1e400`) is refused by
    the verifier's own check before `study_manifest` reads it (`_carried`; `study_manifest` is unchanged for its
    other callers); anything else that goes wrong while a package is read is refused at `verify`'s boundary as step
    `internal`, naming the error's type, never its text. A seeded fuzz (truncations, a byte changed per member,
    members of the wrong type, unsigned and re-signed) holds that nothing else leaves.
- **The export, audited (review of f1d1fe3c, H4; review of ec90c1b4, items 1 to 4, 6, 7).** Packing is a command of
  the coordinating centre's operator, not a console act: no console route is added.
  - **Who runs it, as which account.** `write` **never runs as root**: run as root it refuses before it reads a file
    or touches the audit, with one sentence (English, Japanese or Chinese: `--lang`, else the shell's `LANG`) that
    gives the supported way. That way is 10D-28's for `criteria_compiler.export_part` ("in the criteria compiler's
    container"): from `deploy/`, `docker compose run --rm -v <key folder>:/run/tb-study-key:ro -v <output
    folder>:/data/study-out criteria-compiler python -m tools.study_package write /data/rulesets/<ID> --key
    /run/tb-study-key/cc_ed25519.key --out /data/study-out/<ID>-<version>.tbstudy` (`SUPPORTED_RUN`). The container
    runs as its service account, uid 10001 (`user: "10001:10001"` of the compose file's `*py` anchor; `tb` in the
    image); `tools/` is in the image (`/app/tools`, on `PYTHONPATH`). It reads the study from the **`rulesets-data`**
    volume at `/data/rulesets` (the criteria compiler's rule-set store). **What the compose file does not give, and
    the run line adds for that one run:** the signing key and a folder the operator can take the package from: the
    compose file mounts neither (the key is kept offline, D-1372 keygen), so the two `-v` mounts are part of the
    supported command. **What that means for the key:** the signing key must sit on the box readable by uid 10001,
    the uid of every Python service (`deploy/docker-compose.yml`, the `x-py` anchor), so while the key folder is
    mounted for that one-off run, the service account, and so any code running as it, can read the coordinating
    centre's private key. The key is mounted only for that `run --rm` and kept offline otherwise; a signing step
    outside the service account (a separate account or device that holds the key) is **left to 10D-4 or the
    owner**, not built here. Both host folders, and the key file, must belong to uid 10001 (`sudo chown 10001:10001`), the
    key file mode 600 and the output folder writable by nobody else, or `write` refuses. No other account is
    supported; a host shell as another account works only in file mode (below), which a box does not use.
  - **Where the audit goes.** Through the product's writer, as `export_part` does
    (`tb_common.audit_writer.open_audit`; no `AuditLog` is built here): in the criteria compiler's container
    `TB_AUDIT_WRITER=db`, so the event goes to the audit journal over the container's own `TB_DB_URL` (database role
    `tb_criteria_compiler`, whose families include `approve`, `audit_writer.ROLE_EVENTS`) and the drain writes it
    into the chain; the command writes nothing into the audit folder (mounted read-only there). Without the journal
    (a developer shell, the tests) it writes the chain in `--audit-dir` or `TB_AUDIT_DIR`, and refuses a folder that
    is a link, missing, writable by group or others, or owned by another account; so the files the writer makes are
    the running account's own and nothing is handed to anyone. **The ownership hand-back of ec90c1b4 (`_give_back`)
    is removed**, with every chown and chmod of this command (a test holds that none is called).
  - **The order** (`write()`): refuses root; refuses with no writer; refuses an existing `--out` without `--force`,
    and with `--force` one that is not a regular file; reads the folder (`read_folder`); **binds the approval**
    (`approved_files`, below); reads the key (below); builds and self-verifies; opens `--out`'s folder **once,
    `O_DIRECTORY | O_NOFOLLOW`**, and refuses it unless it is owned by the running account with no group or other
    write bit; writes the package in that descriptor under a hidden name (`.<name>.<pid>.<16 random hex>.part`, `O_CREAT | O_EXCL |
    O_NOFOLLOW`, mode 600, fsync); reads it back **from that descriptor** and takes its sha256 there; appends
    **`approve.study_package_exported`** (actor below; `ruleset`, `ruleset_version`, `output_sha` that sha256;
    `detail`: `package_id`, `key_id`, `created`, `protocol_version`, `criteria_sha256`, `approval_tag`,
    `approval_tag_sha` (the tag object), `approval_commit` (the commit it names), `approved_by` (the person its
    message names), `store` (the store's real path: no component of it is a link), `store_dev` and `store_ino` (its
    `st_dev`, `st_ino`), `store_uid` (its owner), `site_key` (whether the box's site key was compared with the public test key, above), and
    `sudo_user_claimed` when set; never a byte of the content); only then links the name **from the same
    descriptor** (`linkat` of `/proc/self/fd/<n>`, which never overwrites; with `--force` to a second hidden name
    renamed over `--out`), fsyncs the folder (if that fails, the name is taken: the sentence says the package is
    named and that its entry may not survive a crash, never that no package was left; review 4 of c1a78033, L1),
    and checks that the file now named `--out` is that descriptor's
    (`st_dev`, `st_ino`) and hashes it again from the descriptor before it says success. An event that cannot be
    written leaves no package (fail closed). **If the event is written and the name cannot be taken** (a file
    appeared at `--out`; the hidden file was replaced, so the written one has no name left to link), or the named
    file is not the written one (without `/proc` the hidden name is linked, and a swapped file is caught here), the
    name is removed and the sentence says that the event for that package id and sha256 was written, that no package
    was left, so that event names a package that does not exist, and to run the command again (exit 1).
  - **The approval is bound to the content (item 4; review of 02b55d8a, item 7).** `status: approved` alone was a
    word in the folder, and at 02b55d8a any git repository above the given path served as "the store" and any
    annotated tag as the approval (a `git init`, a commit and `git tag -a RA-JAK/v1.0.0 -m anything` packed with an
    `approve.` event). At b9937b0d "the configured store" was still `TB_RULESETS_DIR` from the **caller's**
    environment (review of b9937b0d, item 1: as another account a reviewer made a git folder of their own, tagged
    "RA-JAK v1.0.0 approved by alice" with tagger alice, pointed `TB_RULESETS_DIR` at it, and `write` packed it with
    an event that did not say which store), and a symlinked store and a tag object named otherwise than its ref were
    accepted. Now **the store is pinned**: `write` packs only from `RULESETS_STORE`, `/data/rulesets`, the declared
    default of `TB_RULESETS_DIR` (`tb_common.config.DECLARED`), which is where the compose files mount the
    `rulesets-data` volume in the criteria compiler's container and what they set `TB_RULESETS_DIR` to. The command
    has no option that names a store; an environment whose `TB_RULESETS_DIR` names any other folder is refused with
    one sentence that says so, not followed. Only the tests give the library function `write` (and
    `approved_files`) another store, through its `store` parameter. The store path is reached from `/` one component
    at a time, each opened `O_DIRECTORY | O_NOFOLLOW` from its parent's descriptor, so a store that is or passes
    through a symbolic link is refused; no folder above it may be changed by another account (owned by this account
    or root, no group or other write bit, but root's sticky folders such as `/tmp`), and the store, its `.git`,
    `.git/refs` and `.git/objects` must be folders owned by this account or root that nobody else may write; the
    repository is then read through that descriptor (`/proc/self/fd/<n>`), not by its path again (review 4 of
    c1a78033, L4); the study folder's parent must be that folder (the same `st_dev` and `st_ino`). The tag must be **the approval exactly as the criteria compiler writes
    it** (`criteria_compiler.service`: `repo.tag(tag, branch, "<ID> v<version> approved by <who>", <who>)`): an
    annotated tag naming a commit, **the tag object's own name equal to its ref's** (`<ID>/v<version>`), its message
    exactly that sentence (one line, printable),
    its tagger `<who> <<who>>`, and the manifest at the tag `status: approved`, that version and
    `review.approved_by` that same person; with `export_part`'s checks (not seeded, not arrived in an update). The
    event and the success line record the store's real path, its `st_dev`, `st_ino` and owner uid, next to the tag
    object's sha, the commit's sha and that person. **What "approved on this box" rests on, and no more:** that tag
    is in the box's fixed store, `/data/rulesets`, the `rulesets-data` volume, owned by the criteria compiler's
    service account (uid 10001, `tb` in the image; the success line prints the owner uid it found). A tag there can
    be written by that account (so by any code running as it, the compiler's approval or not) and by root (a store
    another account may write is refused); neither needs the person's act on the console. And whoever holds the
    signing key can call the library's `build` with no store, no tag and no audit. So a package is **as strong as
    those accounts and that key**, no stronger; the success line says so in those words. `approved_files` reads the tag's blobs once and refuses: no store behind the folder (a plain folder
    is not packed at all), a folder not named as its manifest's `id`, a manifest that is not `status: approved`, no
    tag for the manifest's version, a tag that names nobody (`SEEDED_TAG`: a shipped example), an approval that
    arrived in an update (`(offline update`), a tagged manifest that is not that approved version, and a folder whose
    files (the manifest and every carriable file) differ in any byte, or by a file added or removed, from the tag's
    (a file edited after approval). The package is built from the tag's bytes. **The whole `<ID>/` tree of the tag
    is checked** (review 4 of c1a78033, M1: the tag's tree was filtered to the carriable files, so a file the
    criteria hash covers or the engine reads that a package cannot carry, a value set named with a space, an ELM in
    XML, the template, present in the tag and deleted from the folder, was silently dropped, and the package was
    signed and audited as the approved version with another criteria hash): such a file in the tag refuses the
    export, the approval's criteria hash is that of the whole tag, and `write` refuses a package whose header says
    another, before the event. The event stays in the `approve.`
    family: it now records the approval tag it packed.
  - **Who (item 6).** The actor is `host:<account>` from the account database by the real uid
    (`pwd.getpwuid(os.getuid())`; `host:uid:<n>` when the uid has no name), not `LOGNAME` or `USER`, which the
    caller sets; in the supported run that is `host:tb`, the service account, so the event says the export came
    from the criteria compiler's container, not which person ran it. `SUDO_USER`, when set, is recorded as
    `sudo_user_claimed`: a claim, since whoever starts the process can set it.
  - **The key (item 7).** Opened once, `O_NOFOLLOW`, checked on the descriptor (a regular file owned by the running
    account, no group or other bit, at most 64 KiB) and read from it. With `--trust-file`, a key whose public half is
    trusted there for `update` is refused. Without one, **the writer cannot tell an update key** from a coordinating
    centre's: the separation is the verifier's (H5) and 10D-4's register's.
  - **What H4 enforces, and what it does not.** Enforced: no package without its durable audit event naming the
    account, when, which study, version and approval tag, which package (by the sha256 of the linked file) and key;
    only a version holding this box's approval tag as the compiler writes it, in the box's fixed store (`/data/rulesets`), as
    approved (as strong as the accounts that can write a tag there and the signing key, above); never as root; the package file is mode 600; a
    stale hidden part file a SIGKILL left between the event and the link (`.<name>.<pid>.<16 random hex>.part`, and
    `.final` with
    `--force`) is removed by the next run in that destination, and named on stderr: only names of this pattern, only
    regular files (`lstat`, then opened `O_NOFOLLOW` and checked to be that file) the running account owns, and only
    when that run can take `flock(LOCK_EX | LOCK_NB)` on it. Its mode and whether it is complete are not checked. Each
    writer holds `flock(LOCK_EX)` on its own part file from its creation until it is closed after the link, and it
    sweeps and creates its part file holding the destination folder's own `flock`, so no sweep falls between another
    writer's create and lock. The pid in the name decides nothing: at b9937b0d the sweep took a writer for gone when
    `kill(pid, 0)` found no such pid in its own PID namespace, so two `docker compose run` writers into one folder
    could remove each other's live part file and the victim failed after its event (review of b9937b0d, item 3).
    The 16 random hex digits keep two runs whose pids are equal (often 1, in two containers) from sharing a name, and
    a run removes its own part name before it closes its descriptor (so while it holds its lock) and only when the
    name is still its own file (review 4 of c1a78033, L2). **The file-mode audit** (`--audit-dir`, a developer shell or the
    tests) checks its folder with `lstat` and the writer then opens it by path, its parents unchecked: since every
    write branch refuses euid 0, it works with the running account's own power only. Not enforced,
    because a command run in the container cannot: a console role or a study-access check, and the person: whoever
    can run `docker compose` on the box (root or the docker group) and holds the key can export. **For the owner:**
    whether packing should also need a console role is a new role power this card does not invent (10D-4's or a
    later card's).
- **Trusted keys (review of f1d1fe3c, H5).** `verify` takes `TrustedKey` entries, not bare keys: an Ed25519 public
  key (PEM), the `studies` it may sign for (at least one), and its `purpose` (`study-package` or `update`). A bare key
  or an entry naming no study is refused (default deny), and so is a key given twice (one key, one entry). Step 2
  refuses a key whose entry is marked `update` (the vendor's update key, whose `sign-file` signs raw bytes with no
  prefix, is kept apart from a coordinating centre's) and, after the signature verifies, a package whose `study_id`
  the entry does not name. `build` self-verifies with its key trusted for that one study. The command reads a trust
  file (`load_trust`): RFC 8259 JSON, exactly `{"format": "tb-study-trust/1", "keys": [{"key_id", "public_key",
  "purpose", "studies"}]}`: a field it does not list, a key twice in an object, `NaN`, are refused;
  `public_key` exactly one Ed25519 public key's PEM, nothing before or after it (the PEM reader alone would take text
  around it); `key_id` its id (checked); `studies` distinct study ids, at least one (an empty list refuses the file),
  matched exactly (no case folding, no prefix); at most 64 entries. The command reads it with `read_trust_file`:
  opened `O_NOFOLLOW` (a link is refused), a regular file, no group or other write bit, owned by the account
  running it or root, at most 1 MiB. `verify` without `--trust-file` is a usage error (exit 2), and the library's
  `verify` with no trusted key refuses every package. A `TrustedKey`'s `studies` must be a tuple or frozenset of
  exact study ids (review of 02b55d8a, item 6: a text matched by substring, "JAK" in "RA-JAK"); a key of another
  algorithm (cryptography's `UnsupportedAlgorithm`) and a trust file nested deeper than 8 (checked by the same
  linear scan before it is parsed) are refused with one sentence. The name and field patterns match whole. This is the verifier's side only, with the minimal scope field: **10D-4's register of
  coordinating-centre keys must carry, per key, the studies (or the coordinating centre's scope) it signs for and
  its purpose, and refuse a key equal to the vendor's update key** (`deploy/updates/trust.json`,
  `deploy/keys/vendor_ed25519.pub`), which this card does not read.
- **What leaves the box** in a package: `protocol.json`, `hashes.json`, `header.json` (with the writer's date and
  the key id), `signature.ed25519`, and the protocol files under `files/` exactly as `PACKAGE_FILES` names them.
  Nothing else. Within those, this travels **as typed** by whoever wrote the study, checked for shape only:
  - **the manifest's protocol fields** (`study_manifest.PROTOCOL_FIELDS`), every one that is set: `id`, `kind`,
    `title`, `trial_alias`, `sponsor`, `version`, `source_documents`, `protocol_version`, `protocol_date`,
    `language`, `index_date_rule`, `library`, `criteria`, `thresholds`, `variants`, `twpas`, `docx_template` (the
    name; the file is not carried), `cohort`, `population`, `nct_id`, `terminology_release`, `prompt_pins`,
    `derived_pins`, `source_last_update`, and `models.judge_prompt` (`PROTOCOL_SUBFIELDS`); the protocol files'
    hashes and the criteria hash;
  - **each criterion** (`ir/*.json`, without the review record but `{"status": "rejected"}`): every field of the
    model the writer and the verifier check it against, strictly, `tb_contracts.CriterionIR` (schema 1.3.0; a
    test holds this list equal to that model's fields and marks each free-text field, review 4 of c1a78033, M2,
    which found here another schema's fields): `id`, `ruleset` (free text, the study's id as written), `text`
    (free text: the criterion as the protocol states it), `label` (free text), `source_ref` (free text: section and
    page of the source document; all 91 shipped criteria hold one), `kind`, `class`, `time_sensitive`, `logic` (the
    atoms and boolean expressions: domains, value set ids, quantifiers, values, windows, durations, ages, sex,
    derived measures), `fallback` (free text), `note_question` (free text: the question put to the model),
    `note_question_source` (free text: the question as the model extracted it, before the compiler rewrote it),
    `human_question` (free text: the question asked at screening; six shipped criteria hold one), `action` (free
    text), `suggested_order` (free text), `flags` (compiler words only), `review` (only `{"status": "rejected"}`;
    the site's record, who and when and the comment, is dropped), and `provenance` (`calls` only): **the compiling
    box's model call ids** (D-989). 10D-28's rule-set export leaves
    `provenance` out; here the carried form cannot omit it without changing the criteria hash, which D-1366 takes
    over the IR file with its provenance, so it is left in and named for the owner (no shipped study holds one);
  - **each value set**: `id`, `url`, `version`, `name`, `title`, `status`, each include's `system` and each
    concept's `code` and `display`, and the code families (`<system>|<prefix>`); since review item 9 a system only of
    `VALUESET_SYSTEMS` (the test patients' 21 and WHO ICD-10, which the shipped families name), a code of the
    department system only as one of `PLACEHOLDER_DEPARTMENT_DISPLAYS` with its display (`META`, `NEUR`, `PSY`,
    `RHEU`, measured from the two shipped value sets), and no code family of that system;
  - `labels.yaml` as text; `cql/*.cql` and `sql/*.sql` as text, comments included; `cql/elm/*.json` as written
    below its `library` (its annotations hold the CQL source and comments); `tests/expected.json` within its
    allow-list (H2: synthetic chart numbers, the protocol's criterion ids, verdicts, numbers, a date and two labels
    from closed sets);
  - `tests/patients.ndjson`: the leaves listed under "What the guard cannot prove" above, quantities included.
- **Stopped on (rule 11), for the owner, not changed here:**
  - `tests/patients.ndjson` is a protocol file (D-1366 rule 4), and in five shipped studies (GOUT-COH, GZQO,
    ONC-OSI, RA-BIO, RA-COH) its synthetic `Appointment` resources name practitioners `Practitioner/P12345` …
    `P89012` and the department code `RHEU`, the same synthetic codes RA-JAK's site `scopes.screen.practitioners`
    lists. They are synthetic, and the criteria hash covers the file as it is, so the package carries them.
  - Two value sets are department codes used as a criterion (`https://trialbox.local/fhir/CodeSystem/department`):
    GZQO `VS_RHEUMATOLOGY_OR_METABOLISM_CLINIC_VISIT` (`META`, `RHEU`; also in GZQO's IR, CQL, ELM and SQL) and
    NEUR-COH `VS_MEMORY_CLINIC_VISIT` (also in its SQL). A clinic visit is a protocol's criterion, but the code is a
    hospital's local code.
  - The file `docx_template` names is hashed as its bytes (D-1366); a .docx carries its author's name in its
    document properties. A v1 package does not carry it: `build` refuses a folder that holds the named file (none
    of the shipped folders does).
- **Left to later cards:** where coordinating-centre keys live, who registers them, import, the audit of an import
  and the media path (10D-4); the header's registry id, previous package, coordinating centre and central approval
  of review 14's M14-2 (an IRB reference is the site's under D-1366; adding header fields is a format v2, or 10D-4's
  decision with 10D-26's pins); the screen-only pins (10D-26); allowed adaptations (10D-5); a draft package at several
  sites (10D-12, the owner's decision 51: the command packs only an approved version, at its approval tag in the box's
  store, and the header says nothing of a status; the library's `build` packs whatever it is given, a draft
  included, with no store, tag or audit).
  10D-28 carries a rule set in a vendor-signed update bundle for the dry run only; it is not this format.
- **For 10D-4, which v1 does not stop:**
  - the register must give each key its studies and purpose (H5 above); the verifier now runs the writer's guards
    over the carried files (review item 6), so import gets them by calling `verify`;
  - an older valid package, or the same content signed again with another `created`, verifies: import needs "not
    older than the one installed" per study and coordinating-centre key;
  - the register of coordinating-centre keys must refuse a key equal to the vendor's update key: the update bundle's
    `sign-file` signs raw bytes with no prefix, so one key must not serve both channels;
  - two member paths that differ only by case are distinct here and collide on a case-insensitive disk: extraction
    must refuse them;
  - the importer must pass each key's studies as a tuple or frozenset of exact study ids (a text is refused);
  - references inside the IR and the CQL to value sets and libraries are **not checked** against the files carried
    (a criterion may name a value set the package lacks): the importer, or the compile at the site, must;
  - every failure of `verify` is a `PackageRefused` (step `internal` for the unforeseen): the importer handles that
    one type; `show` is never a check (exit 3);
  - the signing key is readable by the service account while it is mounted (above): a signing step outside that
    account is 10D-4's or the owner's.
- **The review of f1d1fe3c, items 6 to 12** (re-read at 3d0cf7d4, after the High fixes; each built one seen failing
  there first):
  - 6, the verifier skipped the writer's patient-data checks: true; **fixed** (`content_refusal`, the last check of
    step 5; `test_item6_…`: a `Patient.name`, a patient not of the synthetic site, an `expected.json` key of another
    form, an IR field, a hospital's code, each in a package a trusted key signed).
  - 7, free text in protocol fields (`population`), `labels.yaml` comments and ELM annotations: true; **not built**.
    The ELM node allow-list is **left to 10D-28** (`ruleset_part`) and the importer, **10D-4**; whether the protocol
    part's free-text fields and comments may travel as typed is **for the owner** (the shipped `labels.yaml` files
    hold comments, and the protocol part is D-1366's: refusing or stripping them changes what the owner approved).
  - 8, the umask: no longer applies: the package is created mode 600 (`O_EXCL`, then `fchmod`) and renamed; a test
    writes it under umask 0.
  - 9, site-local codes in value sets: true; **fixed** (`_valueset_refusal`, writer and verifier;
    `test_item9_…`).
  - 10, `provenance.calls` exports the compiling box's call ids: true; **for the owner** (already named above):
    stripping it changes D-1366's criteria hash of a compiled study, refusing it makes every compiled study
    unpackable; no shipped study holds one.
  - 11, no central approval reference in the header: true (two approvals of one content give one package; a draft is
    no longer packed, H4); **left to 10D-4** with 10D-26's pins (a new header field is a format change and more that
    travels, which this card does not add).
  - 12, the site-field test passed for a stale package id: true (a mutant verifier that lets `routing` through still
    failed it); **fixed**: the package id is made again and step 5 names a site field first
    (`test_item12_…`).
  - Re-checked from H4 and H5: `test_a_…` (the part file by descriptor, the link failure; the give-back by
    descriptor it also held is removed, review of ec90c1b4 item 2) and `test_b_…` (the trust file).
- **Review of ec90c1b4 (writer and act of export; NOT READY), item by item:**
  - 1, `write` ran as root and appended to the audit by path in a folder the service account owns (a planted
    `.HEAD.json.tmp` link made root overwrite a root-only file): **fixed** by never running as root and auditing
    through `open_audit` in the criteria compiler's container (above; `test_item1_…`). `tb_common.audit` is not
    changed (not this card's).
  - 2, `_give_back` handed root-owned files in the audit folder to its owner: **fixed**, removed with every
    chown/chmod (`test_item2_…`).
  - 3, the destination folder unchecked and the name linked by name: **fixed** (`O_NOFOLLOW`, owner and mode,
    linked from the hashed descriptor, checked after; `test_item3_…`).
  - 4, `status: approved` unbound: **fixed**, packed from the approval tag (`test_item4_…`, with the 8 shipped
    studies approved in a store, packed by `write` and verified).
  - 5, the synthetic guard bound only `Patient/` references: **fixed** (patient element per type, id shape, every
    reference resolves; `test_item5_…`).
  - 6, the actor from `getpass`: **fixed** (`test_item6_…`).
  - 7, the key read by path, `per_criterion` precision, a manifest refusal that echoed the value: **fixed**
    (`test_item7_…`: a refusal by the manifest's model now names the field's path and the error type, never the
    value).
- **Review of 02b55d8a (two reviews, NOT READY), item by item** (each a test at the real call, seen failing on
  02b55d8a first):
  - 1 (blocker), the regex depth scan was quadratic before the signature: **fixed**, linear scan and the 64 KiB /
    1 MiB caps (`test_r1_…`: the reviewer's header at 80 KB and at 4 MiB scans in well under 2 s; over the cap,
    refused with nothing scanned or parsed).
  - 2, refusals before the signature echoed the sender's text raw, `show` printed it raw and exited 0: **fixed**
    (`test_r2_…`).
  - 3, a signed member of the wrong type raised TypeError, AttributeError or a bare ValueError: **fixed**
    (`test_r3_…`, with the seeded fuzz); the command's last resort is one sentence, exit 2.
  - 4, an unknown key algorithm and a deep trust file raised: **fixed** (`test_r4_…`).
  - 5, `read_file` read a FIFO or a device by path after `stat`: **fixed** (`test_r5_…`).
  - 6, `studies` as a text matched by substring; patterns with `$`: **fixed** (`test_r6_…`).
  - 7 (blocker), any store and any tag: **fixed** as far as a command in the container can (above; `test_r7_…`).
  - 8, the key readable by the service account, unstated; `keygen` followed a link for the `.pub`: **stated**
    (above) and **fixed** (`test_r8_…`).
  - 9, cross-patient references, a reference of the wrong type, duplicate records; a stale part file after a
    SIGKILL; the file-mode audit's power: **fixed**, **fixed**, **stated** (`test_r9_…`).
- **Review of b9937b0d (delta review, NOT READY), item by item** (each a test at the real call, seen failing on
  b9937b0d first):
  - 1 (blocker), the store from the caller's environment, a symlinked store, a tag object named otherwise than its
    ref, an event that did not name the store: **fixed**, the store pinned to `/data/rulesets` and recorded
    (above; `test_s1_…`).
  - 2, the command's exit point printed messages raw: **fixed** (`test_s2_…`).
  - 3, the stale part sweep by `kill(pid, 0)` across PID namespaces: **fixed**, by `flock` (above; `test_s3_…`, two
    processes).
  - 4, the trust file read by its own code, an internal error in `verify` exiting 1, member names before the
    signature: **fixed** (`test_s4_…`; the internal error through the real `verify`, not a patched `verify_file`).
- **Review 4 of c1a78033 (0 High, 2 Medium, 8 Low), item by item** (each a test at the real call, seen failing on
  the tree before the fix first):
  - M1, a hashed file of the tag that a package cannot carry was silently dropped: **fixed** (`test_t1_…`).
  - M2, the criterion list named another schema: **fixed**, held equal to `CriterionIR` (`test_t2_…`). Added to the
    list: `id`, `ruleset`, `text` (a string), `source_ref` (top level), `kind`, `class`, `time_sensitive`,
    `note_question_source`, `human_question`, `review` (`status: rejected` only), `provenance`; taken out (not
    fields of the checked model): `text.source`, `text.lang`, `text.source_ref`, `human`, `lexicon_keys`,
    `library_ref`, `computability.basis`, `flip_rule.detail`.
  - L1, a failed folder sync after the link said no package was left: **fixed** (`test_t3_…`).
  - L2, part names shared across containers: **fixed** (`test_t4_…`).
  - L3, twice the size before the signature: **fixed**, once (`test_t5_…`).
  - L4, the store reopened by path, its modes unchecked: **fixed** (`test_t6_…`).
  - L5, the public test site key: **fixed where the run can read the key**, and stated where it cannot (above;
    `test_t7_…`); whether the supported run should read it is the owner's.
  - L6, the key folder's owner and mode: **fixed** (`test_t8_…`).
  - L7, the sentence on drafts said the command packs any protocol whatever its status: **corrected** (`test_t9_…`).
  - L8, a bad trust file exited 1: **fixed**, exit 4 (`test_t10_…`).
- **Held by:** `tests/unit/test_study_package.py` (the review of f1d1fe3c: `test_h1_…` to `test_h5_…`, `test_item6_…`,
  `test_item9_…`, `test_item12_…`, `test_a_…`, `test_b_…`; the review of ec90c1b4: `test_item1_…` to `test_item7_…`;
  the review of 02b55d8a: `test_r1_…` to `test_r9_…`; the review of b9937b0d: `test_s1_…` to `test_s4_…`; review 4 of c1a78033: `test_t1_…` to `test_t10_…`;
  each the reviewer's probe at the real call, each seen failing first).
