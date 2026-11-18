"""10D-1 (D-1223): a site's alliance count table is signed, and the merge verifies the signature.

D-144 says counts travel as signed files; the merge checked no signature and took a site's table from the mail
address that first sent one. Now the member box signs its table with its site key and the root stores a member's
table only when the signature holds for the key its register holds for that site, over this very table and its
scope, and only over an older table of the site. Every refusal names the site and never an address. A table stored
before this is kept, marked unverified, and left out of the merge until its site sends it signed. The keys are
made inside the test; the tables are synthetic."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import db as orch_db
from orchestrator.core import Orchestrator, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import cohort
from tb_common import alliance
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.crypto import ed25519_generate, sha256_bytes
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, JobFile, SendRequest, SendResult

from tests import alliance_keys

ROOT = Path(__file__).resolve().parents[2]
SENDER = "trialbox@hospb.test"  # the member box (alliance_sites in settings.example.yaml)
OWN = "DEMO-A"  # the root's own site in settings.example.yaml


def _table(site: str = "HOSP-B", n: int = 12, quarter: str = "2026Q3", version: str = "1.0.0") -> list[dict[str, Any]]:
    return [
        {"site_id": site, "disease": "gout", "quarter": quarter, "criterion_id": f"GOUT-COH-INC-0{i}",
         "criterion_label": "痛風の診断", "n": n + i, "n_contactable": "<5",
         "definition_version": f"GOUT-COH@{version}"}
        for i in (1, 2)
    ]  # fmt: skip


def _parsed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    got, errors = cohort.parse_csv(cohort.to_csv(rows))
    assert not errors
    return got


def _doc(rows: list[dict[str, Any]], seq: int = 1, private: bytes | None = None) -> dict[str, Any]:
    doc = alliance.read(alliance_keys.signature(rows, seq=seq, private=private))
    assert doc is not None
    return doc


@pytest.fixture
def register(tmp_path: Path) -> dict[str, dict[str, str]]:
    return alliance.load_register(alliance_keys.register(tmp_path, ["HOSP-B", "HOSP-C"]))


# ------------------------------------------------------------------------------------------- the signature itself
def test_a_good_table_verifies_with_its_site_key_sequence_and_hash(register: dict[str, dict[str, str]]) -> None:
    rows = _parsed(_table())
    ok = alliance.verify(rows, _doc(_table(), seq=7), register)
    assert (ok.site_id, ok.seq, ok.table_sha256) == ("HOSP-B", 7, alliance.table_sha256(rows))
    assert ok.key_sha256 == register["HOSP-B"]["key_sha256"]
    assert alliance.table_sha256(list(reversed(rows))) == ok.table_sha256  # the order of the rows is not in it
    assert alliance.table_sha256(rows) == orch_db.cohort_table_hash(rows)  # the store's record, the same formula


def test_what_is_signed_is_the_site_the_study_the_window_the_counts_and_the_sequence() -> None:
    doc = _doc(_table(), seq=42)
    body = json.loads(alliance.canonical(doc))
    assert body["site_id"] == "HOSP-B" and body["studies"] == ["GOUT-COH@1.0.0"] and body["diseases"] == ["gout"]
    assert body["quarters"] == ["2026Q3"] and body["seq"] == 42 and body["rows"] == 2
    assert body["table_sha256"] == alliance.table_sha256(_parsed(_table()))
    assert "signature" not in body and body["key_sha256"] and body["public_key"].startswith("-----BEGIN PUBLIC KEY")
    assert "PRIVATE" not in json.dumps(doc)


def _refused(rows: list[dict[str, Any]], doc: dict[str, Any] | None, register: Any) -> str:
    with pytest.raises(alliance.TableRefused) as ei:
        alliance.verify(_parsed(rows), doc, register)
    said = str(ei.value)
    assert "@" not in said and "hosp" not in said.replace("HOSP", "")  # D-555: the site, never an address
    return said


def test_an_unsigned_table_is_refused(register: dict[str, dict[str, str]]) -> None:
    assert "HOSP-B" in _refused(_table(), None, register) and "not signed" in _refused(_table(), None, register)


def test_a_wrongly_signed_table_is_refused(register: dict[str, dict[str, str]]) -> None:
    doc = _doc(_table())
    raw = bytearray(base64.b64decode(doc["signature"]["sig"]))
    raw[0] ^= 1
    doc["signature"]["sig"] = base64.b64encode(bytes(raw)).decode("ascii")
    assert "does not verify" in _refused(_table(), doc, register)
    doc = _doc(_table())
    doc["seq"] += 1  # a field changed after signing: the signature no longer holds
    assert "does not verify" in _refused(_table(), doc, register)


def test_a_changed_table_is_refused(register: dict[str, dict[str, str]]) -> None:
    doc = _doc(_table(n=12))
    assert "not the table its signature covers" in _refused(_table(n=13), doc, register)


def test_a_table_signed_by_a_key_not_registered_for_the_site_is_refused(register: dict[str, dict[str, str]]) -> None:
    other = ed25519_generate()[0]  # a good signature, by a key nobody registered
    assert "not the one registered" in _refused(_table(), _doc(_table(), private=other), register)
    # signed with another registered site's key
    c_key = alliance_keys.key("HOSP-C")
    assert "not the one registered" in _refused(_table(), _doc(_table(), private=c_key), register)


def test_a_site_not_in_the_register_and_a_root_without_one_are_refused(register: dict[str, dict[str, str]]) -> None:
    assert "no key in this alliance root's register" in _refused(_table("HOSP-D"), _doc(_table("HOSP-D")), register)
    assert "no readable register" in _refused(_table(), _doc(_table()), None)


def test_a_signature_for_another_study_window_or_site_is_refused(register: dict[str, dict[str, str]]) -> None:
    doc = _doc(_table(version="1.0.0"))
    assert "another study" in _refused(_table(version="1.1.0"), doc, register)
    assert "another study" in _refused(_table(quarter="2026Q2"), _doc(_table(quarter="2026Q3")), register)
    assert "another site" in _refused(_table("HOSP-B"), _doc(_table("HOSP-C")), register)


def test_a_file_that_is_not_a_signature_is_none() -> None:
    good = alliance_keys.signature(_table())
    assert alliance.read(good) is not None
    for bad in (b"", b"not json", b"[]", json.dumps({"schema": alliance.SCHEMA}).encode(), b"x" * 70_000):
        assert alliance.read(bad) is None
    doc = json.loads(good)
    doc["extra"] = 1
    assert alliance.read(json.dumps(doc).encode()) is None


def test_an_older_table_is_not_taken_over_a_newer_one() -> None:
    g = ("HOSP-B", "gout", "2026Q3", "GOUT-COH@1.0.0")
    assert alliance.stale_refusal("HOSP-B", 5, "h", {}) is None  # nothing signed stored yet
    assert alliance.stale_refusal("HOSP-B", 5, "h", {g: (None, None)}) is None  # stored unsigned: replaced
    assert alliance.stale_refusal("HOSP-B", 6, "h2", {g: (5, "h")}) is None  # newer
    assert alliance.stale_refusal("HOSP-B", 5, "h", {g: (5, "h")}) is None  # the same table again: no change
    said = alliance.stale_refusal("HOSP-B", 4, "h0", {g: (5, "h")})
    assert said is not None and "HOSP-B" in said and "not newer" in said
    assert alliance.stale_refusal("HOSP-B", 5, "other", {g: (5, "h")}) is not None  # two tables, one sequence


def test_the_member_box_signs_what_the_root_reads_and_a_re_run_signs_the_same_bytes(tmp_path: Path) -> None:
    key = alliance_keys.key_file(tmp_path / "alliance.key", "HOSP-B")
    at = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
    ctx: Any = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(extra={alliance.KEY_FILE: str(key)})),
        job=SimpleNamespace(received_at=at),
    )
    data = cohort.to_csv(_table())
    first, again = cohort.sign_table(ctx, data), cohort.sign_table(ctx, data)
    assert first is not None and first == again  # Ed25519 and the job's own time: a re-run gives the same file
    doc = alliance.read(first)
    assert doc is not None and doc["seq"] == alliance.seq_of(at)
    reg = alliance.load_register(alliance_keys.register(tmp_path / "r", ["HOSP-B"]))
    assert alliance.verify(_parsed(_table()), doc, reg).seq == alliance.seq_of(at)
    ctx.cfg.env.extra = {}
    assert cohort.sign_table(ctx, data) is None  # no key: no signature, and nothing is mailed to the root


# ------------------------------------------------------------------------------------------- the merge
class _Mail:
    def __init__(self) -> None:
        self.sent: list[SendRequest] = []

    def send(self, req: SendRequest) -> SendResult:
        self.sent.append(req)
        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=bool(req.encrypt))


class _Root:
    """The alliance root (settings.example.yaml: DEMO-A, alliance_root) with the real COHORT scenario."""

    n = 0

    def __init__(self, tmp_path: Path, schema: str | None = None, register: bool = True) -> None:
        _Root.n += 1
        folder = tmp_path / f"root{_Root.n}"
        environ = alliance_keys.env(folder / "keys", ["HOSP-B", "HOSP-C"]) if register else {}
        cfg = Config(
            env=load_env(dotenv=tmp_path / "x.env", environ=environ),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        assert cfg.settings.site.id == OWN and cfg.settings.cohort and cfg.settings.cohort.alliance_root
        self.mail = _Mail()
        self.db = JobDB(schema=schema or f"orch_sig_{_Root.n}")
        self.store = FsStore(tmp_path / "obj")
        services = Services(lake=None, parser=None, compiler=None, mail=self.mail, llm=None, verifier=None)  # type: ignore[arg-type]
        self.orch = Orchestrator(
            cfg, self.db, self.store, AuditLog(folder / "audit"), services, {"COHORT": cohort.run},
            folder / "rulesets", folder, today=lambda: date(2026, 11, 18), workers=0, async_notify=False,
        )  # fmt: skip

    def merge(self, files: list[tuple[str, bytes]], sender: str = SENDER) -> Any:
        jf = []
        for name, data in files:
            key = f"inputs/{_Root.n}-{len(self.db.find(type_='COHORT'))}/{name}"
            self.store.put(key, data)
            jf.append(JobFile(filename=name, sha256=sha256_bytes(data), minio_key=key))
        job_id = self.orch.create(
            JobCreate(type="COHORT", ruleset="MERGE", requested_by=sender, inputs=jf), notify=False
        ).job_id
        self.orch.run(job_id)
        return self.db.get(job_id)

    def held(self, site: str) -> list[dict[str, Any]]:
        return [r for r in self.db.cohort_rows("gout", "2026Q3") if r["site_id"] == site]

    def merged_csv(self, job: Any) -> str:
        return self.store.get(job.outputs[0].minio_key).decode("utf-8-sig")

    def body(self, job: Any) -> str:
        return next(m.body_md for m in reversed(self.mail.sent) if m.job_id == job.job_id)


def _signed(
    rows: list[dict[str, Any]], seq: int, name: str = "t", private: bytes | None = None
) -> list[tuple[str, bytes]]:
    return [(f"{name}.csv", cohort.to_csv(rows)), (f"{name}.sig.json", alliance_keys.signature(rows, seq, private))]


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Callable[..., _Root]]:
    made: list[_Root] = []

    def make(**kw: Any) -> _Root:
        made.append(_Root(tmp_path, **kw))
        return made[-1]

    yield make
    for r in made:
        r.db.drop()


def test_a_good_table_merges_and_is_stored_as_verified(root: Callable[..., _Root]) -> None:
    r = root()
    job = r.merge(_signed(_table("HOSP-B", n=12), seq=10) + _signed(_table("HOSP-C", n=20), seq=11, name="c"))
    assert job.state == "done", job.error
    data = r.merged_csv(job)
    assert "HOSP-B" in data and "HOSP-C" in data and "ALLIANCE,gout,2026Q3,GOUT-COH-INC-01" in data
    with r.db.tx() as tx:
        got = tx.fetchall("SELECT DISTINCT site_id, verified_by, signed_seq FROM cohort_tables ORDER BY site_id")
    fp = {
        s: e["key_sha256"]
        for s, e in alliance.load_register(Path(r.orch.cfg.env.extra[alliance.REGISTER_FILE])).items()
    }
    assert [tuple(x) for x in got] == [("HOSP-B", fp["HOSP-B"], 10), ("HOSP-C", fp["HOSP-C"], 11)]
    record = r.db.cohort_stored(job.job_id)
    assert [(x["site_id"], x["verified_by"], x["signed_seq"]) for x in record] == [
        ("HOSP-B", fp["HOSP-B"], 10),
        ("HOSP-C", fp["HOSP-C"], 11),
    ]


@pytest.mark.parametrize(
    "case, needle",
    [
        ("unsigned", "is not signed"),
        ("wrongly signed", "does not verify"),
        ("unregistered key", "not the one registered"),
        ("another study", "another study"),
        ("changed table", "not the table its signature covers"),
        ("unregistered site", "no key in this alliance root's register"),
        ("no register", "no readable register"),
    ],
)
def test_each_refusal_stores_nothing_and_names_the_site_never_an_address(
    case: str, needle: str, root: Callable[..., _Root]
) -> None:
    r = root(register=case != "no register")
    site = "HOSP-D" if case == "unregistered site" else "HOSP-B"
    rows = _table(site)
    files = _signed(rows, seq=5)
    if case == "unsigned":
        files = files[:1]
    elif case == "wrongly signed":
        doc = json.loads(files[1][1])
        doc["signature"]["sig"] = base64.b64encode(b"\0" * 64).decode()
        files[1] = (files[1][0], json.dumps(doc).encode())
    elif case == "unregistered key":
        files = _signed(rows, seq=5, private=ed25519_generate()[0])
    elif case == "another study":
        files = [files[0], ("t.sig.json", alliance_keys.signature(_table(site, version="2.0.0"), 5))]
    elif case == "changed table":
        files = [("t.csv", cohort.to_csv(_table(site, n=99))), files[1]]
    job = r.merge(files)
    assert job.state == "failed" and job.error is not None
    said = job.error.message
    assert needle in said and site in said, said
    assert "@" not in said and "hosp" not in said.replace("HOSP", "")
    assert r.db.cohort_stored_all() == [] and r.held(site) == []


def test_a_replayed_table_is_refused_and_a_corrected_newer_one_replaces_its_sites_rows_only(
    root: Callable[..., _Root],
) -> None:
    r = root()
    first = _signed(_table("HOSP-B", n=12), seq=100)
    assert r.merge(first + _signed(_table("HOSP-C", n=40), seq=100, name="c")).state == "done"
    corrected = r.merge(_signed(_table("HOSP-B", n=15), seq=200))
    assert corrected.state == "done", corrected.error
    assert {x["n"] for x in r.held("HOSP-B")} == {16, 17}  # the corrected counts
    assert {x["n"] for x in r.held("HOSP-C")} == {41, 42}  # another site's rows untouched
    replayed = r.merge(first)  # the first table, signature and all, sent again
    assert replayed.state == "failed" and replayed.error is not None
    assert "not newer" in replayed.error.message and "HOSP-B" in replayed.error.message
    assert "@" not in replayed.error.message
    assert {x["n"] for x in r.held("HOSP-B")} == {16, 17}
    older = r.merge(_signed(_table("HOSP-B", n=90), seq=150))  # signed between the two: still older
    assert older.state == "failed" and {x["n"] for x in r.held("HOSP-B")} == {16, 17}
    same = r.merge(_signed(_table("HOSP-B", n=15), seq=200))  # the very table that stands, again: nothing changes
    assert same.state == "done" and {x["n"] for x in r.held("HOSP-B")} == {16, 17}


def test_the_address_check_stays_beside_the_signature(root: Callable[..., _Root]) -> None:
    """D-648 item 7 is kept as an additional check: a site's signed table from another address is refused, and a
    table of the root's own site is never taken from mail. The proof of origin is the signature."""
    r = root()
    assert r.merge(_signed(_table("HOSP-B"), seq=1)).state == "done"
    other = r.merge(_signed(_table("HOSP-B", n=30), seq=2), sender="crc1@hospa.test")
    assert other.state == "failed" and "another address" in other.error.message and "@" not in other.error.message
    own = r.merge(_signed(_table(OWN), seq=3))
    assert own.state == "failed" and "own table" in own.error.message


