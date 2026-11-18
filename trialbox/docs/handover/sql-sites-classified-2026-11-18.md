# The SQL sites built from strings, classified (10G-42 (c), lane H, 2026-11-18)

Plan 10 row 10G-42 ([plan 10](../plan/47-plan-10-2026-11-18.md), Track G, defect (g)) as the integrator narrowed it for
lane H on 2026-11-18: each place that builds SQL from strings is classed as (1) values bound as parameters, (2) an
identifier or fragment from a fixed set in code, or (3) reachable from input. Only the class 3 sites become findings
([findings.json](sql-sites-classified-2026-11-18/findings.json), card `H10G42`); their fixes go to lane J. This page
changes no product file, no lint setting and no ignore list.

## How the sites were found

Review 21 ([21](../reviews/2026-11-root/21-open-tool-security-testing.md), measurement M 3) counted the sites with
ruff's `S` rules run without the project's ignores (`ruff check --isolated --select S … libs services deploy`): 330
findings, of which **S608** (SQL built from strings) **164**. The project's `pyproject.toml` ignores S608 globally,
which is why the normal `make lint` shows none. The same command narrowed to S608, run from `trialbox/` on master
`312eca7c`:

    .venv/bin/ruff check --isolated --select S608 libs services deploy

finds **164** sites, the same number as review 21, with ruff 0.17.4 (the version `uv.lock` pins) and with ruff 0.16.9:
the two versions report the same 164 places. No tool was added: the count is this one command.
`tests/unit/test_sql_sites_page.py` runs it and checks that this page has one row per site, file by file (a moved
line does not fail the test; a new or removed site does, and must then be classed here), and that the class 3 rows
and `findings.json` name the same places.

The 163 "unreviewed low-confidence" bandit findings of the plan row (B608 at MEDIUM/LOW) are the same kind of finding
from the other tool; this page classes the ruff sites, not the bandit list one by one.

Notes on the count:

* `--isolated` drops `extend-exclude`, so `libs/tb_contracts/generated` is scanned too; it holds no site.
* Ruff reports three lines twice (one string, two hits): `services/omop/load.py:819`,
  `services/criteria_compiler/compile_sql/generator.py:642` and `services/orchestrator/scenarios/feas_compute.py:273`.
  Each hit is a row, so the table has 164 rows for 161 distinct lines.
* Two sites are not SQL: `deploy/windows/wsl2_policy.py:327` and `:336` are Windows Update messages whose words
  ("Update ... set") match the rule's pattern.

## The classes

* **1, bound.** Every value is a bound parameter (`?`, `%s`, `$n`); only fixed SQL text is joined (constant column
  lists, `" FOR UPDATE"`, a list of `?` marks).
* **2, fixed set.** An identifier or fragment comes from a set fixed in code: a module or class constant, a literal
  tuple or dict, an enum, or a regex or allow-list checked in code before use. The row names the set or the check.
* **3, reachable from input.** A request, a file (protocol, rule set, feed), configuration an operator edits, or
  database content reaches the SQL text. The row gives the path from where the value enters to the site, what stands
  between, and a severity with its reason.

No site was left "not determined".

Path **P1** (the criterion IR, used by the compiler rows): a protocol document attached to a job → `compile_draft`
(`services/orchestrator/scenarios/review.py:77`) or the ct.gov `_compiled` (`services/orchestrator/trials.py:53`) →
`POST /compile` (`services/criteria_compiler/app.py:137`) → `Compiler.compile` → the model's extraction → `postprocess`
→ `CriterionIR.model_validate` (`services/criteria_compiler/postprocess.py:562`) → `build_artifacts` →
`SqlGenerator.render`. A reviewer's `edited_ir` and the rule-set files read by `overlay._render` and `variant_sql`
reach the same point. Pydantic `Literal` types fix the domain, quantifier, derived score, sex, clinical status,
operator and kind; the free-text fields are the value set name, `value.codes`, `value.unit` and the criterion text.
The SQL the generator writes runs on the lake through `LakeStore.query`, which calls `check_select`
(`services/lake/sqlguard.py`, one read query only) on a read-only connection with external access off.

## Sums

By class:

| Class | Sites |
| --- | --- |
| 1, bound | 64 |
| 2, fixed set | 74 |
| 3, reachable from input | 24 (Medium 2, Low 22, High 0) |
| not SQL | 2 |
| **All** | **164** |

By lane's area (the lane that owns the file, from the lane table of plan 42 §5; `libs/tb_common/db.py` is put under
D as the shared database layer):

| Lane | Area here | 1 | 2 | 3 | not SQL | All |
| --- | --- | --- | --- | --- | --- | --- |
| A2 | compiler, matching, orchestrator, `notmatched` | 14 | 21 | 17 | 0 | 52 |
| B2 | lake, OMOP, vector store, patient profile, `derived_store`, `lakeprobe` | 16 | 41 | 6 | 0 | 63 |
| C2 | console, site set-up, data core, mail gateway, `flags` | 28 | 6 | 1 | 0 | 35 |
| D | `libs/tb_common/db.py` | 0 | 1 | 0 | 0 | 1 |
| E | adapter, EDC, `refdata` | 6 | 5 | 0 | 0 | 11 |
| W | `deploy/windows` | 0 | 0 | 0 | 2 | 2 |
| **All** | | **64** | **74** | **24** | **2** | **164** |

