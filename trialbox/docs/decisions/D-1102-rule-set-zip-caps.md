# D-1102 Rule-set zip caps: members, sizes, ratio and names checked before any member is read

- **Task:** lane H, plan 10 row 10G-6 (review 16-23 and 9g-12; ASVS 12.1.2 "compressed files: uncompressed size and
  count checked"). Track G is lane H's by the integrator's word of 2026-11-18.
- **PR:** this branch (`claude/lane-h-10g-6-rule-set-zip-caps`)
- **Date:** 2026-11-18
- **Status:** reserved
- **Builds on:** D-77 (signed offline updates; the rule-set install), D-1101 (a stated limit, tested at its edge)

## Context

A rule-set package is a zip. The offline install (`criteria_compiler.import_ruleset.read_zip`) read every member
with no cap on their number or size (review 16 §3, 12.1.2 "does not meet"), and the trial simulation's draft read
(`orchestrator.scenarios.cohort.load_draft`) wrote every member to a temporary folder with none either. A zip of a
few kB can declare gigabytes.

## Decision

1. One checker, `libs/tb_common/zipcap.py` (`check_ruleset_zip`), is called by every place a rule-set zip is opened,
   before any member is read or written. It reads only the central directory.
2. The caps (stated limits in the sense of D-1101; the constants are in that module):
   - at most **2,000 members** (`RULESET_ZIP_MAX_MEMBERS`; directories count);
   - each member at most **100,000,000 bytes** uncompressed (`RULESET_ZIP_MAX_MEMBER_BYTES`);
   - all members together at most **200,000,000 bytes** uncompressed (`RULESET_ZIP_MAX_TOTAL_BYTES`);
   - a member may expand at most **200 times** its compressed size (`RULESET_ZIP_MAX_RATIO`); a member of
     1,000,000 bytes or less is not judged by ratio.
   The member and total figures are review 16-23's; the per-member and ratio caps are new and leave room for the
   largest value-set files a rule set carries today (well under 1 MB each).
3. Names: an absolute path (`/x`, `\x`, `C:x`), a `..` part, a backslash or NUL, a symbolic link or a name given
   twice is refused.
4. A refusal carries its reason as a code (`zip.members`, `zip.member_size`, `zip.total_size`, `zip.ratio`,
   `zip.name`, `zip.symlink`, `zip.duplicate`), and nothing is written. The install raises its `ImportRefused`, whose
   text names the cap's value, before the repository is touched; the draft read fails its job with a fixed sentence
   ("draft package refused by the rule-set zip caps (D-1102)": the orchestrator's answers repeat no error's text,
   `tests/unit/test_error_answers.py`) before its folder is made.
5. Not settings: a site has no reason to raise them; a vendor rule set larger than this is a change to this decision.

## Consequences

- `tools/limits_edge.py` lists the four caps as stated rows (L36 to L39), claimed constants, driven on the function.
- `tests/unit/test_ruleset_zip_caps.py` tests each cap at the limit, one over and far over, with zips built in the
  test (sizes declared in the central directory, not stored), and a real deflated zip-bomb fixture.
