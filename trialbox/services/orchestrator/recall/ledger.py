"""The recall ledger (spec v4 §10.14 SAFE-10/12/14, §6.7; sprint task S1-12).

Tables (same SQL on PostgreSQL and SQLite, see :mod:`orchestrator.db_pg`):

``recall_cell``
    one row per (canonical criterion hash, stratum, series) with the running ``n``, ``found`` and the head of a hash
    chain over the ordered observations (``observation_seq_sha``).
``recall_observation``
    append-only audit draws, ordered by ``seq_no``; ``draw_id`` makes a repeated append a no-op.
``recall_sequence_state``
    the canonical-JSON ``ConfidenceSequence`` state per cell and α. It is advanced **in the same transaction** as
    the observations it absorbs, so ``state.n`` always equals the cell's ``n``; a resumed sequence is the
    uninterrupted one, byte for byte.
``recall_run_cell``, ``recall_registration``
    excluded counts E_c per run, and the α_c = α · E_c/ΣE allocation frozen at the study's first certificate.
``recall_known_positive``
    the two known-positive lines (H: historical enrollees; B: blinded chart review), append-only.

:func:`render_certificate` builds the :class:`~tb_contracts.recall.RecallCertificate` of a run from these tables.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tb_common import timeutil
from tb_common.recall import ConfidenceSequence, cp_lower, cp_upper
from tb_contracts.recall import (
    LINE_B_MIN_R,
    LINE_LABELS,
    CellBound,
    CsStateRef,
    KnownPositiveLine,
    KnownPositiveLineKind,
    RecallCell,
    RecallCertificate,
    RecallObservation,
    Stratum,
    StratumBound,
)

from orchestrator.db_pg import Clock, SqlBackend, Tx, apply_schema, canonical_json, sha256_text
from orchestrator.recall import state as cs_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS recall_cell (
  canonical_hash TEXT NOT NULL,
  stratum TEXT NOT NULL,
  series BIGINT NOT NULL,
  criterion_type TEXT,
  n BIGINT NOT NULL DEFAULT 0,
  found BIGINT NOT NULL DEFAULT 0,
  obs_head TEXT NOT NULL,
  first_look TEXT,
  created TEXT NOT NULL,
  PRIMARY KEY (canonical_hash, stratum, series)
);
CREATE TABLE IF NOT EXISTS recall_observation (
  canonical_hash TEXT NOT NULL,
  stratum TEXT NOT NULL,
  series BIGINT NOT NULL,
  seq_no BIGINT NOT NULL,
  draw_id TEXT NOT NULL,
  pid_hash TEXT NOT NULL,
  study_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  draw_prob DOUBLE PRECISION NOT NULL,
  weight DOUBLE PRECISION NOT NULL,
  label BIGINT NOT NULL,
  y DOUBLE PRECISION NOT NULL,
  route TEXT NOT NULL,
  weighting TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (canonical_hash, stratum, series, seq_no),
  UNIQUE (canonical_hash, stratum, series, draw_id)
);
CREATE TABLE IF NOT EXISTS recall_sequence_state (
  canonical_hash TEXT NOT NULL,
  stratum TEXT NOT NULL,
  series BIGINT NOT NULL,
  alpha TEXT NOT NULL,
  n BIGINT NOT NULL,
  state TEXT NOT NULL,
  state_sha TEXT NOT NULL,
  obs_head TEXT NOT NULL,
  updated TEXT NOT NULL,
  PRIMARY KEY (canonical_hash, stratum, series, alpha)
);
CREATE TABLE IF NOT EXISTS recall_run_cell (
  run_id TEXT NOT NULL,
  study_id TEXT NOT NULL,
  ruleset TEXT NOT NULL,
  period TEXT NOT NULL,
  canonical_hash TEXT NOT NULL,
  stratum TEXT NOT NULL,
  series BIGINT NOT NULL,
  excluded BIGINT NOT NULL,
  recorded TEXT NOT NULL,
  PRIMARY KEY (run_id, canonical_hash, stratum, series)
);
CREATE TABLE IF NOT EXISTS recall_registration (
  study_id TEXT NOT NULL,
  ruleset TEXT NOT NULL,
  series BIGINT NOT NULL,
  alpha TEXT NOT NULL,
  allocation TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  PRIMARY KEY (study_id, ruleset)
);
CREATE TABLE IF NOT EXISTS recall_known_positive (
  line TEXT NOT NULL,
  population TEXT NOT NULL,
  seq_no BIGINT NOT NULL,
  draw_id TEXT NOT NULL,
  pid_hash TEXT NOT NULL,
  missed BIGINT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (line, population, seq_no),
  UNIQUE (line, population, draw_id)
)
"""