## The class 3 sites

No site lets the text of a request reach the SQL unchecked. Two sites are Medium, the rest Low:

* **Medium**, `services/orchestrator/scenarios/feas_compute.py:273` (two hits): the feasibility funnel places the
  stored SQL of a rule set (`safe_sql(rs)`) whole inside its query. That text comes from the rule-set repository: the
  compiler's output, or a zip installed offline by `services/criteria_compiler/import_ruleset.py`, whose manifest must
  say approved. Nothing checks the SQL text itself before it runs; only the lake's SELECT-only check and the read-only
  connection stand between.
* **Low**, the criteria compiler's SQL generator (`generator.py`, 14 hits) and the feasibility variants
  (`feas_compute.py:271`): text from the protocol or rule set (value set names, codes, units) is written as SQL
  literals through `lit()`, which doubles every single quote (a complete escape for DuckDB's standard strings), the
  criterion text goes into a `--` comment with every line break removed by `_comment`, and the numbers are pydantic
  ints and floats. The values are escaped, not bound, which is why they are class 3.
* **Low**, catalogue and database names the box made itself: `services/console/demo_guard.py:298` (column, table
  and schema names from `information_schema`, put in double quotes without escaping an embedded quote),
  `services/omop/export.py:276` (`tb_record`'s column names), `services/omop/partitions.py:123` (partition names),
  `services/lake/store.py:630` (the DuckDB database name, quoted with embedded quotes doubled).
* **Low**, typed or regex-checked values: `services/omop/partitions.py:108` (a year from feed dates, an int),
  `services/vec/store.py:117` and `:122` (the embedding model name checked by `_MODEL`, the dimension by
  `check_dim`, the row limit by `int()`).

Observed outside the 164 (ruff does not flag `.format` on a module constant), not classed and not a finding: the SQL
header `HEADER` in `services/criteria_compiler/compile_sql/generator.py:45`, filled at line 677, puts the rule set's
name and version into a `--` comment without removing line breaks, and the requested version
(`services/criteria_compiler/service.py:446`) is not checked in code. Not traced further; named here for lane J and
part (b)'s rules.

## The table

Columns: the site as ruff reports it; the lane; the enclosing function (read from the code's syntax tree); what is
put into the text; the class; where the value comes from (the fixed set, or the path for class 3); what checks it;
the severity of a class 3 site.

| Site | Lane | Function | Interpolated | Class | Source, fixed set or path | Check | Severity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `deploy/windows/wsl2_policy.py:327` | W | check_windows_update | start, end, wrong | not SQL | a Windows Update status message passed to v.policy(); the words "Update ... set" trip the rule; never sent to a database | – | – |
| `deploy/windows/wsl2_policy.py:336` | W | check_windows_update | au, mdm | not SQL | a Windows Update status message passed to v.policy(); never sent to a database | – | – |
| `libs/tb_common/db.py:663` | D | Database.applied | bf_at | 2 | one of two literals, "backfilled_at" or "NULL" (db.py:661), chosen by an information_schema column check | literal choice | – |
| `libs/tb_common/derived_store.py:338` | B2 | DerivedStore._conflicts_of | cols, ? marks | 1 | cols is a literal tuple (335); DECISIONS (derived_store.py:53) only sets the number of ? marks; row_id and DECISIONS bound | – | – |
| `libs/tb_common/derived_store.py:534` | B2 | DerivedStore.latest_many | valid | 1 | one of two literal fragments (528-532); as_of and other values bound | – | – |
| `libs/tb_common/derived_store.py:675` | B2 | rows_from_lake | pairs (system, code) | 2 | written inline as quoted literals from derived.CODES (derived.py:73, a literal dict) for the components of STORED and derived.COMPONENTS (derived.py:92); pids bound | constant dicts | – |
| `libs/tb_common/flags.py:282` | C2 | Flags.row | table (schema) | 2 | schema = the tb_prefix from TB_DB_URL (environment) + "app"; checked by _NAME_RE.match (flags.py:59) at flags.py:276 before use; name bound | _NAME_RE | – |
| `libs/tb_common/flags.py:338` | C2 | Flags.events | where | 1 | where is the literal "WHERE name = ?" or "" (333); name and int(limit) bound | – | – |
| `libs/tb_common/lakeprobe.py:31` | B2 | table_sql | table | 2 | written inline in quotes; _NAME.fullmatch (lakeprobe.py:18) checked at line 29, else ValueError | _NAME.fullmatch | – |
| `libs/tb_common/notmatched.py:185` | A2 | NotMatchedStore.sample | _COLS | 1 | _COLS is a module constant column list (notmatched.py:79); ruleset and week bound | – | – |
| `libs/tb_common/notmatched.py:192` | A2 | NotMatchedStore.history | _COLS | 1 | _COLS constant (notmatched.py:79); ruleset and limit bound | – | – |
| `libs/tb_common/refdata.py:692` | E | RefStore.load | table | 2 | loop over the TABLES tuple (refdata.py:137); sid bound | TABLES | – |
| `libs/tb_common/refdata.py:770` | E | RefStore._withdraw | table | 2 | loop over the TABLES tuple (refdata.py:137); sid bound | TABLES | – |
| `libs/tb_common/refdata.py:810` | E | RefStore.ctgov_search | where fragments, ? marks | 1 | literal fragments; the number of locations only sets how many "countries LIKE ?" appear; all values bound (LIKE-escaped by _esc) | – | – |
| `libs/tb_common/refdata.py:823` | E | RefStore.trials | where fragments | 1 | literal fragments; registry, condition and limit bound | – | – |
| `libs/tb_common/refdata.py:849` | E | RefStore._map | where | 1 | both callers (refdata.py:832, 845) pass literal "... = ? AND ... = ?" text; values bound | – | – |
| `services/adapter/licensed.py:332` | E | TermStore.releases | " WHERE kind = ?" | 1 | literal fragment; kind bound | – | – |
| `services/adapter/pidmap.py:237` | E | PidMap._every_pseudonym_holds | table | 2 | literal tuple ("pid_map", "pending") at pidmap.py:236; key_id bound | literal tuple | – |
| `services/adapter/sources/cgrd_sql/source.py:35` | E | SqlSource.columns | source_name | 2 | table name from the operator's mapping file; _IDENT.match (source.py:19) checked at line 32, else ValueError | _IDENT | – |
| `services/adapter/sources/cgrd_sql/source.py:112` | E | SqlSource.rows | what (columns), source_name, delta_column | 2 | source_name and delta_column from the mapping, checked by _IDENT.match (line 100); column names from the source's catalogue, joined only if all match _IDENT (line 110); since and until bound | _IDENT | – |
| `services/console/auth.py:482` | C2 | UserStore.users | _COLS | 1 | _COLS constant (auth.py:207) | – | – |
| `services/console/auth.py:486` | C2 | UserStore.get | _COLS | 1 | _COLS constant (auth.py:207); username bound | – | – |
| `services/console/auth.py:507` | C2 | UserStore.set_scope | _COLS | 1 | _COLS constant; username bound | – | – |
| `services/console/auth.py:554` | C2 | UserStore.upsert_sso | _COLS | 1 | _COLS constant; u bound | – | – |
| `services/console/auth.py:601` | C2 | UserStore.upsert_oidc | _COLS | 1 | _COLS constant; u bound | – | – |
| `services/console/auth.py:659` | C2 | UserStore.disabled_users | _COLS | 1 | _COLS constant | – | – |
| `services/console/auth.py:739` | C2 | UserStore.authenticate | _COLS | 1 | _COLS constant; the sign-in name u bound | – | – |
| `services/console/auth.py:1104` | C2 | UserStore.confirming_accounts | _COLS | 1 | _COLS constant | – | – |
| `services/console/breakglass_store.py:175` | C2 | BreakGlassStore.get | _COLS | 1 | _COLS constant (breakglass_store.py:65); gid bound | – | – |
| `services/console/breakglass_store.py:180` | C2 | BreakGlassStore.grants | _COLS | 1 | _COLS constant; limit bound | – | – |
| `services/console/breakglass_store.py:183` | C2 | BreakGlassStore.of | _COLS | 1 | _COLS constant; username and limit bound | – | – |
| `services/console/breakglass_store.py:188` | C2 | BreakGlassStore.active | _COLS | 1 | _COLS constant; username and now bound | – | – |
| `services/console/breakglass_store.py:210` | C2 | BreakGlassStore.uses_of | marks | 1 | ", ".join of "?" over gids; gids bound | – | – |
| `services/console/demo_guard.py:298` | C2 | _db_texts | column, schema, table | 3 | database content: names the information_schema.columns query (286-294) returns for schemas under tb_prefix; reached from the demo_guard --db scan (demo_guard.py:324) -> _db_texts | double quotes only; an embedded double quote is not escaped; no allow-list | Low: the names are tables the box's own migrations made; only someone who can already create a table under the prefix reaches it |
| `services/console/feedback.py:132` | C2 | FeedbackStore.entries | _COLS | 1 | _COLS constant (feedback.py:68) | – | – |
| `services/console/firstrun.py:82` | C2 | box_holds_patients | schema, table | 2 | schema = db.schema (tb_prefix from TB_DB_URL + "auth", checked by _SCHEMA_RE.match at db.py:395 in Database.connect) with "auth" replaced by "pidmap"; table from the literal tuple at line 79 | _SCHEMA_RE and literal tuple | – |
| `services/console/sitestore.py:870` | C2 | SiteStore.irb_text | _IRB_COLS | 1 | class constant (sitestore.py:860); ruleset bound | – | – |
| `services/console/sitestore.py:878` | C2 | SiteStore.irb_text_history | _IRB_COLS | 1 | class constant; ruleset bound | – | – |
| `services/console/teamstore.py:391` | C2 | TeamStore.entries | _ENTRY | 1 | _ENTRY constant (teamstore.py:359); ruleset bound | – | – |
| `services/console/teamstore.py:395` | C2 | TeamStore.entry | _ENTRY | 1 | _ENTRY constant; ruleset and eid bound | – | – |
| `services/console/teamstore.py:556` | C2 | TeamStore.referrals | _REF | 1 | _REF constant (teamstore.py:363); ruleset and pid bound | – | – |
| `services/console/teamstore.py:563` | C2 | TeamStore.referral | _REF | 1 | _REF constant; ruleset and rid bound | – | – |
| `services/console/teamstore.py:685` | C2 | TeamStore.icf_history | _ICF | 1 | class constant _ICF (teamstore.py:677); ruleset bound | – | – |
| `services/criteria_compiler/compile_sql/generator.py:172` | A2 | SqlGenerator._vs_match | lit(vsname), system_col, code_col | 3 | a protocol or rule-set file: vsname = atom.valueset of the criterion IR (path P1); the columns from PRESENCE (generator.py:185) or the SYSTEMS / YJ_STEM constants | lit() (generator.py:67) doubles each single quote, a complete escape for DuckDB string literals; the query then runs through check_select on a read-only lake connection (lake/store.py:1651) | Low: free text from a file, escaped completely |
| `services/criteria_compiler/compile_sql/generator.py:180` | A2 | SqlGenerator._family_offlist | lit(vsname), system_col, code_col, _vs_match(...) | 3 | as generator.py:172 (atom.valueset, P1) | lit(); check_select | Low: escaped completely |
| `services/criteria_compiler/compile_sql/generator.py:212` | A2 | SqlGenerator._presence.src | rid_sel, d, table, where | 3 | table, rid and d from the PRESENCE ClassVar (generator.py:185), checked at :202; where carries lit(atom.valueset) (P1) and lit(clinical_status), a pydantic Literal | domain a Literal and `in PRESENCE`; lit() on valueset; check_select | Low: escaped completely |
| `services/criteria_compiler/compile_sql/generator.py:225` | A2 | SqlGenerator._presence.cte | n (CTE name), source, in_window(w) | 3 | n = a_{ident(c.id)}_N (CRITERION_ID pattern); source = src() with lit(valueset) (P1); window days from atom.window | id regex (models.py:3290); window ints by pydantic; lit(); check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:243` | A2 | SqlGenerator._presence | nd, src(listed or family) | 3 | nd from the regex-checked id; src carries lit(valueset) (P1) | id regex; lit(); check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:296` | A2 | SqlGenerator._obs_source | num (value_sql), bad, in_window(w), _vs_match | 3 | v.unit -> value_sql (tb_common/labunit.py:215), quotes doubled at labunit.py:221; valueset through lit() (P1); window ints | quote doubling (complete); pydantic int; check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:317` | A2 | SqlGenerator._obs_value | name, c (obs_cmp_sql), src, lit(UNIT_MISMATCH), stands, ref | 3 | c: value.codes through lit() (P1); num through fmt_num on a pydantic float (semantics.py:187); src as generator.py:296 | lit(); float type (a non-finite float gives a broken query, not other SQL); check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:366` | A2 | SqlGenerator._obs_value | name, agg, c, bad_refs, could_refs, src, lit(UNIT_MISMATCH), atom.count | 3 | as generator.py:317; atom.count a pydantic int | lit(); int and float types; check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:390` | A2 | SqlGenerator._latest_component | name, comp, domain_sql, unit_sql, anchor (int(days)), in_window(w), lit(system, code) | 3 | comp, CODES, DOMAIN, UNITS and SAME_VISIT are fixed tables in tb_common/derived.py; name from the regex-checked id; window days from atom.window (P1) | pydantic int window; int(); id regex | Low: only int values come from the file |
| `services/criteria_compiler/compile_sql/generator.py:503` | A2 | SqlGenerator._derived | name, value, refs, why, joins | 2 | formulas from COMPONENTS, EGFR, EGFR_JSN, DAS28, ASDAS (tb_common/derived.py:92-134); reasons the MISSING / UNIT constants; atom.derived checked against COMPONENTS (generator.py:406); name passes the CRITERION_ID regex (models.py:3290) and ident() | fixed tables and the id regex | – |
| `services/criteria_compiler/compile_sql/generator.py:507` | A2 | SqlGenerator._derived | name | 2 | from c.id, which must match CRITERION_ID on CriterionIR.id (models.py:3290; enforced at postprocess.py:562 and when a rule set loads); ident() maps - to _ | id regex | – |
| `services/criteria_compiler/compile_sql/generator.py:534` | A2 | SqlGenerator._med_duration | name, lo, hi, match | 3 | match = _vs_match(lit(atom.valueset)) (P1); lo and hi window ints | lit(); pydantic int; check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:544` | A2 | SqlGenerator._med_duration | name, gap + 1 | 3 | gap = atom.duration.gap_days (a pydantic int, Duration at models.py:344) from the IR (P1); name passes the id regex | int type | Low: an int |
| `services/criteria_compiler/compile_sql/generator.py:549` | A2 | SqlGenerator._med_duration | name | 2 | the regex-checked criterion id (models.py:3290) through ident() | id regex | – |
| `services/criteria_compiler/compile_sql/generator.py:553` | A2 | SqlGenerator._med_duration | name | 2 | the regex-checked criterion id (models.py:3290) through ident() | id regex | – |
| `services/criteria_compiler/compile_sql/generator.py:563` | A2 | SqlGenerator._med_duration | name, match, hi | 3 | match carries lit(atom.valueset) (P1); hi a window int | lit(); pydantic int; check_select | Low: escaped or typed |
| `services/criteria_compiler/compile_sql/generator.py:642` | A2 | SqlGenerator.render | c.id, c.kind, _comment(c.text), crit, _bool(...), evs, joins | 3 | c.text is free protocol text (P1) put in a -- comment; id regex-checked, kind a Literal; the _bool expressions hold lit(sex, codes) and fmt_num values | _comment (generator.py:153) collapses all whitespace, so the comment cannot end early; literals through lit(); check_select | Low: comment text neutralised, literals escaped |
| `services/criteria_compiler/compile_sql/generator.py:642` | A2 | SqlGenerator.render | the + concatenation of joins (ruff's second hit on the same string) | 3 | c.text is free protocol text (P1) put in a -- comment; id regex-checked, kind a Literal; the _bool expressions hold lit(sex, codes) and fmt_num values | _comment (generator.py:153) collapses all whitespace, so the comment cannot end early; literals through lit(); check_select | Low: comment text neutralised, literals escaped |
| `services/criteria_compiler/library/repository.py:149` | A2 | CriterionLibrary.put | table | 2 | the literal tuple ("text", "valueset", "lexicon_key", "usage") at repository.py:148 | literal tuple | – |
| `services/datacore/optout_worker.py:228` | C2 | _verify_one_omop | t | 2 | loop over the OMOP_BY_PERSON tuple (optout_worker.py:175); persons bound | OMOP_BY_PERSON | – |
| `services/datacore/store.py:250` | C2 | DataCore.conflicts | " AND resolved IS NULL" | 1 | literal fragment; study bound | – | – |
| `services/edc/store.py:1029` | E | EdcStore.redcap_changes | "AND record = ? " | 1 | literal fragment; study and record bound | – | – |
| `services/edc/store.py:1079` | E | EdcStore.open_attempt | marks | 1 | "?" times len(READ_BACK) (edc/store.py:140); values bound | – | – |
| `services/lake/store.py:630` | B2 | _compat_views | db (current_database()) | 3 | the name of the DuckDB file the box opened: POST /query or /chunks/search (lake/app.py) -> _named -> LakeStore.connect/_open (store.py:1597) -> _compat_views | snapshot a pydantic date, generation isdigit() and int() in _named (app.py:80); the name is double-quoted with embedded quotes doubled (a complete identifier escape) | Low: the name is a file path the box built, not request text, and it is escaped |
| `services/lake/store.py:1437` | B2 | Lake._build | name | 2 | keys of the SCHEMAS dict (lake/flatten.py:42); the path is bound | SCHEMAS | – |
| `services/lake/store.py:1476` | B2 | Lake._build | chunk_cols | 2 | the CHUNK_COLUMNS list (store.py:86) | CHUNK_COLUMNS | – |
| `services/lake/store.py:1555` | B2 | Lake._embed.flush | DIM | 2 | DIM = 1024, a constant (store.py:62) | DIM | – |
| `services/lake/store.py:1705` | B2 | Lake.search | where, int(depth) | 2 | where is fixed text with ? marks; depth is the default 50, which no caller passes (app.py:111, client.py:339), and int() | default argument, int() | – |
| `services/lake/store.py:1713` | B2 | Lake.search | DIM, where, int(depth) | 2 | DIM (store.py:62); where fixed text with ? marks; depth the default 50, never passed | DIM, default argument | – |
| `services/lake/store.py:1718` | B2 | Lake.search | where | 1 | fixed text with ? marks; args bound | – | – |
| `services/lake/store.py:1731` | B2 | Lake.search | ? marks | 1 | a list of ? marks; keys bound | – | – |
| `services/mail_gateway/store.py:200` | C2 | MailDB._rows | where | 1 | callers pass the literal "WHERE key = ?" (184) or ? marks over OPEN_STATES (190; constant at 69); params bound | – | – |
| `services/mail_gateway/store.py:244` | C2 | MailDB.due | due | 1 | a literal fragment or ""; now_iso and limit bound | – | – |
| `services/mail_gateway/store.py:269` | C2 | MailDB.stale_sending | " FOR UPDATE SKIP LOCKED" | 1 | literal text appended; before_iso bound | – | – |
| `services/matching/carried.py:29` | A2 | _has | domain, system, table, col | 2 | called only at module level (carried.py:37-41) with literals and the SYSTEMS (mapper.py:45) and YJ_STEM (mapper.py:58) constants | literal arguments, constants | – |
| `services/matching/carried.py:35` | A2 | (module level) | t | 2 | the _TABLES tuple at carried.py:33 | _TABLES | – |
| `services/matching/recorded.py:28` | A2 | (module level) | table | 2 | the DOMAINS tuple at carried.py:44; the pid list bound | DOMAINS | – |
| `services/omop/__main__.py:83` | B2 | main | t | 2 | the schema.CDM_TABLES tuple (schema.py:60) and a literal list of tb_ tables | CDM_TABLES | – |
| `services/omop/dqd.py:162` | B2 | run | t | 2 | the keys of the CLINICAL dict (dqd.py:38) and a literal tuple | CLINICAL | – |
| `services/omop/dqd.py:184` | B2 | run | table, col | 2 | required_columns(): tables only CLINICAL and a literal list; columns are \w+ matches from the vendored DDL under services/omop/ddl (pinned by sha in pin.json) | CLINICAL, \w+ regex, pinned DDL | – |
| `services/omop/dqd.py:190` | B2 | run | table, col | 2 | the PRIMARY dict (dqd.py:77) | PRIMARY | – |
| `services/omop/dqd.py:194` | B2 | run | table, col, rtable, rcol | 2 | schema.foreign_keys(): \w+ matches from the pinned constraints file (sha checked by pinned()), tables only CDM_TABLES | pinned DDL, CDM_TABLES | – |
| `services/omop/dqd.py:205` | B2 | run | table | 2 | foreign_keys() as above | pinned DDL, CDM_TABLES | – |
| `services/omop/dqd.py:214` | B2 | run | table, col | 2 | the literal tuple of (person, visit_occurrence) at dqd.py:208; domain bound | literal tuple | – |
| `services/omop/dqd.py:223` | B2 | run | table, concept | 2 | the CLINICAL dict (dqd.py:38) | CLINICAL | – |
| `services/omop/dqd.py:248` | B2 | run | table, pk | 2 | the CLINICAL dict; table also bound | CLINICAL | – |
| `services/omop/dqd.py:287` | B2 | run | table, source, src_col | 2 | the CLINICAL dict (src_col derived from it by replace) | CLINICAL | – |
| `services/omop/dqd.py:292` | B2 | run | table, concept | 2 | the CLINICAL dict | CLINICAL | – |
| `services/omop/dqd.py:336` | B2 | run | table, start | 2 | the CLINICAL dict | CLINICAL | – |
| `services/omop/dqd.py:341` | B2 | run | table, start | 2 | the CLINICAL dict | CLINICAL | – |
| `services/omop/dqd.py:345` | B2 | run | table, start, end | 2 | the CLINICAL dict | CLINICAL | – |
| `services/omop/dqd.py:398` | B2 | relational_violations | table, col, rtable, rcol | 2 | foreign_keys() (pinned DDL, CDM_TABLES) | pinned DDL, CDM_TABLES | – |
| `services/omop/dqd.py:404` | B2 | relational_violations | table, col | 2 | required_columns() (pinned DDL, CLINICAL) | pinned DDL, CLINICAL | – |
| `services/omop/dqd.py:409` | B2 | relational_violations | table, col | 2 | the PRIMARY dict (dqd.py:77) | PRIMARY | – |
| `services/omop/dqd.py:413` | B2 | relational_violations | table, col, rtable, rcol | 2 | foreign_keys() | pinned DDL, CDM_TABLES | – |
| `services/omop/export.py:256` | B2 | _wind_back | table, ID_COL[table] | 2 | deletes is keyed only when `table in ID_COL` (export.py:247); the ID_COL dict at load.py:84; ids bound | ID_COL | – |
| `services/omop/export.py:259` | B2 | _wind_back | table | 2 | inserts is keyed by old["cdm_table"] only after the `in ID_COL` check (export.py:249); rows bound | ID_COL | – |
| `services/omop/export.py:276` | B2 | _wind_back | sets (column names) | 3 | database content: the column names of tb_record read from information_schema.columns (export.py:266) | none in code | Low: catalogue names the box's own migrations made |
| `services/omop/export.py:283` | B2 | _wind_back | later | 1 | the constant SQL text at export.py:279; at bound | – | – |
| `services/omop/export.py:354` | B2 | _emit_all | LIVE, ORDER | 1 | module constant text (export.py:42-43) | – | – |
| `services/omop/export.py:359` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/export.py:382` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/export.py:403` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/export.py:452` | B2 | _emit_all | LIVE | 1 | constant (export.py:43) | – | – |
| `services/omop/export.py:512` | B2 | _emit_all | LIVE, ORDER.replace(...) | 1 | constants; the replace runs on constant text | – | – |
| `services/omop/export.py:559` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/export.py:582` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/export.py:623` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/export.py:643` | B2 | _emit_all | LIVE, ORDER | 1 | constants (export.py:42-43) | – | – |
| `services/omop/load.py:580` | B2 | _map_ids | seq | 2 | the only callers pass the literals tb_person_seq, tb_provider_seq, tb_care_site_seq (load.py:974-976) | literal arguments | – |
| `services/omop/load.py:814` | B2 | _stage.flush | _KEY | 1 | constant text (load.py:776) | – | – |
| `services/omop/load.py:819` | B2 | _stage.flush | cols, _KEY | 2 | the _STAGE_COLS list (load.py:777) and the _KEY constant (load.py:776) | _STAGE_COLS | – |
| `services/omop/load.py:819` | B2 | _stage.flush | "c = EXCLUDED.c" list | 2 | the _STAGE_COLS list (load.py:777); ruff reports this line twice | _STAGE_COLS | – |
| `services/omop/load.py:884` | B2 | _staged_codes | column | 2 | the only callers pass the literals "std" and "codes" (load.py:749-750) | literal arguments | – |
| `services/omop/load.py:1459` | B2 | _write | sets | 2 | the TB_RECORD_COLS list (load.py:588) | TB_RECORD_COLS | – |
| `services/omop/load.py:1470` | B2 | _write | all_cols | 2 | the TB_RECORD_COLS list (load.py:588) | TB_RECORD_COLS | – |
| `services/omop/load.py:1579` | B2 | _drop_rows | col, table | 2 | col = ID_COL[table] (load.py:84), a KeyError for any other table; callers filter `in ID_COL` (load.py:1957); ids bound | ID_COL | – |
| `services/omop/load.py:1581` | B2 | _drop_rows | table, col | 2 | the ID_COL lookup as above | ID_COL | – |
| `services/omop/load.py:1692` | B2 | _derive | vocab.EHR | 2 | EHR = 32817, a constant (vocab.py:61) | EHR | – |
| `services/omop/load.py:1710` | B2 | _derive | a, b | 2 | the literal tuple ("p","c") / ("c","p") at load.py:1707; concept ids bound | literal tuple | – |
| `services/omop/partitions.py:101` | B2 | ensure_years | default, date_col | 2 | the PARTITIONED dict (partitions.py:20), checked with `table not in PARTITIONED`; lo and hi bound | PARTITIONED | – |
| `services/omop/partitions.py:108` | B2 | ensure_years | name (table_yYYYY), lo, hi, default, date_col | 3 | a feed file: the year comes from the dates of feed rows: the load batch (load.py:1440) -> years_of -> date.year; table and date_col from PARTITIONED | years_of keeps only date objects; the year is an int written with %04d | Low: only an int year reaches the text |
| `services/omop/partitions.py:111` | B2 | ensure_years | default, date_col | 2 | the PARTITIONED dict (partitions.py:20) | PARTITIONED | – |
| `services/omop/partitions.py:123` | B2 | layout | p | 3 | database content: partition names read from pg_inherits and pg_class (partitions()) | none in code | Low: catalogue names the box made itself (table_yYYYY) |
| `services/omop/vocab_load.py:933` | B2 | load_athena | _CONCEPT_COLS | 2 | the _CONCEPT_COLS tuple (vocab_load.py:826) | _CONCEPT_COLS | – |
| `services/orchestrator/db.py:320` | A2 | JobDB.put | keep | 1 | one of two constant strings (db.py:317); all values bound | – | – |
| `services/orchestrator/db.py:368` | A2 | JobDB.find | where (col = ?) | 2 | col from the literal tuple at db.py:358-364; values bound | literal tuple | – |
| `services/orchestrator/db.py:421` | A2 | JobDB.scheduler_jobs | where | 1 | constant fragments from the filters tuple (db.py:401) and ? marks for TERMINAL (db.py:221); values bound | – | – |
| `services/orchestrator/db.py:469` | A2 | JobDB.claim | types | 1 | the constant " AND type = ANY(?)"; the list bound | – | – |
| `services/orchestrator/db.py:583` | A2 | JobDB.unfinished | terminal | 1 | ? marks over TERMINAL; values bound | – | – |
| `services/orchestrator/db.py:752` | A2 | JobDB._submission_insert | upsert | 1 | constant text at db.py:746; values bound | – | – |
| `services/orchestrator/db.py:781` | A2 | JobDB.prune_inactive | marks | 1 | a list of ? marks; values bound | – | – |
| `services/orchestrator/db.py:784` | A2 | JobDB.prune_inactive | marks | 1 | a list of ? marks; values bound | – | – |
| `services/orchestrator/db.py:804` | A2 | JobDB.candidate_get | _CAND_KEYS | 2 | the class tuple at db.py:789 | _CAND_KEYS | – |
| `services/orchestrator/db.py:810` | A2 | JobDB.candidates | _CAND_KEYS | 2 | the class tuple at db.py:789 | _CAND_KEYS | – |
| `services/orchestrator/db.py:841` | A2 | JobDB.candidate_set | _db_row_lock | 1 | the constant " FOR UPDATE" (db.py:1056), not overridden | – | – |
| `services/orchestrator/db.py:869` | A2 | JobDB.candidate_events | keys | 2 | the literal tuple at db.py:868 | literal tuple | – |
| `services/orchestrator/db.py:953` | A2 | JobDB._stored | _STORED_COLS, where | 2 | _STORED_COLS at db.py:950; where only literals from the callers (db.py:959, 963); values bound | _STORED_COLS, literal arguments | – |
| `services/orchestrator/db.py:974` | A2 | JobDB.cohort_read | _COHORT_COLS | 2 | the class tuple at db.py:878 | _COHORT_COLS | – |
| `services/orchestrator/db.py:998` | A2 | JobDB.cohort_before | cols | 2 | _COHORT_COLS (db.py:878) and two literals (db.py:997) | _COHORT_COLS | – |
| `services/orchestrator/db.py:1013` | A2 | JobDB.cohort_rows | _COHORT_COLS | 2 | the class tuple at db.py:878 | _COHORT_COLS | – |
| `services/orchestrator/db.py:1045` | A2 | JobDB.trial_cache_all | cols | 2 | the literal tuple at db.py:1044 | literal tuple | – |
| `services/orchestrator/db.py:1051` | A2 | JobDB.trial_cache_get | cols | 2 | the literal tuple at db.py:1049; values bound | literal tuple | – |
| `services/orchestrator/recall/ledger.py:196` | A2 | RecallLedger.purge_cells | t | 2 | the literal tuple at ledger.py:195; the prefix bound | literal tuple | – |
| `services/orchestrator/recall/ledger.py:220` | A2 | RecallLedger._counts | backend.row_lock | 1 | the constant " FOR UPDATE" (PostgresBackend.row_lock, db_pg.py:92, the only backend) | – | – |
| `services/orchestrator/recall/ledger.py:301` | A2 | RecallLedger.append | backend.row_lock | 1 | the constant " FOR UPDATE" (db_pg.py:92) | – | – |
| `services/orchestrator/recall/ledger.py:421` | A2 | RecallLedger.registration | backend.row_lock | 1 | the constant " FOR UPDATE" (db_pg.py:92) | – | – |
| `services/orchestrator/scenarios/feas_compute.py:271` | A2 | funnel_query | vsql | 3 | variant_sql (feas_compute.py:213): generator output for copies of rule-set criteria (P1) with threshold numbers from the job's variant options | numbers through float() (_numbers, :142) and CriterionIR.model_validate (:207); literals through lit(); check_select (feasibility goes through query_by_patients to LakeStore.query) | Low: generator output, escaped or typed |
| `services/orchestrator/scenarios/feas_compute.py:273` | A2 | funnel_query | safe_sql(rs), vcte, dept, vcols, vjoin, sel, agg | 3 | a rule-set file: safe_sql(rs) (overlay.py:56) returns rs.sql, the stored SQL of the rule set (compiler output, or an offline zip installed by criteria_compiler/import_ruleset.py), placed whole; vcols and sel use regex-checked ids; dept constant, departments bound ($5) | none on the text of rs.sql itself; the zip's manifest must say approved; then check_select (SELECT only) and a read-only lake connection with external access off | Medium: whole SQL text from a file is run as written; only SELECT-only and read-only limits stand between |
| `services/orchestrator/scenarios/feas_compute.py:273` | A2 | funnel_query | (ruff's second hit on the same expression) | 3 | a rule-set file: safe_sql(rs) (overlay.py:56) returns rs.sql, the stored SQL of the rule set (compiler output, or an offline zip installed by criteria_compiler/import_ruleset.py), placed whole; vcols and sel use regex-checked ids; dept constant, departments bound ($5) | none on the text of rs.sql itself; the zip's manifest must say approved; then check_select (SELECT only) and a read-only lake connection with external access off | Medium: whole SQL text from a file is run as written; only SELECT-only and read-only limits stand between |
| `services/orchestrator/scenarios/twpas.py:69` | A2 | _latest | col | 2 | a dict lookup over {"value_num", "value_code"} at twpas.py:67 (KeyError otherwise); values bound $1-$4 | literal dict | – |
| `services/orchestrator/scheduler.py:153` | A2 | recorded_close | years | 1 | the constant "keep_years" or "NULL" (scheduler.py:151); ruleset bound | – | – |
| `services/orchestrator/studystore.py:123` | A2 | _select | _COLS[table], table | 2 | keys of the _COLS dict at studystore.py:105 (KeyError otherwise); every caller (:155-346) passes a literal | _COLS | – |
| `services/patient_profile/twin.py:162` | B2 | read_lake | table, column names, pcols | 2 | the literal "patient" entry, the _TIMELINE dict (twin.py:52) and the _PROV tuple (twin.py:61); pids bound | _TIMELINE, _PROV | – |
| `services/sitesetup/store.py:148` | C2 | SetupStore.inputs | " AND kind = ?" | 1 | literal fragment; ws and kind bound | – | – |
| `services/sitesetup/store.py:262` | C2 | SetupStore.decide | sets (column names) | 2 | the keys of changes are filtered to the literal set allowed (sitesetup/store.py:255); values bound | allowed | – |
| `services/sitesetup/store.py:284` | C2 | SetupStore.undecide | sets (column names) | 2 | keys from stored JSON (database) filtered by the literal tuple ("term", "code", "system", "value", "unit", "day") at line 281; values bound | literal tuple | – |
| `services/sitesetup/store.py:404` | C2 | SetupStore.checks | " AND c.answer IS NULL" | 1 | literal fragment; ws bound | – | – |
| `services/sitesetup/store.py:486` | C2 | SetupStore.reset | t | 2 | literal tuple ("fact", "check_item", "local_code", "input", "published") at line 485; ws bound | literal tuple | – |
| `services/vec/store.py:117` | B2 | search_sql | cols, dist(dim), model, dim, k | 3 | config and database content: model from the embedder's model name (embed service config); k from callers (s2b.py:86 passes a chunk count from the database) via VecStore.search (store.py:236) | model checked by the _MODEL regex (store.py:33) in check_model; dim by check_dim (an int, 1 to 4000); k by int() | Low: every value is checked by a regex or is an int |
| `services/vec/store.py:122` | B2 | search_sql | cols, dist(dim), model, k | 3 | the same path as store.py:117 | _MODEL regex, check_dim, int(k) | Low: checked by a regex or an int |

## How the reading was done

Three sub-agents read the sites by directory (OMOP, lake and vector store, 58; orchestrator, compiler and matching,
50; console, libs and the rest, 56), each returning rows in this table's form. I checked 20 of their rows against the
code (8, 6 and 6): none was in the wrong class. Two kinds of change were made after the check: the function names
of 37 rows were wrong labels (for example `OrchDB` for the class `JobDB`) and were replaced by the names read from
each file's syntax tree; and the compiler rows' severity was lowered from Medium to Low, because the escape `lit()` is
complete and the generated SQL runs through `check_select` on a read-only connection.

Not done: no site was run with crafted input (this is a reading of the code, basis "shown" by reading); the offline
rule-set zip's signature check (in the update path, `tools/trialbox/update.py`) was not traced; the 163 bandit
findings were not matched one by one to these rows.