def test_tables_stored_before_signatures_are_kept_unverified_and_left_out_until_re_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root updated in place: its member tables were stored unsigned. They are kept, marked unverified, and not
    merged; the merge says which sites. The root's own table, made in the box, stays verified. Once the site sends
    its table signed, it replaces the unverified one and is merged."""
    schema = "orch_sig_before"
    with monkeypatch.context() as mp:
        mp.setattr(orch_db, "MIGRATIONS", orch_db.MIGRATIONS[:5])
        old = _Root(tmp_path, schema=schema)
        with old.db.tx() as tx:  # as the release before stored them, table and record
            for job_id, sender, rows in (
                ("J-OLD-1", SENDER, _table("HOSP-B", n=12)),
                ("J-OLD-2", f"self:{OWN}", _table(OWN, n=50)),
            ):
                for x in rows:
                    tx.execute(
                        "INSERT INTO cohort_tables (site_id, disease, quarter, criterion_id, definition_version, "
                        "criterion_label, n, n_contactable, received_from, job_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (x["site_id"], x["disease"], x["quarter"], x["criterion_id"], x["definition_version"],
                         x["criterion_label"], json.dumps(x["n"]), json.dumps(x["n_contactable"]), sender, job_id),
                    )  # fmt: skip
                tx.execute(
                    "INSERT INTO cohort_stored (job_id, site_id, received_from, table_sha256, rows) VALUES (?,?,?,?,?)",
                    (job_id, rows[0]["site_id"], sender, orch_db.cohort_table_hash(rows), json.dumps(rows)),
                )
    new = _Root(tmp_path, schema=schema)
    try:
        with new.db.tx() as tx:
            got = tx.fetchall("SELECT DISTINCT site_id, verified_by FROM cohort_tables ORDER BY site_id")
            rec = tx.fetchall("SELECT site_id, verified_by FROM cohort_stored ORDER BY seq")
        assert [tuple(x) for x in got] == [(OWN, "own"), ("HOSP-B", None)]
        assert [tuple(x) for x in rec] == [("HOSP-B", None), (OWN, "own")]
        job = new.merge(_signed(_table("HOSP-C", n=20), seq=5))
        assert job.state == "done", job.error
        data = new.merged_csv(job)
        assert "HOSP-C" in data and OWN in data and "HOSP-B" not in data  # kept, not merged
        assert {x["n"] for x in new.held("HOSP-B")} == {13, 14}  # still in the store
        assert "Not merged: the tables of HOSP-B" in new.body(job) and "unverified" in new.body(job)
        again = new.merge(_signed(_table("HOSP-B", n=12), seq=6))  # the site sends it signed
        assert again.state == "done", again.error
        assert "HOSP-B" in new.merged_csv(again) and "Not merged" not in new.body(again)
    finally:
        new.db.drop()


def test_a_re_run_of_a_signed_merge_gives_what_its_first_run_gave(root: Callable[..., _Root], tmp_path: Path) -> None:
    """The record keeps how each table was verified, so the re-run's own store of the same signed table (same
    sequence, same hash) is taken, and a newer table stored after the merge read does not leak into it."""
    r = root()
    first = r.merge(_signed(_table("HOSP-B", n=12), seq=10) + _signed(_table("HOSP-C", n=20), seq=10, name="c"))
    assert first.state == "done"
    assert r.merge(_signed(_table("HOSP-B", n=70), seq=11)).state == "done"
    again = _Root(tmp_path, schema=f"{r.db.schema}_rerun")
    try:
        assert cohort.replay_stored(r.db, again.db, first.job_id) is True
        with again.db.tx() as tx:
            got = tx.fetchall("SELECT DISTINCT site_id, signed_seq FROM cohort_tables ORDER BY site_id")
        assert [tuple(x) for x in got] == [("HOSP-B", 10), ("HOSP-C", 10)]
        # the job as it was received, its inputs in the root's own store: copy them to the re-run's store
        for f in first.inputs:
            again.store.put(f.minio_key, r.store.get(f.minio_key))
        again.db.put(first.model_copy(update={"state": "received", "outputs": [], "error": None}), queued=False)
        second = again.orch.run(first.job_id)
        assert second.state == "done", second.error
        assert [(o.filename, o.sha256) for o in second.outputs or []] == [
            (o.filename, o.sha256) for o in first.outputs or []
        ]
    finally:
        again.db.drop()


# ------------------------------------------------------------------------------- the review of the first version
def _resigned(doc: dict[str, Any], private: bytes) -> dict[str, Any]:
    """``doc`` signed again with ``private``, every field as it is (what an attacker with their own key can do)."""
    from tb_common.crypto import ed25519_sign

    body = {k: v for k, v in doc.items() if k != "signature"}
    sig = base64.b64encode(ed25519_sign(private, alliance.canonical(body))).decode("ascii")
    return {**body, "signature": {"alg": "ed25519", "sig": sig}}


def test_a_key_that_claims_the_registered_fingerprint_is_refused(register: dict[str, dict[str, str]]) -> None:
    """The attacker signs with their own key and writes the registered fingerprint in the file: the signature holds
    for the key in the file, but that key's fingerprint is not the registered one."""
    from tb_common.crypto import ed25519_public_of

    attacker = ed25519_generate()[0]
    doc = _doc(_table())
    doc["public_key"] = ed25519_public_of(attacker).decode("ascii")
    forged = _resigned(doc, attacker)
    assert forged["key_sha256"] == register["HOSP-B"]["key_sha256"]
    assert "not the one registered" in _refused(_table(), forged, register)


