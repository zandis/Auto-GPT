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
    PEM: the formats of `tools/sign_bundle.py keygen` and `tb_common.crypto`), `write STUDY --key K --out F
    [--created YYYY-MM-DD] [--force]` (a key file others may read, and an encrypted key, are refused; an existing
    `F` is replaced only with `--force`; and see "The export, audited" below), `verify F --trust-file T` (see "Trusted
    keys" below), `show F`
    (the header; the signature is not checked, and it says so). It prints key ids, never key material. No new
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
  - **Memory:** `verify` holds the package's bytes and a copy of its members, about twice the input, so at most
    about 400 MB at the caps; the tool reads a file only after its size is checked.
  - **Verify, in this order, one sentence each** (`PackageRefused`, its `step`; nothing is written anywhere, a test
    blocks every file open during it): (1) `tar`, its sub-checks in the order the code makes them: the whole package
    at most 200,000,000 bytes (from the file's size before it is read); whole 512-byte blocks, at least two; then for
    each block: the two end blocks and nothing after them, the checksum and size fields plain octal, the checksum,
    the `ustar` magic, a regular file, an empty prefix field, an ASCII name, the name rules, no duplicate, at most
    2,000 members, the member's size cap (100,000,000 bytes; 4 MiB for `hashes.json`, `header.json`, `protocol.json`
    and `signature.ed25519`), all members together at most 200,000,000 bytes, the member's bytes present, the
    canonical header block, zero padding and name order; then the four fixed members present, only allowed names, a
    64-byte signature, the header's nesting, JSON, RFC 8785 form and v1 fields, the hash list's nesting, JSON, RFC 8785
    form and entries; (2) `signature`: the header's `key_id` is one of the trusted keys, that key's entry is for
    study packages (not `update`), the signature verifies with it, and the header's `study_id` is one the entry names
    (H5); (3) `hashes`: each member's sha256 is the listed one; (4) `members`: no member outside the list,
    none missing; (5) `protocol`: `protocol.json` is a protocol part that holds its own criteria hash
    (`study_manifest.protocol_refusal`), the header's `study_id`, `version`, `protocol_version` and
    `criteria_sha256` are its, each carried file is in its canonical form, the files' hashes are exactly the protocol
    part's `files`, the criteria hash computed again from them is the header's, and the header's `package_id` is the
    one its `study_id`, `version` and `hashes.json` give, and then (H3, the last check) the criteria the protocol part's
    manifest names are exactly the carried `ir/` files (`criteria_refusal`: each id once, each with its
    `ir/<id>.json` whose `id` is that id, no `ir/*.json` it does not name, and, when it names a CQL `library`, its
    `cql/<library>.cql` and `cql/elm/<library>.json` carried). The writer makes the same check before it signs.
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
    the file does not hold. All five shipped files pass unchanged (each `Patient` is site-a's, chart numbers
    10000001 to 10000600), so no fixture and no criteria hash changed. This was chosen over a new marker stamped by
    the generator because a marker in the test patients would change them and so every shipped criteria hash
    (D-1366) and the goldens that pin them; the pseudonym scheme is already in every shipped file.
  - **What H1 proves, and what it does not.** It proves where the records were pseudonymised: by the test stack,
    from a chart number in the synthetic generators' numbering, under a key published in the repository. A box's own
    patients are pseudonymised under that box's secret key (D-09), so an export of a box's real ingested records is
    refused (the chance that a real pseudonym equals one of the 22,500 is about 22,500 in 2^128). It does **not**
    prove that the content is synthetic: the key is public, so anyone can compute a synthetic pseudonym and write a
    real person's dates, codes or report under it by hand; and a real hospital that numbered its chart numbers in
    the same range and ingested them under the public test key would pass. The leaves below still travel **as
    typed**, unchecked against any real record (each within the type and the 200-character cap above): every `id` and `reference` id (a FHIR id, so `Patient/` and
    the like may carry any 64 letters, digits, `.` and `-`), `Patient.birthDate`, `Patient.gender`,
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
    `patients` (the integer number of patients) and `per_criterion` (criterion ids to a number from 0 to 100). So no
    free text and no identifier but a synthetic chart number travels in it. For the three studies with no test
    patients (AD-MAB, NEUR-COH, RA-JAK) the keys are only held to the synthetic numbering, not tied to records.
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
  - Only the writer checks the test patients (H1), `tests/expected.json` (H2) and the models; a package from
    elsewhere is not refused for them (the verifier's checks and their order are as above; the criteria set, H3, is
    checked by both). 10D-4's import should run the same guards.
- **The export, audited (review of f1d1fe3c, H4).** Packing is a host command of the coordinating centre's
  operator, not a console act: no console route is added. `tools.study_package write` (`write()`), in this order:
  refuses with no audit folder (`--audit-dir`, else `TB_AUDIT_DIR`) or one that is not a folder; refuses an existing
  `--out` without `--force`; reads the folder (`read_folder`) and refuses a study whose `manifest.yaml` does not say
  `status: approved` (a draft is not packed: decision 51, feasibility on a draft at several sites, is open and is
  10D-12's); builds and self-verifies the package; writes it beside `--out` under a hidden name
  (`.<name>.<pid>.part`, `O_EXCL`, `O_NOFOLLOW`, mode 600, fsync); appends **`approve.study_package_exported`** to
  the box's audit chain through `tb_common.audit.AuditLog` (actor `host:<user>`, as 10D-28's `export_part`;
  `ruleset`, `ruleset_version`, `output_sha` the package's sha256; `detail`: `package_id`, `key_id`, `created`,
  `protocol_version`, `criteria_sha256`; never a byte of the content); gives what it wrote in the audit folder to
  the folder's owner (`backup._own_writes`, D-724: only as root; injected in the tests, which run as any user); and
  only then gives the package its name (`os.link`, which never overwrites, or `os.replace` with `--force`). An event
  that cannot be written removes the part file and leaves no package (fail closed). The event is in the approval
  family (`audit_writer.ROLE_EVENTS`: the criteria compiler's), written to the chain file directly as the host's
  backup and restore events are, so it carries no journal role.
  - **What H4 enforces, and what it does not.** Enforced: no package without its durable audit event naming who,
    when, which study and version, which package and key; only an approved protocol; the package file is mode 600 (so
    the umask cannot make it readable to other local accounts). Not enforced, because a host command cannot: a
    console role or a study-access check. Whoever can read the study folder and the coordinating-centre key and
    write the box's audit folder can export; on a box that is root or the audit writer's account. **For the owner:**
    whether packing should also need a console role (for example the PI's or the steward's approval of the export)
    is a new role power this card does not invent; it would be a console act, 10D-4's or a later card's.
- **Trusted keys (review of f1d1fe3c, H5).** `verify` takes `TrustedKey` entries, not bare keys: an Ed25519 public
  key (PEM), the `studies` it may sign for (at least one), and its `purpose` (`study-package` or `update`). A bare key
  or an entry naming no study is refused (default deny), and so is a key given twice (one key, one entry). Step 2
  refuses a key whose entry is marked `update` (the vendor's update key, whose `sign-file` signs raw bytes with no
  prefix, is kept apart from a coordinating centre's) and, after the signature verifies, a package whose `study_id`
  the entry does not name. `build` self-verifies with its key trusted for that one study. The command reads a trust
  file (`load_trust`): RFC 8259 JSON, exactly `{"format": "tb-study-trust/1", "keys": [{"key_id", "public_key",
  "purpose", "studies"}]}`, `public_key` the PEM text, `key_id` its id (checked), `studies` distinct study ids, at
  most 64 entries. This is the verifier's side only, with the minimal scope field: **10D-4's register of
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
  - **each criterion** (`ir/*.json`, without the review record but `{"status": "rejected"}`): `text.source`,
    `text.lang`, `text.source_ref`, `label`, `logic`, the atoms and macros, `fallback`, `action`,
    `suggested_order`, `flags` (compiler words only), `note_question` (its key and its texts), `human` (its
    checklist questions and hints), `lexicon_keys`, `library_ref`, `computability.basis`, `flip_rule.detail`, and
    `provenance.calls`: **the compiling box's model call ids** (D-989). 10D-28's rule-set export leaves
    `provenance` out; here the carried form cannot omit it without changing the criteria hash, which D-1366 takes
    over the IR file with its provenance, so it is left in and named for the owner (no shipped study holds one);
  - **each value set**: `id`, `url`, `version`, `name`, `title`, `status`, each include's `system` and each
    concept's `code` and `display`, and the code families (`<system>|<prefix>`);
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
  sites (10D-12, the owner's decision 51: v1 packs whatever protocol the folder holds and says nothing of its status).
  10D-28 carries a rule set in a vendor-signed update bundle for the dry run only; it is not this format.
- **For 10D-4, which v1 does not stop:**
  - the register must give each key its studies and purpose (H5 above) and run the writer's guards on import: the
    verifier checks the criteria set (H3) but, as before, not the test patients (H1) or `tests/expected.json` (H2);
  - an older valid package, or the same content signed again with another `created`, verifies: import needs "not
    older than the one installed" per study and coordinating-centre key;
  - the register of coordinating-centre keys must refuse a key equal to the vendor's update key: the update bundle's
    `sign-file` signs raw bytes with no prefix, so one key must not serve both channels;
  - two member paths that differ only by case are distinct here and collide on a case-insensitive disk: extraction
    must refuse them.
- **Held by:** `tests/unit/test_study_package.py` (the review of f1d1fe3c: `test_h1_…` to `test_h5_…`, each the
  reviewer's probe at the real call, each seen failing on f1d1fe3c first).
