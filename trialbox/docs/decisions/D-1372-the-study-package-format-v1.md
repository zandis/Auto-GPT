# D-1372 The study package, format v1: canonical tar, header, hash list, Ed25519 signature (10D-3)

- **Task:** lane A2, plan 10 row 10D-3 (review 14 M14-2; the owner's decision 47: federation by a signed package;
  decision 50, ruled: transport is a signed file on media or internal mail). · **Date:** 2026-11-19
- **Builds on:** D-1366 (the protocol part, its canonical form and the criteria hash), D-77 and D-210 (the update
  bundle's Ed25519 signature and its `key_id`), D-1102 (the rule-set zip caps), D-1226 (signed alliance tables),
  D-555 (a refusal is a returned sentence)
- **What this card does not do, plainly:** nothing on the live path reads a package. No import, console page, route,
  role or audit row changes; `tb_common.study_package` is called only by the tests and by the operator's tool
  `python -m tools.study_package`, which no console action calls.
- **Decision:**
  - A study travels as **one file** that `tb_common.study_package.build` writes from a study folder `rulesets/<ID>/`
    and a coordinating-centre Ed25519 private key, and `verify` checks against the trusted public keys its caller
    passes. The tool: `keygen --out DIR` (`cc_ed25519.key`, PKCS8 PEM, mode 600; `cc_ed25519.pub`, SubjectPublicKeyInfo
    PEM: the formats of `tools/sign_bundle.py keygen` and `tb_common.crypto`), `write STUDY --key K --out F
    [--created YYYY-MM-DD] [--force]` (a key file others may read, and an encrypted key, are refused; an existing
    `F` is replaced only with `--force`), `verify F --trust PUB [--trust PUB…]`, `show F`
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
    form and entries; (2) `signature`: the header's `key_id` is one of the trusted keys and the signature
    verifies with it; (3) `hashes`: each member's sha256 is the listed one; (4) `members`: no member outside the list,
    none missing; (5) `protocol`: `protocol.json` is a protocol part that holds its own criteria hash
    (`study_manifest.protocol_refusal`), the header's `study_id`, `version`, `protocol_version` and
    `criteria_sha256` are its, each carried file is in its canonical form, the files' hashes are exactly the protocol
    part's `files`, the criteria hash computed again from them is the header's, and the header's `package_id` is the
    one its `study_id`, `version` and `hashes.json` give.
  - **"A changed byte fails verification"** is held by flipping every byte of a package (one bit, then all eight),
    and by named classes: header, hash list, signature, protocol part, a protocol file, a tar header's name, mode,
    mtime, owner, checksum and unused bytes, the padding, the end blocks, bytes appended, the archive cut short.
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
  - an older valid package, or the same content signed again with another `created`, verifies: import needs "not
    older than the one installed" per study and coordinating-centre key;
  - the register of coordinating-centre keys must refuse a key equal to the vendor's update key: the update bundle's
    `sign-file` signs raw bytes with no prefix, so one key must not serve both channels;
  - two member paths that differ only by case are distinct here and collide on a case-insensitive disk: extraction
    must refuse them.
- **Held by:** `tests/unit/test_study_package.py`.