def test_freshness_is_per_site_and_rule_set_across_versions_and_quarters(root: Callable[..., _Root]) -> None:
    """After a seq-20 table stood, an older table never delivered before (seq 5) of an older version of the rule
    set, or of an older quarter, is refused: it would otherwise be merged beside the newer one."""
    r = root()
    assert r.merge(_signed(_table("HOSP-B", version="1.1.0"), seq=20)).state == "done"
    for older in (_table("HOSP-B", version="1.0.0"), _table("HOSP-B", quarter="2026Q2", version="1.1.0")):
        job = r.merge(_signed(older, seq=5))
        assert job.state == "failed" and "not newer" in job.error.message, job.error
    with r.db.tx() as tx:
        got = tx.fetchall("SELECT DISTINCT definition_version, quarter FROM cohort_tables WHERE site_id='HOSP-B'")
    assert [tuple(x) for x in got] == [("GOUT-COH@1.1.0", "2026Q3")]
    # another rule set of the site has its own sequence; a newer table of the same rule set is taken
    other = [{**x, "definition_version": "RA-COH@1.0.0", "disease": "gout"} for x in _table("HOSP-B")]
    assert r.merge(_signed(other, seq=6, name="ra")).state == "done"
    assert r.merge(_signed(_table("HOSP-B", quarter="2026Q2", version="1.1.0"), seq=21)).state == "done"


