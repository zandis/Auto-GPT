"""Erasure as an obligation of every store (T-727, D-465; review 2026-11-12 lifecycle F-7, root cause R4).

Every table every store's migrations create (``schema.table``), every top-level entry the lake and the adapter write
under the lake directory (``lake:<name>``), every object-store key prefix (``objects:<prefix>``) and every store
outside those (``outside:<name>``) has exactly one obligation here:

* :data:`ERASE`: an opt-out takes the patient out. ``clear`` names a :class:`Clear` (a function of the opt-out worker
  that takes the opted-out pseudonyms and returns counts, and the function that reads the store back). An entry with
  no clear yet is ``erase`` with ``owed_by`` (the card that builds it); an entry whose clear does only part of the job
  has both. Every entry with ``owed_by`` is on the **erasure owed** list (:func:`owed`).
* :data:`KEEP`: kept on purpose; ``decision`` names the decision that says why.
* :data:`NO_PATIENT_DATA`: nothing about a patient.

``tests/unit/test_erasure_registry.py`` enumerates the tables, lake entries and object prefixes from the code and
fails on one with no entry here (or an entry for one that is gone): a new store is not exempt by default. The opt-out
worker (``services/datacore/optout_worker.py``) runs every clear of :func:`clears` and its verify on each tick.

``python -m tb_common.erasure --write`` renders ``docs/validation/erasure-registry.md``; ``--check`` fails when the
file and this module differ.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

ERASE = "erase"
KEEP = "keep"
NO_PATIENT_DATA = "no_patient_data"
KINDS = (ERASE, KEEP, NO_PATIENT_DATA)
#: the card that builds the remaining clears on this registry (PR #278)
T206B = "T-206b"

DOC = Path(__file__).resolve().parents[2] / "docs" / "validation" / "erasure-registry.md"


@dataclass(frozen=True)
class Clear:
    """One clear the opt-out worker runs: ``clear(pids, env) -> counts`` (idempotent, counts only) and
    ``verify(pids, env) -> {table: rows of those pids still there}`` (an empty or all-zero result: nothing left).
    Both are ``"module:function"``, resolved when the worker runs (this library imports no service)."""

    name: str
    clear: str
    verify: str
    note: str

    def resolve(self) -> tuple[Callable[..., dict[str, int]], Callable[..., dict[str, int]]]:
        return _ref(self.clear), _ref(self.verify)


def _ref(ref: str) -> Callable[..., dict[str, int]]:
    mod, _, fn = ref.partition(":")
    out: Callable[..., dict[str, int]] = getattr(importlib.import_module(mod), fn)
    return out


@dataclass(frozen=True)
class Entry:
    kind: str
    why: str
    clear: str | None = None
    decision: str | None = None
    owed_by: str | None = None
    owed: str = ""


_W = "datacore.optout_worker"
CLEARS: dict[str, Clear] = {
    c.name: c
    for c in (
        Clear("candidate_pool", f"{_W}:clear_pool", f"{_W}:verify_pool", "MICROBATCH's pool rows go (D-441)"),
        Clear(
            "candidate_registry",
            f"{_W}:clear_candidates",
            f"{_W}:verify_candidates",
            "open candidates become withdrawn; consented and enrolled are kept (OD-8, D-441)",
        ),
        Clear(
            "omop",
            f"{_W}:clear_omop",
            f"{_W}:verify_omop",
            "tb_withheld, and the live rows deleted and tombstoned at once (D-441)",
        ),
        Clear(
            "vec",
            f"{_W}:clear_vec",
            f"{_W}:verify_vec",
            "VecStore.delete_patient: the chunks and every vector no other chunk uses (D-439)",
        ),
        Clear(
            "pid_pending",
            f"{_W}:clear_pending",
            f"{_W}:verify_pending",
            "the staged chart number and identity of the patient go; a later night stages them again (D-489)",
        ),
        Clear(
            "held_mail",
            f"{_W}:clear_held_mail",
            f"{_W}:verify_held_mail",
            "a held mail carrying an opted-out patient's own file is dropped: its request and recipients go (D-863)",
        ),
        Clear(
            "screening_log",
            f"{_W}:clear_screening_log",
            f"{_W}:verify_screening_log",
            "a never-consented patient's screening-log rows stay, numbered, under a random token; the PI's note and "
            "the registry's reasons go; a trial subject's stay (OD-8, D-1032, D-875)",
        ),
        Clear(
            "setup_uploads",
            f"{_W}:clear_setup_uploads",
            f"{_W}:verify_setup_uploads",
            "a patient's own upload to the site set-up (a chart) goes whole: rows, items, facts and files (D-869)",
        ),
        Clear(
            "owed_tables",
            f"{_W}:clear_tables",
            f"{_W}:verify_tables",
            "T-206b part 1 (D-798): the patient's rows in the site, team, PI feedback and derived tables go (the "
            "nightly derive skips an opted-out patient); a batch's failed list loses the pseudonym",
        ),
        Clear(
            "profile",
            f"{_W}:clear_profile",
            f"{_W}:verify_profile",
            "ProfileStore.erase: every version of the twin (D-440)",
        ),
        Clear(
            "provenance_index",
            f"{_W}:clear_provenance",
            f"{_W}:verify_provenance",
            "D-989 point 5: the provenance index's use rows of the patient go (provenance_index.erase)",
        ),
    )
}


def _none(why: str) -> Entry:
    return Entry(NO_PATIENT_DATA, why)


def _keep(decision: str, why: str) -> Entry:
    return Entry(KEEP, why, decision=decision)


def _erase(clear: str, why: str, owed: str = "") -> Entry:
    return Entry(ERASE, why, clear=clear, owed_by=T206B if owed else None, owed=owed)


def _owed(why: str, owed: str = "the clear", card: str = T206B) -> Entry:
    return Entry(ERASE, why, owed_by=card, owed=owed)


def _each(schema: str, tables: Iterable[str], entry: Entry) -> dict[str, Entry]:
    return {f"{schema}.{t}": entry for t in tables}


# ------------------------------------------------------------------------------------------------ the tables
_REFDATA = _none("public or licensed reference data")
_CONFIG = _none("settings and configuration, no patient")
_STAFF = _none("staff, accounts or sign-in state, no patient")
_OD8 = _keep("OD-8", "the trial record of a consented or enrolled subject stays (GCP)")
_OMOP_CLEARED = _erase("omop", "OMOP clinical rows of the person (deleted by the withhold, D-441)")
_OMOP_UNWRITTEN = _erase(
    "omop",
    "a CDM table keyed by person that no loader writes today: deleted by person at the withhold, so a loader that "
    "writes it later is covered from its first row, and read back by the worker (D-867)",
)
#: D-867: reached only through the person (an event, the person row): deleted then, and not read back after it
_OMOP_THROUGH = _erase(
    "omop",
    "a CDM table no loader writes today, reached through the person: deleted at the withhold with the person's "
    "events (cost, by domain) or its last person (an address); not read back, as nothing names the person after it "
    "(D-867)",
)
_OMOP_VOCAB = _none("OMOP vocabulary and metadata")

TABLES: dict[str, Entry] = {
    **_each(
        "refdata", ("concept_map", "ctgov_study", "pack", "source", "synonym", "term", "trial", "withdrawn"), _REFDATA
    ),
    "optout.optout_events": _keep("D-441", "the opt-out register itself: the record of the refusal (D-147)"),
    **_each(
        "recall",
        ("recall_cell", "recall_registration", "recall_run_cell", "recall_sequence_state"),
        _none("recall cells and sequences: counts by criterion, no patient"),
    ),
    "recall.recall_observation": _owed("pid_hash: an unsalted hash of the pseudonym, linkable"),
    "recall.recall_known_positive": _owed(
        "pid_hash and draw_id: an unsalted hash of the pseudonym, linkable",
        "both columns, with the certificate not adding the patient again (the review of D-866)",
    ),
    **_each("study", ("rc_connection", "rc_project_link", "screen_scope", "study_settings"), _CONFIG),
    "study.rc_read_log": _erase(
        "screening_log",
        "a REDCap read: when, who, ok, and its result (the changes and conflicts name a number with its pseudonym): a "
        "never-consented patient's pseudonym takes the screening log's token (the review of D-878)",
    ),
    "study.rc_record": _erase(
        "screening_log",
        "the REDCap project's records linked to pseudonyms: a never-consented patient's take the screening log's "
        "token (D-878, D-1032); a trial subject's stay (OD-8)",
    ),
    "study.rc_write": _none(
        "what was written to REDCap, by screening number and record, with the hash of the values: no pseudonym (the "
        "screening log keeps the number, D-875; D-878)"
    ),
    "orch.pool": _erase("candidate_pool", "MICROBATCH's candidate pool (a re-run's scratch copy is dropped with it)"),
    "orch.candidates": _erase(
        "candidate_registry",
        "the candidate registry (a never-consented patient's withdrawn row then takes a token: screening_log, D-875; "
        "a trial subject's stays, OD-8)",
    ),
    "orch.candidate_events": _erase(
        "screening_log",
        "each status change of a candidate: a never-consented patient's take a token and lose the reason (D-875)",
    ),
    "orch.feedback": _erase("owed_tables", "the PI's feedback on a candidate, by pseudonym"),
    "orch.judge_answers": _keep(
        "D-456",
        "a model's answers (a verdict and a quote; no pseudonym column) kept only while their job is unfinished: "
        "deleted when the job ends in any state, and at the orchestrator's start for jobs finished or gone",
    ),
    "orch.answers": _erase(
        "owed_tables",
        "the answer store (D-1360, card 10A-4): the latest answer of each patient on each criterion, by pseudonym, "
        "with its quote; deleted at an opt-out and with its snapshot (D-452); class D3, never exported",
    ),
    "orch.judged_pairs": _erase(
        "owed_tables",
        "the judged-pair store (D-908, D-519): a model's answer to a note question, by pseudonym; deleted at an "
        "opt-out and with its snapshot (D-452); class D3, never exported",
    ),
    "orch.jobs": _owed("a job's request may name a pseudonym (CASE, a reveal)"),
    "orch.submissions": _erase(
        "owed_tables",
        "NAV submissions, by pseudonym: a dry run goes; a live one stays (D-513: NHI's send-once guard and the record "
        "of a disclosure already made)",
    ),
    "orch.cohort_tables": _none("aggregate counts per quarter and criterion"),
    "orch.cohort_stored": _none(
        "D-648: each alliance table as it was stored (aggregate counts per quarter and criterion, the site, the "
        "sender's address, the job), kept so that a re-run reads the tables as they stood"
    ),
    "orch.cohort_read": _none("D-648: the point in that record at which a merge read the tables (job, a number)"),
    "orch.cohort_tables_before": _none(
        "D-648: the alliance tables as the version that began the record found them (aggregate counts, as "
        "orch.cohort_tables)"
    ),
    "orch.id_limits": _none("the identifier caps' use rows: staff and kind only"),
    "orch.mails": _none("a mail sent: message id, job, kind, subject"),
    "orch.trial_cache": _none("the public registry cache"),
    "sitesetup.input": _erase(
        "setup_uploads",
        "an uploaded file and the patient it belongs to: a patient's own upload is erased, file included, its row an "
        "empty marker (D-869)",
        "a sheet of many patients that names the patient (its file and its rows are not keyed by patient)",
    ),
    "sitesetup.fact": _erase("owed_tables", "a fact read from an uploaded file, by pseudonym (D-866)"),
    "sitesetup.check_item": _erase(
        "setup_uploads",
        "the raw value of an uploaded row: those of a patient's own upload go with it (D-869)",
        "a sheet's rows of the patient (not keyed by patient)",
    ),
    "sitesetup.fix": _erase(
        "setup_uploads",
        "example values of an uploaded column: those of a patient's own upload go with it (D-869)",
        "a sheet's examples of the patient (not keyed by patient)",
    ),
    **_each("sitesetup", ("local_code", "setting"), _CONFIG),
    "sitesetup.published": _none("a publish: when, snapshot, digest, counts"),
    "mail.intake": _none("a mail received: sender, action, job"),
    "mail.send_keys": _erase(
        "held_mail",
        "the outbox's send request while queued (attachments by key, a per-patient file's name, recipients)",
        "an uncertain mail (it may have left: a person checks), and a queued or held mail of lists: its files are "
        "asked about before each send (D-863), its row stays until a person or the send ends it; a held or queued mail "
        "of the patient's own file is dropped (D-874)",
    ),
    "mail.sent": _none("a mail sent: subject, recipients, tag"),
    **_each(
        "library",
        (
            "criterion_library",
            "criterion_library_lexicon_key",
            "criterion_library_meta",
            "criterion_library_text",
            "criterion_library_usage",
            "criterion_library_valueset",
        ),
        _none("the criteria library"),
    ),
    **_each("terminology", ("concept", "release"), _REFDATA),
    "pidmap.pid_map": _keep("D-441", "the chart number must still be recognised at the door to honour the opt-out"),
    "pidmap.pid_alias": _keep("D-441", "a merged chart's opt-out hides the surviving pseudonym (append-only)"),
    "pidmap.pending": _erase(
        "pid_pending",
        "a night's chart numbers and identities, encrypted, until the night is published or dropped (D-489)",
    ),
    "pidmap.identity": _owed("the encrypted identity of the patient", "the crypto-shred of the opted-out identity"),
    "pidmap.site_key": _none("the site key's fingerprint"),
    "trace.traces": _owed("a model call's redacted body: note excerpts", "the traces of the patient (7 days kept)"),
    "trace.access_log": _none("who read a trace and why"),
    **_each(
        "datacore",
        ("ae_ack", "conflict", "deviation_call", "history", "src_record", "subject_step", "value"),
        _OD8,
    ),
    "datacore.subject": _erase(
        "screening_log",
        "the lifecycle's subject of a screening number: a never-consented patient's pid column takes the screening "
        "log's token (the review of D-875; a record keyed by the pseudonym itself keeps it as its key, D-772); a "
        "trial subject's stays (OD-8)",
    ),
    **_each(
        "datacore",
        ("contact_rule", "form", "owner", "sae_rule", "schedule", "schedule_version", "source_cfg", "sponsor_layout"),
        _CONFIG,
    ),
    **_each(
        "auth",
        (
            "account_notices",
            "account_requests",
            "factor_resets",
            "login_failures",
            "oidc_pending",
            "pending_logins",
            "sessions",
            "users",
        ),
        _STAFF,
    ),
    "auth.session_drafts": _keep(
        "D-777",
        "a form sent after the session ended (TOL-AUTH): what was typed, never a secret; it may name a patient by "
        "pseudonym; cleared by time, 15 minutes at most; the console also deletes one that names an opted-out "
        "patient when a kept form is next read, kept or handed over (UserStore.drop_stale_drafts), and every kept "
        "form if the register cannot be read",
    ),
    "auth.user_pref": _none(
        "a person's own look and language (10F-1, D-1387): a closed set of values per key, no free text, nothing "
        "names a patient; it goes with the account when the account is disabled"
    ),
    "site.contact_outcomes": _erase("owed_tables", "a contact attempt's outcome, by pseudonym"),
    "site.excluded_review": _erase("owed_tables", "the review of an excluded patient, by pseudonym"),
    "site.pi_marks": _erase(
        "screening_log",
        "the PI's mark on a patient: a never-consented patient's take a token and lose the note (D-875)",
    ),
    "site.screening_no": _erase(
        "screening_log",
        "the screening number given to a pseudonym: a never-consented patient's number stays under a token (D-875)",
    ),
    "site.weekly_seen": _erase(
        "screening_log",
        "the week a pseudonym first appeared on a list: a never-consented patient's under a token (D-762, D-875)",
    ),
    **_each("site", ("approval_opened", "code_ticks"), _none("a review trace: job, criterion, who")),
    **_each(
        "site",
        (
            "criterion_labels",
            "notify_people",
            "site_profile",
            "study_identity",
            "study_irb_text",
            "study_settings",
            "study_state",
        ),
        _CONFIG,
    ),
    "site.notify_log": _none("a notice sent: kind, user, day, subject"),
    # 10C-4 (D-1227): a study's committee record and each site's head-of-institution permission; no patient
    **_each("team", ("committee", "committee_open", "site_permission"), _CONFIG),
    "team.monitor_visits": _keep(
        "OD-8", "a monitoring visit's record: the subjects reviewed are trial subjects (an essential record)"
    ),
    "team.approach_overrides": _erase("owed_tables", "an override of an approach warning, by pseudonym"),
    "team.candidate_views": _erase(
        "owed_tables",
        "a cross-department view of a candidate: the row stays for the reveal cap and for who saw an identity, its "
        "pseudonym becomes a random token, unlinked in this table; the kept audit log keeps the link (D-868, D-771)",
    ),
    "team.referrals": _erase("owed_tables", "a referral of a patient, by pseudonym"),
    "team.referral_events": _erase("owed_tables", "a referral's events, by pseudonym"),
    **_each(
        "team",
        ("delegation", "delegation_checks", "delegation_history", "dept_contacts", "icf_versions", "irb", "staff"),
        _STAFF,
    ),
    "feedback.entry": _none("in-product feedback from staff, not about a patient (record inventory O-02)"),
    # E-EDCB-2 (D-1044): the EDC door's state; the EDC's project and record ids, never a value or a name
    "edcdoor.oidc_code": _STAFF,
    "edcdoor.proposal": _keep(
        "OD-8",
        "a write held for a staff member's confirmation, by the EDC's record id; "
        "gone once confirmed or after 15 minutes",
    ),
    "edcdoor.event": _keep("OD-8", "the id of an event the trial's EDC sent, with the EDC's record id; no value"),
    "breakglass.grants": _keep("D-430", "the record of an emergency access to a patient, for the steward's review"),
    "breakglass.uses": _keep("D-430", "each use of a break-glass grant, for the steward's review"),
    "edc.draft": _owed(
        "an EDC draft, by pseudonym, with values read from the chart",
        "the drafts of a patient who never consented: the EDC drafts for any numbered patient (consent is not "
        "checked), and D-1032's definition counts a draft as a trial subject's, which keeps the patient's rows; "
        "whether a draft alone makes a trial subject is the owner's question (the review of D-878)",
    ),
    **_each("edc", ("copy_tick", "decision", "sent", "signature", "signature_void"), _OD8),
    **_each(
        "edc",
        ("direct_source_event", "item_map", "map_event", "reentry_record", "switch", "switch_event", "target"),
        _CONFIG,
    ),
    **_each("sae", ("sae_case", "sae_report", "sae_trail"), _keep("OD-8", "the SAE register of a trial subject")),
    **_each("app", ("flag", "flag_event"), _CONFIG),
    "derived.score_row": _erase("owed_tables", "a derived score of a pseudonym"),
    "derived.conflict": _erase("owed_tables", "a documented-versus-derived conflict of a pseudonym"),
    "derived.input_link": _erase("owed_tables", "the source rows each derived score was computed from"),
    "derived.batch_run": _erase(
        "owed_tables", "one row per nightly derive batch; failed_pids lists the pseudonyms whose recompute failed"
    ),
    "derived.definition": _none("score definitions"),
    **_each("dataops", ("batch", "batch_step"), _none("ingest batches and their steps: counts")),
    "dataops.built": _none("which generation each derived artefact is built from: names, states and times (D-491)"),
    "dataops.built_kept": _none("the finished generations of the derived rows and their batch ids: no patient (D-525)"),
    "tuned.tuned_patients": _erase(
        "owed_tables",
        "the weekly PI sample of patients not matched: the row stays so a reviewed week is never drawn again, its "
        "pseudonym becomes a random token and the PI's note goes; counted as removed on the page (D-868)",
    ),
    "tuned.not_matched_check": _none("the site's check of the sample: who, when, a note"),
    "vec.note_chunk": _erase("vec", "the masked chunks of a patient's notes"),
    "vec.embedding": _erase("vec", "one vector per chunk text: those no other chunk uses go with the chunks"),
    "profile.tb_patient_profile": _erase("profile", "the patient twin, every version"),
    # OMOP: the rows the withhold deletes
    **_each(
        "omop",
        (
            "person",
            "observation_period",
            "death",
            "visit_occurrence",
            "condition_occurrence",
            "drug_exposure",
            "procedure_occurrence",
            "measurement",
            "observation",
            "note",
            "note_nlp",
            "fact_relationship",
            "tb_appointment",
            "tb_claim",
            "visit_occurrence_ydefault",
            "condition_occurrence_ydefault",
            "drug_exposure_ydefault",
            "procedure_occurrence_ydefault",
            "measurement_ydefault",
            "observation_ydefault",
            "note_ydefault",
        ),
        _OMOP_CLEARED,
    ),
    **_each(
        "omop",
        (
            "condition_era",
            "drug_era",
            "dose_era",
            "device_exposure",
            "specimen",
            "visit_detail",
            "episode",
            "episode_event",
            "payer_plan_period",
            "cohort",
        ),
        _OMOP_UNWRITTEN,
    ),
    **_each("omop", ("cost", "location"), _OMOP_THROUGH),
    "omop.tb_record": _keep(
        "D-876",
        "the record ledger, ids and provenance (D-441, the owner's D-1031): the person's live records are "
        "tombstoned at the opt-out, and the FHIR fields a record carried (extra) are blanked at retention by the "
        "omop clear",
    ),
    "omop.tb_record_event": _erase(
        "omop",
        "every change of a record with its before-image: blanked at retention by the omop clear (D-1031)",
        "an opted-out patient's before-images until retention (the lake's month-end months): kept hidden, so a lift "
        "and the export as of a time work (D-1031, as D-513 for the lake's files)",
    ),
    "omop.tb_conflict": _owed(
        "a source conflict of a person, every source's value and the steward's ruling",
        "at retention, or with a before-image: a lift undoes the withhold, and the ruling must still hold (D-867)",
    ),
    "omop.tb_consent": _keep("D-441", "the refusal itself must reach the lake, or the registry would read as silent"),
    "omop.tb_id_map": _keep("D-441", "pseudonym to person id: the worker and the loader must still find the person"),
    "omop.tb_withheld": _keep("D-441", "the register's copy the loader reads to keep the patient out"),
    "omop.tb_load": _none("a load: batch and counts"),
    **_each("omop", ("care_site", "provider"), _none("sites and providers, no patient")),
    **_each(
        "omop",
        (
            "cdm_source",
            "metadata",
            "cohort_definition",
            "concept",
            "concept_ancestor",
            "concept_class",
            "concept_relationship",
            "concept_synonym",
            "domain",
            "drug_strength",
            "relationship",
            "source_to_concept_map",
            "vocabulary",
            "tb_concept_attr",
            "tb_map_relation",
            "tb_ruleset_release",
            "tb_term_grouper",
            "tb_vocab_release",
        ),
        _OMOP_VOCAB,
    ),
}

# ------------------------------------------------------------------------------------------------ the lake
# D-513 (the owner, 2026-11-15): the kept snapshots are not rebuilt; they are withheld on read and kept until
# retention rewrites them. Every job's patient scope drops an opted-out pseudonym at receipt and again at publish,
# audited by count (D-441); still owed (D-862): the criteria compiler's equivalence sample and a direct call of the
# lake's /query
_SNAPSHOTS = (
    "withheld on read by every job's scope (D-441, D-860); still read whole: the criteria compiler's "
    "equivalence sample (every patient) and a direct call of the lake's /query (D-862)"
)
LAKE: dict[str, Entry] = {
    "lake:ndjson": _owed("the nightly NDJSON extracts (3 nightly + month-ends kept)", _SNAPSHOTS),
    "lake:ndjson-rerun": _owed("a re-run of a promoted night until it passes the gate (D-271)", _SNAPSHOTS),
    "lake:db": _owed("the DuckDB snapshots (nightly and month-end) and their side files", _SNAPSHOTS),
    "lake:parquet": _owed("the Parquet copy of each snapshot", _SNAPSHOTS),
    "lake:site": _owed("facts the site set-up published, as NDJSON, by pseudonym"),
    "lake:embed_cache.duckdb": _owed(
        "vectors of note chunks by text hash, never pruned",
        "pruning by the patient across every kept snapshot, with the nightly build not embedding them again (D-862)",
    ),
    "lake:fhir_ledger": _owed("the FHIR sync ledger: resource ids and hashes per patient"),
    "lake:backfill": _owed("the back-fill's working copy of a year's extract"),
    "lake:tmp": _owed(
        "the rebuild's and the night's ingest scratch files (removed after each; a crash may leave them)"
    ),
    "lake:holds": _none("a job's hold on a snapshot: job id and date"),
    "lake:CURRENT": _none("the name of the served snapshot"),
    "lake:CURRENT.tmp": _none("the served snapshot's name while it is replaced"),
    "lake:FEED": _none("the date of the last feed snapshot"),
    "lake:.rebuild.lock": _none("the lock one lake rebuild holds (T-722), no patient"),
    "lake:locks": _none("lock files of the lake's readers and writers (T-722), rebuild job states (T-690)"),
}

# ------------------------------------------------------------------------------------------------ object store
OBJECTS: dict[str, Entry] = {
    "objects:outputs": _owed(
        "job outputs: candidate and excluded lists, micro-batch pids (365 days); withheld on read (D-513, D-860): the "
        "console's pages and downloads (a per-patient file by its patient), a submission and a feedback row; the mail "
        "outbox asks before each send (D-863)",
        "kept until retention (D-513): other patients' pages read the same files, so no clear deletes them",
    ),
    "objects:attachments": _owed(
        "files mailed or uploaded to a job (consent forms, review sheets, case requests); a CASE chart of an "
        "opted-out subject is refused before it is read (D-873)",
        "the files kept with a job until retention (D-513): an attached chart of a patient who opted out after it came",
    ),
    "objects:ctgov": _none("public registry text and its parse"),
}

# ------------------------------------------------------------------------------------------------ outside both
OUTSIDE: dict[str, Entry] = {
    "outside:fhir_store": _owed("the FHIR store (HAPI, database hapi): every resource of the patient"),
    "outside:backups": _owed("every backup: the databases, the lake, the FHIR store", "the backups (with T-728)"),
    "outside:sitesetup_space_omop": _owed(
        "the OMOP store of a site set-up space other than the hospital's (schema omop_<hash of the space's lake "
        "folder>, made by a publish while the lake is built from OMOP), and that space's own lake (its site files "
        "and snapshot keep a deleted chart's text until the space is published again, D-869): the space's uploaded "
        "patients; Reset of "
        "the space drops it whole (D-714)",
        "the opt-out's clear in a practice space's store",
    ),
    "outside:provenance_index": _erase(
        "provenance_index",
        "D-989 point 5: the provenance index (schema provenance: model_calls, model_uses), derived from the audit "
        "chain and rebuilt from it; a use row names a patient by pseudonym and goes at the opt-out "
        "(tb_common.provenance_index.erase; a rebuild leaves an opted-out patient out); the call rows name no patient",
    ),
    "outside:audit": _keep(
        "D-394",
        "the audit chain and its journal: append-only, hash-chained; the opt-out's own "
        "events carry counts only, never who (D-147, D-441)",
    ),
}


def entries() -> dict[str, Entry]:
    """Every obligation, by key."""
    return {**TABLES, **LAKE, **OBJECTS, **OUTSIDE}


def owed() -> list[tuple[str, str, str]]:
    """The erasure owed: ``(key, card, what)`` of every ``erase`` entry not fully met today, sorted."""
    return sorted((k, str(e.owed_by), e.owed) for k, e in entries().items() if e.owed_by)


def clears() -> list[Clear]:
    """The clears the registry names, by name."""
    named = {e.clear for e in entries().values() if e.clear}
    return [CLEARS[n] for n in sorted(named)]


def tables_of(clear: str) -> list[str]:
    return sorted(k for k, e in entries().items() if e.clear == clear)


def problems() -> list[str]:
    """Entries that break the rules of the registry (empty: none)."""
    out: list[str] = []
    for k, e in sorted(entries().items()):
        if e.kind not in KINDS:
            out.append(f"{k}: kind {e.kind!r}")
        if not e.why:
            out.append(f"{k}: no reason")
        if e.kind == KEEP and not (e.decision and e.decision.startswith(("D-", "OD-"))):
            out.append(f"{k}: kept with no decision")
        if e.kind == ERASE and not (e.clear or e.owed_by):
            out.append(f"{k}: erase with no clear and no card that owes it")
        if e.kind == ERASE and e.owed_by and not e.owed:
            out.append(f"{k}: owed with no description")
        if e.kind != ERASE and (e.clear or e.owed_by):
            out.append(f"{k}: only an erase entry has a clear or an owed card")
        if e.clear and e.clear not in CLEARS:
            out.append(f"{k}: clear {e.clear!r} is not in CLEARS")
    out += [f"clear {n}: no entry uses it" for n in sorted(set(CLEARS) - {c.name for c in clears()})]
    return out


def render() -> str:
    """The generated page ``docs/validation/erasure-registry.md``."""
    es = entries()
    count = {k: sum(1 for e in es.values() if e.kind == k) for k in KINDS}
    lines = [
        "# Erasure registry: what an opt-out removes, keeps and still owes",
        "",
        "*Generated from `libs/tb_common/erasure.py` by `python -m tb_common.erasure --write` (T-727, D-465). "
        "Do not edit by hand.*",
        "",
        f"{len(es)} entries: {count[ERASE]} erase, {count[KEEP]} keep, {count[NO_PATIENT_DATA]} no patient data. "
        f"{len(owed())} erase entries are owed. `tests/unit/test_erasure_registry.py` fails on a table, lake entry or "
        "object prefix the code makes with no entry here.",
        "",
        "## 1. Erased on opt-out today",
        "",
        "The opt-out worker runs each clear on every tick and reads the store back; a row left fails the tick.",
        "",
        "| Clear | What it does | Stores |",
        "| --- | --- | --- |",
    ]
    for c in clears():
        lines.append(f"| `{c.name}` | {c.note} | {', '.join(f'`{t}`' for t in tables_of(c.name))} |")
    lines += [
        "",
        "## 2. Erasure owed",
        "",
        "| Store | Card | What is owed | Why it holds patient data |",
        "| --- | --- | --- | --- |",
    ]
    for k, card, what in owed():
        lines.append(f"| `{k}` | {card} | {what} | {es[k].why} |")
    lines += ["", "## 3. Kept, with the decision", "", "| Store | Decision | Why |", "| --- | --- | --- |"]
    for k, e in sorted(es.items()):
        if e.kind == KEEP:
            lines.append(f"| `{k}` | {e.decision} | {e.why} |")
    lines += ["", "## 4. No patient data", "", "| Store | What it holds |", "| --- | --- |"]
    for k, e in sorted(es.items()):
        if e.kind == NO_PATIENT_DATA:
            lines.append(f"| `{k}` | {e.why} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--write" in args:
        DOC.write_text(render(), encoding="utf-8")
        return 0
    if "--check" in args:
        ok = DOC.exists() and DOC.read_text(encoding="utf-8") == render()
        if not ok:
            print(f"{DOC.name} is out of date: run python -m tb_common.erasure --write")
        return 0 if ok else 1
    print(render(), end="")
    return 0


__all__ = [
    "CLEARS",
    "ERASE",
    "KEEP",
    "LAKE",
    "NO_PATIENT_DATA",
    "OBJECTS",
    "OUTSIDE",
    "TABLES",
    "Clear",
    "Entry",
    "clears",
    "entries",
    "owed",
    "problems",
    "render",
    "tables_of",
]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