CHAIN_GENESIS = "sha256:" + "0" * 64
CS_METHOD = "1 − confidence-sequence upper bound on the miss rate (anytime)"


class LedgerError(RuntimeError):
    pass


def alpha_key(alpha: float) -> str:
    return repr(float(alpha))


def chain(head: str, y: float) -> str:
    return "sha256:" + hashlib.sha256((head + canonical_json(float(y))).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CellCounts:
    n: int
    found: int
    obs_head: str
    first_look: str | None


CellKey = tuple[str, Stratum, int]


def _key(cell: RecallCell) -> CellKey:
    return (cell.canonical_hash, cell.stratum, cell.series)


class RecallLedger:
    def __init__(self, backend: SqlBackend, clock: Clock = timeutil.now) -> None:
        self.backend = backend
        self.clock = clock
        apply_schema(backend, SCHEMA)

    # ------------------------------------------------------------------------------------------------ cells
    def ensure_cell(self, cell: RecallCell) -> None:
        with self.backend.transaction() as tx:
            self._ensure_cell(tx, cell)

    def _ensure_cell(self, tx: Tx, cell: RecallCell) -> None:
        tx.execute(
            "INSERT INTO recall_cell (canonical_hash, stratum, series, criterion_type, n, found, obs_head, created)"
            " VALUES (?, ?, ?, ?, 0, 0, ?, ?) ON CONFLICT (canonical_hash, stratum, series) DO NOTHING",
            (
                cell.canonical_hash,
                cell.stratum.value,
                cell.series,
                cell.criterion_type,
                CHAIN_GENESIS,
                timeutil.iso(self.clock()),
            ),
        )

    def _counts(self, tx: Tx, key: CellKey, lock: bool = False) -> CellCounts | None:
        row = tx.fetchone(
            "SELECT n, found, obs_head, first_look FROM recall_cell WHERE canonical_hash = ? AND stratum = ?"
            " AND series = ?" + (self.backend.row_lock if lock else ""),
            (key[0], key[1].value, key[2]),
        )
        return CellCounts(int(row[0]), int(row[1]), str(row[2]), row[3]) if row else None

    def counts(self, cell: RecallCell) -> CellCounts:
        with self.backend.transaction() as tx:
            c = self._counts(tx, _key(cell))
        return c if c is not None else CellCounts(0, 0, CHAIN_GENESIS, None)

    def observations(self, cell: RecallCell) -> list[float]:
        with self.backend.transaction() as tx:
            return self._ys(tx, _key(cell))

    def _ys(self, tx: Tx, key: CellKey) -> list[float]:
        rows = tx.fetchall(
            "SELECT y FROM recall_observation WHERE canonical_hash = ? AND stratum = ? AND series = ? ORDER BY seq_no",
            (key[0], key[1].value, key[2]),
        )
        return [float(r[0]) for r in rows]

    # ------------------------------------------------------------------------------------------------ append
    def append(self, observations: Sequence[RecallObservation]) -> int:
        """Append observations (idempotent per ``draw_id``) and advance every stored sequence state of the cells
        they touch, in one transaction. Returns the number of new observations."""
        by_cell: dict[CellKey, list[RecallObservation]] = {}
        for o in observations:
            by_cell.setdefault((o.canonical_hash, o.stratum, o.series), []).append(o)
        added = 0
        now = timeutil.iso(self.clock())
        with self.backend.transaction() as tx:
            for key, obs in by_cell.items():
                self._ensure_cell(tx, RecallCell(canonical_hash=key[0], stratum=key[1], series=key[2]))
                counts = self._counts(tx, key, lock=True)
                assert counts is not None
                n, found, head, first = counts.n, counts.found, counts.obs_head, counts.first_look
                new_ys: list[float] = []
                for o in obs:
                    if tx.fetchone(
                        "SELECT 1 FROM recall_observation WHERE canonical_hash = ? AND stratum = ? AND series = ?"
                        " AND draw_id = ?",
                        (key[0], key[1].value, key[2], o.draw_id),
                    ):
                        continue
                    n += 1
                    tx.execute(
                        "INSERT INTO recall_observation (canonical_hash, stratum, series, seq_no, draw_id, pid_hash,"
                        " study_id, run_id, draw_prob, weight, label, y, route, weighting, observed_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            key[0],
                            key[1].value,
                            key[2],
                            n,
                            o.draw_id,
                            o.pid_hash,
                            o.study_id,
                            o.run_id,
                            o.draw_prob,
                            o.weight,
                            o.label,
                            o.y,
                            o.route,
                            o.weighting,
                            timeutil.iso(o.observed_at),
                        ),
                    )
                    found += o.label
                    head = chain(head, o.y)
                    first = first or timeutil.iso(o.observed_at)
                    new_ys.append(o.y)
                if not new_ys:
                    continue
                added += len(new_ys)
                tx.execute(
                    "UPDATE recall_cell SET n = ?, found = ?, obs_head = ?, first_look = ? WHERE canonical_hash = ?"
                    " AND stratum = ? AND series = ?",
                    (n, found, head, first, key[0], key[1].value, key[2]),
                )
                for alpha_s, st_n, text in tx.fetchall(
                    "SELECT alpha, n, state FROM recall_sequence_state WHERE canonical_hash = ? AND stratum = ?"
                    " AND series = ?" + self.backend.row_lock,
                    (key[0], key[1].value, key[2]),
                ):
                    if int(st_n) != counts.n:
                        raise LedgerError(f"sequence state of {key} at alpha {alpha_s} is out of step")
                    cs = cs_state.loads(text)
                    cs.extend(new_ys)
                    self._save_state(tx, key, alpha_s, cs, head, now)
        return added

    def _save_state(self, tx: Tx, key: CellKey, alpha_s: str, cs: ConfidenceSequence, head: str, now: str) -> None:
        text = cs_state.dumps(cs)
        tx.execute(
            "INSERT INTO recall_sequence_state (canonical_hash, stratum, series, alpha, n, state, state_sha, obs_head,"
            " updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (canonical_hash, stratum, series, alpha) DO UPDATE SET n = excluded.n,"
            " state = excluded.state, state_sha = excluded.state_sha, obs_head = excluded.obs_head,"
            " updated = excluded.updated",
            (key[0], key[1].value, key[2], alpha_s, cs.n, text, sha256_text(text), head, now),
        )

    # ------------------------------------------------------------------------------------------------ sequences
    def state_json(self, cell: RecallCell, alpha: float) -> str:
        """The stored canonical state at α (created from the stored observations on first use)."""
        key, alpha_s = _key(cell), alpha_key(alpha)
        with self.backend.transaction() as tx:
            row = tx.fetchone(
                "SELECT state, n FROM recall_sequence_state WHERE canonical_hash = ? AND stratum = ? AND series = ?"
                " AND alpha = ?",
                (key[0], key[1].value, key[2], alpha_s),
            )
            counts = self._counts(tx, key, lock=True)
            if counts is None:
                self._ensure_cell(tx, cell)
                counts = CellCounts(0, 0, CHAIN_GENESIS, None)
            if row is not None and int(row[1]) == counts.n:
                return str(row[0])
            if row is not None:
                raise LedgerError(f"sequence state of {key} at alpha {alpha_s} is out of step")
            cs = ConfidenceSequence(alpha=float(alpha))
            cs.extend(self._ys(tx, key))
            self._save_state(tx, key, alpha_s, cs, counts.obs_head, timeutil.iso(self.clock()))
            return cs_state.dumps(cs)

    def sequence(self, cell: RecallCell, alpha: float) -> ConfidenceSequence:
        """Resume the cell's confidence sequence at α from its stored state."""
        return cs_state.loads(self.state_json(cell, alpha))

    def upper(self, cell: RecallCell, alpha: float) -> float:
        return self.sequence(cell, alpha).upper

    def state_ref(self, cell: RecallCell, alpha: float) -> CsStateRef:
        text = self.state_json(cell, alpha)
        cs = cs_state.loads(text)
        return CsStateRef(ref=f"cs:{cell.key}|{alpha_key(alpha)}", sha=sha256_text(text), n=cs.n)

    def looks(self, cell: RecallCell) -> int:
        key = _key(cell)
        with self.backend.transaction() as tx:
            row = tx.fetchone(
                "SELECT COUNT(DISTINCT run_id) FROM recall_observation WHERE canonical_hash = ? AND stratum = ?"
                " AND series = ?",
                (key[0], key[1].value, key[2]),
            )
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------------------------------------ runs
    def record_run(
        self, run_id: str, study_id: str, ruleset: str, period: str, excluded: Mapping[RecallCell, int]
    ) -> None:
        """Excluded counts E_c of one run (SAFE-13: only real exclusions belong here)."""
        now = timeutil.iso(self.clock())
        with self.backend.transaction() as tx:
            for cell, e in sorted(excluded.items(), key=lambda kv: kv[0].key):
                self._ensure_cell(tx, cell)
                tx.execute(
                    "INSERT INTO recall_run_cell (run_id, study_id, ruleset, period, canonical_hash, stratum, series,"
                    " excluded, recorded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (run_id, canonical_hash, stratum, series) DO UPDATE SET excluded = excluded.excluded",
                    (run_id, study_id, ruleset, period, cell.canonical_hash, cell.stratum.value, cell.series, e, now),
                )

    def add_known_positive(
        self, line: KnownPositiveLineKind, population: str, draw_id: str, pid_hash: str, missed: bool
    ) -> bool:
        """Append a known positive to line H or B (1 = the cascade excluded it). Idempotent per ``draw_id``."""
        with self.backend.transaction() as tx:
            if tx.fetchone(
                "SELECT 1 FROM recall_known_positive WHERE line = ? AND population = ? AND draw_id = ?",
                (line.value, population, draw_id),
            ):
                return False
            row = tx.fetchone(
                "SELECT COALESCE(MAX(seq_no), 0) FROM recall_known_positive WHERE line = ? AND population = ?",
                (line.value, population),
            )
            seq = int(row[0]) + 1 if row else 1
            tx.execute(
                "INSERT INTO recall_known_positive (line, population, seq_no, draw_id, pid_hash, missed, observed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (line.value, population, seq, draw_id, pid_hash, int(missed), timeutil.iso(self.clock())),
            )
        return True

    def known_positive_outcomes(self, line: KnownPositiveLineKind, population: str) -> list[int]:
        with self.backend.transaction() as tx:
            rows = tx.fetchall(
                "SELECT missed FROM recall_known_positive WHERE line = ? AND population = ? ORDER BY seq_no",
                (line.value, population),
            )
        return [int(r[0]) for r in rows]

    def registration(
        self, study_id: str, ruleset: str, alpha: float, run_cells: Mapping[RecallCell, int]
    ) -> tuple[dict[str, float], str, int]:
        """The pre-registered allocation α_c = α · E_c/ΣE, frozen from the counts of the study's first certificate
        (weighted Bonferroni). Returns (allocation by cell key, registered_at, series)."""
        with self.backend.transaction() as tx:
            row = tx.fetchone(
                "SELECT alpha, allocation, registered_at, series FROM recall_registration WHERE study_id = ?"
                " AND ruleset = ?" + self.backend.row_lock,
                (study_id, ruleset),
            )
            if row is not None:
                if row[0] != alpha_key(alpha):
                    raise LedgerError(f"{study_id} {ruleset} is registered at alpha {row[0]}")
                return dict(json.loads(row[1])), str(row[2]), int(row[3])
            total = sum(run_cells.values())
            if total <= 0:
                raise LedgerError("cannot register a certificate without exclusions")
            alloc = {c.key: alpha * e / total for c, e in sorted(run_cells.items(), key=lambda kv: kv[0].key)}
            registered_at = timeutil.iso(self.clock())
            tx.execute(
                "INSERT INTO recall_registration (study_id, ruleset, series, alpha, allocation, registered_at)"
                " VALUES (?, ?, 1, ?, ?, ?)",
                (study_id, ruleset, alpha_key(alpha), canonical_json(alloc), registered_at),
            )
            return alloc, registered_at, 1

    def run_cells(self, run_id: str) -> tuple[str, str, str, dict[RecallCell, int]]:
        with self.backend.transaction() as tx:
            rows = tx.fetchall(
                "SELECT r.study_id, r.ruleset, r.period, r.canonical_hash, r.stratum, r.series, r.excluded,"
                " c.criterion_type FROM recall_run_cell r JOIN recall_cell c ON c.canonical_hash = r.canonical_hash"
                " AND c.stratum = r.stratum AND c.series = r.series WHERE r.run_id = ?"
                " ORDER BY r.canonical_hash, r.stratum, r.series",
                (run_id,),
            )
        if not rows:
            raise LedgerError(f"no exclusions recorded for run {run_id}")
        cells = {
            RecallCell(canonical_hash=r[3], stratum=Stratum(r[4]), series=int(r[5]), criterion_type=r[7]): int(r[6])
            for r in rows
        }
        return str(rows[0][0]), str(rows[0][1]), str(rows[0][2]), cells