def test_a_table_signed_by_a_key_no_longer_registered_is_kept_and_left_out(
    root: Callable[..., _Root], tmp_path: Path
) -> None:
    """Revocation reaches what is stored: after the site's register line is replaced, its tables signed with the
    old key are kept, not merged, and named in the summary; its next table under the new key is merged."""
    r = root()
    assert r.merge(_signed(_table("HOSP-B"), seq=1) + _signed(_table("HOSP-C"), seq=1, name="c")).state == "done"
    path = Path(r.orch.cfg.env.extra[alliance.REGISTER_FILE])
    reg = json.loads(path.read_text(encoding="utf-8"))
    new_key = ed25519_generate()[0]
    from tb_common.crypto import ed25519_public_of
    from tb_common.opportunity import key_fingerprint

    reg["sites"]["HOSP-B"]["key_sha256"] = key_fingerprint(ed25519_public_of(new_key))
    path.write_text(json.dumps(reg), encoding="utf-8")
    job = r.merge(_signed(_table("HOSP-C", n=30), seq=2, name="c"))
    assert job.state == "done", job.error
    assert "HOSP-B" not in r.merged_csv(job) and "HOSP-C" in r.merged_csv(job)
    assert len(r.held("HOSP-B")) == 2  # kept in the store
    body = r.body(job)
    assert "Not merged: the tables of HOSP-B" in body and "no longer the one registered" in body
    again = r.merge(_signed(_table("HOSP-B", n=40), seq=3, private=new_key))
    assert again.state == "done", again.error
    assert "HOSP-B" in r.merged_csv(again) and "no longer" not in r.body(again)


