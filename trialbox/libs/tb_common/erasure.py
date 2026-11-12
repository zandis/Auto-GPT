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
            "profile",
            f"{_W}:clear_profile",
            f"{_W}:verify_profile",
            "ProfileStore.erase: every version of the twin (D-440)",
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
_OMOP_UNWRITTEN = _owed(
    "a CDM table keyed by person that no loader writes today", "a delete by person when a loader writes it"
)
_OMOP_VOCAB = _none("OMOP vocabulary and metadata")

TABLES: dict[str, Entry] = {
    **_each(
        "refdata", ("concept_map", "ctgov_study", "pack", "source", "synonym", "term", "trial", "withdrawn"), _REFDATA
    ),
    "optout.optout_events": _keep("D-441", "the opt-out register itself: the record of the refusal (D-147)"),
    "wf.outbox": _owed("a job's mail payloads may carry pseudonyms (candidate lists)"),
    "wf.steps": _owed("a job step's input and output may carry pseudonyms"),
    **_each(
        "recall",
        ("recall_cell", "recall_registration", "recall_run_cell", "recall_sequence_state"),
        _none("recall cells and sequences: counts by criterion, no patient"),
    ),
    "recall.recall_observation": _owed("pid_hash: an unsalted hash of the pseudonym, linkable"),
    "recall.recall_known_positive": _owed("pid_hash: an unsalted hash of the pseudonym, linkable"),
    **_each("study", ("rc_connection", "rc_project_link", "screen_scope", "study_settings"), _CONFIG),
    "study.rc_read_log": _none("a REDCap read: when, who, ok, counts"),
    "study.rc_record": _owed(
        "the REDCap project's records linked to pseudonyms",
        "the rows of a patient never consented (a consented subject's stay, OD-8)",
    ),
    "study.rc_write": _owed("what was written to REDCap, by link value and record"),
    "orch.pool": _erase("candidate_pool", "MICROBATCH's candidate pool (a re-run's scratch copy is dropped with it)"),
    "orch.candidates": _erase(
        "candidate_registry",
        "the candidate registry",
        "a withdrawn row keeps the pseudonym (consented and enrolled rows are kept, OD-8)",
    ),
    "orch.candidate_events": _owed(
        "each status change of a candidate, by pseudonym",
        "the events of a patient never consented (OD-8 keeps the rest)",
    ),
    "orch.feedback": _owed("the PI's feedback on a candidate, by pseudonym"),
    "orch.jobs": _owed("a job's request may name a pseudonym (CASE, a reveal)"),
    "orch.submissions": _owed("NAV submissions, by pseudonym"),
    "orch.cohort_tables": _none("aggregate counts per quarter and criterion"),
    "orch.id_limits": _none("the identifier caps' use rows: staff and kind only"),
    "orch.mails": _none("a mail sent: message id, job, kind, subject"),
    "orch.trial_cache": _none("the public registry cache"),
    "sitesetup.input": _owed("an uploaded file and the patient it belongs to"),
    "sitesetup.fact": _owed("a fact read from an uploaded file, by pseudonym"),
    "sitesetup.check_item": _owed("the raw value of an uploaded row"),
    "sitesetup.fix": _owed("example values of an uploaded column"),
    **_each("sitesetup", ("local_code", "setting"), _CONFIG),
    "sitesetup.published": _none("a publish: when, snapshot, digest, counts"),
    "mail.intake": _none("a mail received: sender, action, job"),
    "mail.send_keys": _owed("the outbox's send request while queued (attachments by key, recipients)"),
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
    "pidmap.identity": _owed("the encrypted identity of the patient", "the crypto-shred of the opted-out identity"),
    "pidmap.site_key": _none("the site key's fingerprint"),
    "trace.traces": _owed("a model call's redacted body: note excerpts", "the traces of the patient (7 days kept)"),
    "trace.access_log": _none("who read a trace and why"),
    **_each(
        "datacore",
        ("ae_ack", "conflict", "deviation_call", "history", "src_record", "subject", "subject_step", "value"),
        _OD8,
    ),
    **_each(
        "datacore",
        ("contact_rule", "form", "owner", "sae_rule", "schedule", "schedule_version", "source_cfg", "sponsor_layout"),
        _CONFIG,
    ),
    **_each("auth", ("login_failures", "oidc_pending", "pending_logins", "sessions", "users"), _STAFF),
    "site.contact_outcomes": _owed("a contact attempt's outcome, by pseudonym"),
    "site.excluded_review": _owed("the review of an excluded patient, by pseudonym"),
    "site.pi_marks": _owed(
        "the PI's mark on a patient, by pseudonym", "the marks of a patient never consented (the screening log's, OD-8)"
    ),
    "site.screening_no": _owed(
        "the screening number given to a pseudonym",
        "the number of a patient never consented (the screening log's, OD-8)",
    ),
    "site.weekly_seen": _owed("the week a pseudonym first appeared on a list"),
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
    "team.monitor_visits": _keep(
        "OD-8", "a monitoring visit's record: the subjects reviewed are trial subjects (an essential record)"
    ),
    "team.approach_overrides": _owed("an override of an approach warning, by pseudonym"),
    "team.candidate_views": _owed("a cross-department view of a candidate, by pseudonym"),
    "team.referrals": _owed("a referral of a patient, by pseudonym"),
    "team.referral_events": _owed("a referral's events, by pseudonym"),
    **_each(
        "team",
        ("delegation", "delegation_checks", "delegation_history", "dept_contacts", "icf_versions", "irb", "staff"),
        _STAFF,
    ),
    "feedback.entry": _none("in-product feedback from staff, not about a patient (record inventory O-02)"),
    "breakglass.grants": _keep("D-430", "the record of an emergency access to a patient, for the steward's review"),
    "breakglass.uses": _keep("D-430", "each use of a break-glass grant, for the steward's review"),
    "edc.draft": _owed(
        "an EDC draft, by pseudonym", "the drafts of a patient who never enrolled (an enrolled subject's stay, OD-8)"
    ),
    **_each("edc", ("copy_tick", "decision", "sent", "signature", "signature_void"), _OD8),
    **_each("edc", ("item_map", "map_event", "reentry_record", "switch", "switch_event", "target"), _CONFIG),
    **_each("sae", ("sae_case", "sae_report", "sae_trail"), _keep("OD-8", "the SAE register of a trial subject")),
    **_each("app", ("flag", "flag_event"), _CONFIG),
    "derived.score_row": _owed("a derived score of a pseudonym"),
    "derived.conflict": _owed("a documented-versus-derived conflict of a pseudonym"),
    "derived.input_link": _owed("the source rows each derived score was computed from"),
    "derived.definition": _none("score definitions"),
    **_each("dataops", ("batch", "batch_step"), _none("ingest batches and their steps: counts")),
    "tuned.tuned_patients": _owed("the weekly PI sample of patients not matched, by pseudonym"),
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
            "cost",
            "cohort",
            "location",
        ),
        _OMOP_UNWRITTEN,
    ),
    "omop.tb_record": _erase(
        "omop",
        "the record ledger: the person's live records are tombstoned",
        "the tombstoned row keeps the person id and the source record id",
    ),
    "omop.tb_record_event": _owed("every change of a record with its before-image", "the before-images"),
    "omop.tb_conflict": _owed("a source conflict of a person"),
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
_SNAPSHOTS = "kept snapshots (3 nightly + 36 month-ends): rebuild without the patient, or a tombstone list read"
LAKE: dict[str, Entry] = {
    "lake:ndjson": _owed("the nightly NDJSON extracts (3 nightly + month-ends kept)", _SNAPSHOTS),
    "lake:ndjson-rerun": _owed("a re-run of a promoted night until it passes the gate (D-271)", _SNAPSHOTS),
    "lake:db": _owed("the DuckDB snapshots (nightly and month-end) and their side files", _SNAPSHOTS),
    "lake:parquet": _owed("the Parquet copy of each snapshot", _SNAPSHOTS),
    "lake:site": _owed("facts the site set-up published, as NDJSON, by pseudonym"),
    "lake:embed_cache.duckdb": _owed("vectors of note chunks by text hash, never pruned", "pruning by the patient"),
    "lake:fhir_ledger": _owed("the FHIR sync ledger: resource ids and hashes per patient"),
    "lake:backfill": _owed("the back-fill's working copy of a year's extract"),
    "lake:tmp": _owed("the rebuild's scratch files (removed after a build; a crash may leave them)"),
    "lake:holds": _none("a job's hold on a snapshot: job id and date"),
    "lake:CURRENT": _none("the name of the served snapshot"),
    "lake:CURRENT.tmp": _none("the served snapshot's name while it is replaced"),
    "lake:FEED": _none("the date of the last feed snapshot"),
    "lake:.rebuild.lock": _none("the lock one lake rebuild holds (T-722), no patient"),
    "lake:locks": _none("lock files of the lake's readers and writers (T-722), rebuild job states (T-690)"),
}

# ------------------------------------------------------------------------------------------------ object store
OBJECTS: dict[str, Entry] = {
    "objects:outputs": _owed("job outputs: candidate and excluded lists, micro-batch pids (365 days)"),
    "objects:attachments": _owed("files mailed or uploaded to a job (consent forms, review sheets, case requests)"),
    "objects:ctgov": _none("public registry text and its parse"),
}

# ------------------------------------------------------------------------------------------------ outside both
OUTSIDE: dict[str, Entry] = {
    "outside:fhir_store": _owed("the FHIR store (HAPI, database hapi): every resource of the patient"),
    "outside:backups": _owed("every backup: the databases, the lake, the FHIR store", "the backups (with T-728)"),
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