# ---------------------------------------------------------------------------------------------------- certificate
def _line(
    ledger: RecallLedger, kind: KnownPositiveLineKind, population_key: str, population: str, alpha: float
) -> KnownPositiveLine:
    outcomes = ledger.known_positive_outcomes(kind, population_key)
    r, missed = len(outcomes), sum(outcomes)
    lower = 1.0 - ConfidenceSequence(alpha=alpha).extend(outcomes)
    biased = kind is KnownPositiveLineKind.HISTORICAL_ENROLLEES
    return KnownPositiveLine(
        line=kind,
        biased=biased,
        label=LINE_LABELS[kind].format(r=r),
        population=population,
        r=r,
        missed=missed,
        recall_lower=lower,
        method=CS_METHOD,
        recall_lower_single_look_info=cp_lower(r - missed, r, alpha) if biased and r else None,
    )


def render_certificate(
    ledger: RecallLedger,
    run_id: str,
    *,
    rc_id: str,
    populations: Mapping[KnownPositiveLineKind, tuple[str, str]],
    alpha: float = 0.05,
    seed: int | None = None,
    lineage_id: str | None = None,
) -> RecallCertificate:
    """Render the recall certificate of ``run_id`` from the ledger (SAFE-14, DM-16).

    ``populations`` maps each known-positive line to (ledger population key, human-readable population)."""
    study_id, ruleset, period, run_cells = ledger.run_cells(run_id)
    alloc, registered_at, series = ledger.registration(study_id, ruleset, alpha, run_cells)
    cells: list[CellBound] = []
    for cell, excluded in run_cells.items():
        if cell.key not in alloc:
            raise LedgerError(f"cell {cell.key} is not in the registered allocation; a new series is needed")
        a_c = alloc[cell.key]
        counts = ledger.counts(cell)
        ref = ledger.state_ref(cell, a_c)
        cells.append(
            CellBound(
                canonical_hash=cell.canonical_hash,
                stage=cell.stratum,
                series=cell.series,
                excluded=excluded,
                alpha_c=a_c,
                ledger_sampled=counts.n,
                found=counts.found,
                upper_cs=ledger.upper(cell, a_c),
                upper_cp_single_look=cp_upper(counts.found, counts.n, a_c),
                cs_state=ref,
                observation_seq_sha=counts.obs_head,
                looks=ledger.looks(cell),
                first_look=counts.first_look,
            )
        )
    strata: list[StratumBound] = []
    for stage in Stratum:
        cs_ = [c for c in cells if c.stage is stage]
        if not cs_:
            continue
        exc = sum(c.excluded for c in cs_)
        up = sum(c.excluded * c.upper_cs for c in cs_)
        strata.append(
            StratumBound(
                stage=stage,
                excluded=exc,
                ledger_sampled=sum(c.ledger_sampled for c in cs_),
                found=sum(c.found for c in cs_),
                missed_point=sum(c.excluded * (c.found / c.ledger_sampled if c.ledger_sampled else 0.0) for c in cs_),
                missed_upper=up,
                per_1000_excluded_upper=1000 * up / exc if exc else 0.0,
            )
        )
    excluded_total = sum(s.excluded for s in strata)
    missed_upper = sum(s.missed_upper for s in strata)
    line_h = _line(
        ledger,
        KnownPositiveLineKind.HISTORICAL_ENROLLEES,
        *populations[KnownPositiveLineKind.HISTORICAL_ENROLLEES],
        alpha,
    )
    line_b = _line(
        ledger,
        KnownPositiveLineKind.BLINDED_CHART_REVIEW,
        *populations[KnownPositiveLineKind.BLINDED_CHART_REVIEW],
        alpha,
    )
    quoted = line_b if line_b.r >= LINE_B_MIN_R else line_h
    per_1000 = 1000 * missed_upper / excluded_total if excluded_total else 0.0
    statement = (
        f"Recall is at least {quoted.recall_lower:.3f} ({quoted.label}; population: {quoted.population})."
        f" At most {per_1000:.1f} per 1,000 excluded patients may have been eligible (anytime-valid, alpha {alpha})."
    )
    if quoted is line_h:
        statement += f" Blinded chart review has r = {line_b.r} so far (quoted from r = {LINE_B_MIN_R})."
    return RecallCertificate(
        rc_id=rc_id,
        study_id=study_id,
        run_id=run_id,
        ruleset=ruleset,
        period=period,
        alpha=alpha,
        k_cells=len(alloc),
        series=series,
        registered_at=registered_at,
        method=(
            f"confidence sequence (WSR 2024 betting); alpha {alpha} allocated per cell in proportion to E_c,"
            f" pre-registered {registered_at[:7]}"
        ),
        cells=cells,
        strata=strata,
        missed_point=sum(s.missed_point for s in strata),
        missed_upper=missed_upper,
        per_1000_excluded_upper=per_1000,
        known_positive=(line_h, line_b),
        quoted_line=quoted.line,
        statement={"en": statement},
        seed=seed,
        lineage_id=lineage_id,
    )


__all__ = [
    "CHAIN_GENESIS",
    "SCHEMA",
    "CellCounts",
    "LedgerError",
    "RecallLedger",
    "alpha_key",
    "chain",
    "render_certificate",
]