def test_the_signing_key_file_must_be_there_and_private(tmp_path: Path) -> None:
    key = alliance_keys.key_file(tmp_path / "k" / "site.key", "HOSP-B")
    assert alliance.signing_key({alliance.KEY_FILE: str(key)}) == alliance_keys.key("HOSP-B")
    assert alliance.signing_key({}) is None and alliance.signing_key({alliance.KEY_FILE: " "}) is None
    with pytest.raises(alliance.KeyFileRefused, match="not there"):
        alliance.signing_key({alliance.KEY_FILE: str(tmp_path / "missing.key")})
    for mode in (0o640, 0o604, 0o644):
        key.chmod(mode)
        with pytest.raises(alliance.KeyFileRefused, match="mode 600"):
            alliance.signing_key({alliance.KEY_FILE: str(key)})
    ctx: Any = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(extra={alliance.KEY_FILE: str(tmp_path / "missing.key")})),
        job=SimpleNamespace(received_at=datetime(2026, 10, 5, tzinfo=UTC)),
    )
    from orchestrator.clients import StepFailed

    with pytest.raises(StepFailed, match="cannot be used"):  # a named file that is missing stops the job
        cohort.sign_table(ctx, cohort.to_csv(_table()))


def test_keygen_makes_its_secret_files_mode_600_from_the_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from tools import opportunity_feed

    made: list[tuple[str, int]] = []
    real_open = os.open

    def watch(path: Any, flags: int, mode: int = 0o777, *a: Any, **kw: Any) -> int:
        made.append((Path(path).name, mode))
        return real_open(path, flags, mode, *a, **kw)

    out = tmp_path / "keys"
    out.mkdir()
    (out / "site.key").write_bytes(b"old")
    (out / "site.key").chmod(0o644)  # a file already there, readable by others
    monkeypatch.setattr(os, "open", watch)
    assert opportunity_feed.main(["keygen", "--out", str(out)]) == 0
    assert ("site.key", 0o600) in made and ("band.secret", 0o600) in made  # created with the mode, not chmod after
    for name in ("site.key", "band.secret"):
        assert (out / name).stat().st_mode & 0o777 == 0o600


def test_a_forged_second_signature_does_not_push_out_the_good_one(root: Callable[..., _Root]) -> None:
    """A second ``.sig.json`` with the same table hash and a higher sequence, by another key, is tried and fails;
    the good one still verifies and the table is taken with its own sequence."""
    r = root()
    rows = _table("HOSP-B")
    good = alliance_keys.signature(rows, seq=7)
    forged = json.loads(good)
    forged["seq"] = 9
    forged = _resigned(forged, ed25519_generate()[0])
    files = [("t.csv", cohort.to_csv(rows)), ("t.sig.json", good), ("x.sig.json", json.dumps(forged).encode())]
    job = r.merge(files)
    assert job.state == "done", job.error
    with r.db.tx() as tx:
        assert [tuple(x) for x in tx.fetchall("SELECT DISTINCT signed_seq FROM cohort_tables")] == [(7,)]


def test_a_signature_file_with_a_member_twice_or_an_unknown_member_is_not_one() -> None:
    good = alliance_keys.signature(_table()).decode("utf-8")
    assert alliance.read(good.encode()) is not None
    twice = good.replace('"seq":', '"seq": 1,\n "seq":', 1)
    assert twice != good and alliance.read(twice.encode()) is None
    doc = json.loads(good)
    doc["signature"]["kid"] = "x"
    assert alliance.read(json.dumps(doc).encode()) is None
