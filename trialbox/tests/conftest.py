from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

ROOT = Path(__file__).resolve().parents[1]

# D-315: the code has no default site zone; a box sets TB_TZ (deploy/.env, from site.tz). The tests run as the
# synthetic Taiwan demo site of .env.example unless a test sets another zone (monkeypatch) or removes it.
os.environ.setdefault("TB_TZ", "Asia/Taipei")
# D-539: on a box the lake service builds in a process of its own, which reads its lake and its embedder from the
# environment. Most tests hand the service a lake and an embedder in memory, which no other process can be given: for
# them the build stays a thread of the service. tests/unit/test_lake_build_process.py runs the box's way.
# Set, not defaulted: a shell that exports the box's value must not change what these tests drive.
os.environ["TB_LAKE_BUILD"] = "thread"
# D-663: the same for the adapter's ingest: most tests hand the adapter a configuration in memory (``build_config``
# replaced); tests/unit/test_adapter_run_process.py runs the box's way, with real processes.
os.environ["TB_ADAPTER_RUN"] = "thread"


@pytest.fixture
def repo_root() -> Path:
    return ROOT


# ------------------------------------------------------------------ the trial database (D-126)
# One throwaway PostgreSQL per test session (tools/pglocal.py), or the one in TB_TEST_DB_URL; every test gets its own
# schemas through a unique tb_prefix, so tests never see each other's rows.
_DB_COUNTER = iter(range(1, 10**9))


@pytest.fixture(scope="session")
def pg_cluster_url(request: pytest.FixtureRequest) -> Iterator[str]:
    given = os.environ.get("TB_TEST_DB_URL")
    if given:
        yield given
        return
    import atexit
    import tempfile

    from tools import pglocal

    # D-201: not under pytest's basetemp (as root the server runs as `postgres`, and pytest wipes the basetemp at
    # start), but under this branch's TB_TEST_ROOT, one cluster per xdist worker; without a test root a fresh
    # directory under the scratch root. Never a fixed /tmp path. The .owner file lets `python -m tools.pglocal --gc`
    # reap the cluster after a kill -9; atexit stops it when the session ends without its teardown.
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        _stop(request, exc)
    keep = os.environ.get("TB_TEST_PG_DIR")
    if keep:
        root = Path(keep)
    else:
        if os.environ.get("TB_TEST_ROOT"):
            root = pglocal.cluster_dir()
            if pglocal.owner_alive(root):
                owner = (root / ".owner").read_text().split()[0]
                raise pytest.UsageError(f"{root} belongs to running pid {owner}: give each parallel run its own "
                                        "TB_TEST_ROOT (RUNBOOK §13)")  # fmt: skip
            pglocal.remove(root)  # a cluster left by a killed run of this worker starts again empty
            root.mkdir(parents=True)
        else:
            pglocal.scratch_root().mkdir(parents=True, exist_ok=True)
            root = Path(tempfile.mkdtemp(prefix="tb-pgtest-", dir=pglocal.scratch_root()))
        pglocal.claim(root)
        me = os.getpid()  # a forked child that exits must not take the session's cluster with it
        atexit.register(lambda: pglocal.remove(root) if os.getpid() == me else None)
    root.chmod(0o755)
    try:
        url = pglocal.ensure(root)
    except (OSError, RuntimeError) as exc:
        _stop(request, exc)
    yield url
    if not keep:
        pglocal.remove(root)


def _stop(request: pytest.FixtureRequest, exc: BaseException) -> NoReturn:
    """ENG-028: when the cluster cannot start, the run stops after this test with one message (``shouldstop`` also
    stops every xdist worker), instead of one error per test."""
    msg = (
        f"the test PostgreSQL cluster cannot start ({str(exc)[-300:]}). Install the PostgreSQL server binaries "
        "(or set TB_PG_BIN), or give a server in TB_TEST_DB_URL; `make test-pure` runs the tests that need none"
    )
    request.session.shouldstop = msg
    pytest.fail(msg, pytrace=False)


@pytest.fixture
def db_url(pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A TB_DB_URL private to this test (also set in the environment for code that reads TB_DB_URL)."""
    sep = "&" if "?" in pg_cluster_url else "?"
    url = f"{pg_cluster_url}{sep}tb_prefix=t{os.getpid()}x{next(_DB_COUNTER)}_"
    monkeypatch.setenv("TB_DB_URL", url)
    return url


# ENG-028 (T-653): a pure test needs no PostgreSQL. A test marked ``nodb`` (or in a module of PURE_MODULES) gets a
# TB_DB_URL that refuses at once (port 1 on the loopback), so a test that does touch the database fails with a refused
# connection instead of starting a cluster; `make test-pure` runs only those tests, with no server binaries at all.
NODB_URL = "postgresql://127.0.0.1:1/tb_nodb?connect_timeout=1"
# T-653: every module here passed with the database refused (TB_PG_BIN pointing nowhere) on 2026-11-10.
PURE_MODULES: tuple[str, ...] = (
    "tests/console/test_console_timers.py",
    "tests/console/test_local_time.py",
    "tests/unit/test_acceptance.py",
    "tests/unit/test_agreement_judge.py",
    "tests/unit/test_audit_repair.py",
    "tests/unit/test_bakeoff.py",
    "tests/unit/test_cascade_excerpt_budget.py",
    "tests/unit/test_cascade_exclusion_rules.py",
    "tests/unit/test_cascade_lake_errors.py",
    "tests/unit/test_cascade_units.py",
    "tests/unit/test_catalogue_verify.py",
    "tests/unit/test_code_coverage.py",
    "tests/unit/test_cohort_unit.py",
    "tests/unit/test_config.py",
    "tests/unit/test_consent_unit.py",
    "tests/unit/test_cql_eval.py",
    "tests/unit/test_cql_sql_generators.py",
    "tests/unit/test_dataclass.py",
    "tests/unit/test_dates.py",
    "tests/unit/test_derived_definitions.py",
    "tests/unit/test_derived_phi.py",
    "tests/unit/test_derived_scores.py",
    "tests/unit/test_disclosure_linked.py",
    "tests/unit/test_doclint.py",
    "tests/unit/test_doctor_serving.py",
    "tests/unit/test_egress_rules.py",
    "tests/unit/test_encoding.py",
    "tests/unit/test_env_settings_gate.py",
    "tests/unit/test_eval_public_suites.py",
    "tests/unit/test_export_ledger.py",
    "tests/unit/test_extra_ca.py",
    "tests/unit/test_feas_profile.py",
    "tests/unit/test_feas_unit.py",
    "tests/unit/test_fhir_delta_load.py",
    "tests/unit/test_flatten_embed_generator.py",
    "tests/unit/test_gen_calendar.py",
    "tests/unit/test_gen_traceability.py",
    "tests/unit/test_gpu_sizing.py",
    "tests/unit/test_image_pins.py",
    "tests/unit/test_japan_icd10.py",
    "tests/unit/test_job_subject.py",
    "tests/unit/test_judge_bakeoff.py",
    "tests/unit/test_judge_schema_order.py",
    "tests/unit/test_lab_value_unknown.py",
    "tests/unit/test_labvalue.py",
    "tests/unit/test_language_hygiene.py",
    "tests/unit/test_log_scrubber_jp.py",
    "tests/unit/test_mapping_engine.py",
    "tests/unit/test_messy.py",
    "tests/unit/test_microbatch_note_block.py",
    "tests/unit/test_mimic_mapping.py",
    "tests/unit/test_mixed_and_polarity.py",
    "tests/unit/test_mlbench.py",
    "tests/unit/test_model_guard.py",
    "tests/unit/test_network_sheet.py",
    "tests/unit/test_no_direct_model_calls.py",
    "tests/unit/test_note_pair_disagreement.py",
    "tests/unit/test_onboarding_tools.py",
    "tests/unit/test_one_engine.py",
    "tests/unit/test_one_rule.py",
    "tests/unit/test_orchestrator_drain.py",
    "tests/unit/test_orchestrator_i18n.py",
    "tests/unit/test_parity_replay.py",
    "tests/unit/test_parser_terminology_review.py",
    "tests/unit/test_provider_pin.py",
    "tests/unit/test_public_validation.py",
    "tests/unit/test_quotes.py",
    "tests/unit/test_recall_cert.py",
    "tests/unit/test_registry_match_core.py",
    "tests/unit/test_registry_match_egress.py",
    "tests/unit/test_registry_match_harness.py",
    "tests/unit/test_routing_policy.py",
    "tests/unit/test_ruleset_drift.py",
    "tests/unit/test_ruleset_pins.py",
    "tests/unit/test_safety_properties.py",
    "tests/unit/test_screen_cascade.py",
    "tests/unit/test_screen_exclusion_pair.py",
    "tests/unit/test_screen_not_at_index.py",
    "tests/unit/test_serving_config.py",
    "tests/unit/test_site_today_misc.py",
    "tests/unit/test_site_tz.py",
    "tests/unit/test_smtp_sink.py",
    "tests/unit/test_step5_approval_roles_pack.py",
    "tests/unit/test_subject_routing.py",
    "tests/unit/test_suspected_diagnosis.py",
    "tests/unit/test_synth_hospital.py",
    "tests/unit/test_tb_llm_truncation.py",
    "tests/unit/test_test_hygiene.py",
    "tests/unit/test_test_shard.py",
    "tests/unit/test_textproc_sqlguard.py",
    "tests/unit/test_trialbox_doctor.py",
    "tests/unit/test_two_phase_strict.py",
    "tests/unit/test_ulid_crypto.py",
    "tests/unit/test_valueset_family.py",
    "tests/unit/test_verify_update_stdlib.py",
    "tests/unit/test_vllm_standin.py",
    "tests/unit/test_wording.py",
)


# D-635 (PG-LEAK): a test gives its database connections back. Set up first, so torn down last: every other fixture
# of the test has finished with its stores by then. tests/db_connections.py says why and what is left alone.
from tests.db_connections import TRACKER as _CONNECTIONS  # noqa: E402

_CONNECTIONS.install()


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef: Any, request: pytest.FixtureRequest) -> Iterator[None]:
    wide = fixturedef.scope != "function"
    if wide:
        _CONNECTIONS.wide(+1)
    try:
        yield
    finally:
        if wide:
            _CONNECTIONS.wide(-1)


@pytest.fixture(autouse=True)
def _connections_given_back() -> Iterator[None]:
    mark = _CONNECTIONS.mark()
    yield
    _CONNECTIONS.close_since(mark)


@pytest.fixture(autouse=True)
def _private_trial_db(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Every test runs with its own TB_DB_URL, so nothing it stores leaks into another test; a ``nodb`` test gets a
    URL that refuses, and no cluster is started for it."""
    if request.node.get_closest_marker("nodb") is not None:
        monkeypatch.setenv("TB_DB_URL", NODB_URL)
        return NODB_URL
    url: str = request.getfixturevalue("db_url")
    return url


@pytest.fixture(autouse=True)
def _keep_service_token() -> Iterator[None]:
    """``tools.role_demo.orch_client`` sets ``TB_SERVICE_TOKEN`` for its process (a demo box authenticates like a real
    console). A test that builds such a box must not leave it set: every later test of a service's HTTP surface would
    then expect a token (the 401s seen after tests/integration/test_list_demo.py in one run, D-146)."""
    # D-464: and the demo's token registry; T-717 (D-485): and the demo console's signing key
    names = ("TB_SERVICE_TOKEN", "TB_SERVICE_TOKENS", "TB_ACTOR_KEYS_FILE", "TB_ACTOR_SIGN_KEY_FILE")
    before = {n: os.environ.get(n) for n in names}
    yield
    for n, v in before.items():
        if v is None:
            os.environ.pop(n, None)
        else:
            os.environ[n] = v


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith(("TB_", "IMAP_", "SMTP_", "LLM_", "CLOUD_LLM", "MAIL_")) and key != "TB_DB_URL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TB_CANARY_GATE", "off")  # see pytest_configure
    yield


# ------------------------------------------------------------------ the committed rulesets are read-only (T-650c)
# A ruleset repository pointed at rulesets/ re-materialises it in place (``.<id>.tmp``, rmtree, rename) and breaks a
# parallel test copying the folder. Each test, and the whole session, must leave the folder exactly as it found it.
_RULESETS_AT_START: frozenset[tuple[str, int, int, int]] | None = None


@pytest.fixture(autouse=True)
def _rulesets_untouched() -> Iterator[None]:
    from tests.rulesets_guard import describe, snapshot

    before = snapshot()
    yield
    after = snapshot()
    if after != before:
        pytest.fail(
            "the committed rulesets/ folder changed during this test (or a parallel one): "
            f"{describe(before, after)}; write into tmp_path or a copy (tests.rulesets_guard.copy_rulesets)",
            pytrace=False,
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    global _RULESETS_AT_START
    if not hasattr(session.config, "workerinput"):  # the controller (or a run without xdist)
        from tests.rulesets_guard import snapshot

        _RULESETS_AT_START = snapshot()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _RULESETS_AT_START is None or hasattr(session.config, "workerinput"):
        return
    from tests.rulesets_guard import describe, snapshot

    after = snapshot()
    if after != _RULESETS_AT_START:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        msg = f"T-650c: the committed rulesets/ folder changed during the test session: {describe(_RULESETS_AT_START, after)}"
        if tr is not None:
            tr.write_line(msg, red=True)
        else:
            print(msg)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_addoption(parser: pytest.Parser) -> None:
    g = parser.getgroup("trialbox shards (T-747, D-475)")
    g.addoption("--shard", default=None, metavar="I/N",
                help="run only the test files of shard I of N (tools/test_shard.py: a hash of the file path)")  # fmt: skip
    g.addoption("--shard-record", default=None, metavar="PATH",
                help="write the full collection and the shard's node ids to PATH, for `tools.test_shard check`")  # fmt: skip


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--shard", None):  # T-747: after every other selection (-m, -k), only this shard's files
        from tools import test_shard

        try:
            shard = test_shard.parse(config.getoption("--shard"))
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        config.pluginmanager.register(test_shard.ShardPlugin(shard, config.getoption("--shard-record")), "tb-shard")
    config.addinivalue_line("markers", "req(*ids): spec v4 requirement ids this test verifies (§17.4)")
    config.addinivalue_line("markers", "nodb: a pure test: no PostgreSQL is started for it (TB_DB_URL refuses); "
                            "`make test-pure` runs these alone (T-653)")  # fmt: skip
    # D-117: on a box the pair canary gates note exclusions (on unless TB_ENV is DEV or TEST). The suite's stub and
    # fake models are not the pair and never pass a canary, so the gate is off for the suite; the gate's own tests
    # (tests/unit/test_canary_gate.py) switch it on with monkeypatch.
    os.environ.setdefault("TB_CANARY_GATE", "off")
    # D-127 (F-06): an unset TB_ENV now means PRODUCTION (token required, timers on). The suite is a TEST box; the
    # tests of the PRODUCTION default set or clear TB_ENV themselves.
    os.environ.setdefault("TB_ENV", "TEST")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    from tb_testkit.req import unknown_ids

    bad = sorted({i for item in items for m in item.iter_markers("req") for i in unknown_ids(list(m.args))})
    if bad:
        raise pytest.UsageError(f"@pytest.mark.req names unknown spec v4 requirement ids: {', '.join(bad)}")
    _mark_pure_modules(items)
    egress = pytest.mark.skip(reason="host egress test: run `make test-egress` as root with the stack up")
    for item in items:
        if item.get_closest_marker("egress") and os.environ.get("TB_EGRESS_TEST") != "1":
            item.add_marker(egress)
    if os.environ.get("TB_INTEGRATION") == "1":
        _skip_compose_tests_without_a_stack(items)
        return
    skip = pytest.mark.skip(reason="needs compose services (set TB_INTEGRATION=1, run `make up-test`)")
    for item in items:
        if item.get_closest_marker("integration") or item.get_closest_marker("e2e"):
            item.add_marker(skip)


def _mark_pure_modules(items: list[pytest.Item]) -> None:
    """The modules of PURE_MODULES are ``nodb`` as a whole; a listed module that no longer exists is an error, so the
    list cannot rot silently."""
    missing = [m for m in PURE_MODULES if not (ROOT / m).is_file()]
    if missing:
        raise pytest.UsageError(f"tests/conftest.py PURE_MODULES lists missing files: {', '.join(missing)}")
    pure = {str(ROOT / m) for m in PURE_MODULES}
    for item in items:
        if str(item.path) in pure:
            item.add_marker(pytest.mark.nodb)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """TB_STRICT_SKIPS=1 (the nightly compose job): a skipped test fails, with its reason. A nightly job that selects
    the compose tests must run them; a missing stack, browser or jar must not turn the job green by skipping."""
    rep = yield
    if os.environ.get("TB_STRICT_SKIPS") == "1" and rep.skipped and not hasattr(rep, "wasxfail"):
        reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)
        rep.outcome = "failed"
        rep.longrepr = f"skipped under TB_STRICT_SKIPS=1, which allows no skip: {reason}"
    return rep


def _stack_up() -> bool:
    """The compose test stack answers on the lake's host port (tests/stack.py)."""
    import socket

    from tests.stack import host_port

    try:
        with socket.create_connection(("127.0.0.1", host_port("LAKE")), timeout=1):
            return True
    except OSError:
        return False


def _skip_compose_tests_without_a_stack(items: list[pytest.Item]) -> None:
    """``TB_INTEGRATION=1`` runs the in-process integration tests anywhere; the ``*compose*`` ones need `make
    up-test`, so without a running stack they are skipped by name instead of erroring on a refused connection."""
    compose = [i for i in items if "compose" in Path(str(i.fspath)).name and i.get_closest_marker("integration")]
    if compose and not _stack_up():
        mark = pytest.mark.skip(reason="compose test stack not running (`make up-test`)")
        for item in compose:
            item.add_marker(mark)


# ----------------------------------------------------------------------------- synthetic data fixtures
REF_DATE = "2026-10-05"
SNAPSHOT = "2026-10-04"


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tools.make_fixtures import main as make_fixtures

    out = tmp_path_factory.mktemp("synth")
    assert make_fixtures(["--out", str(out), "--sites", "ab"]) == 0
    return out


@pytest.fixture(scope="session")
def site_key_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("secrets")
    (d / "site_hmac.key").write_bytes(b"trialbox-test-site-key-0123456789abcdef")
    (d / "site_hmac.key").chmod(0o600)
    return d


@pytest.fixture(scope="session")
def ingested(
    synth_dir: Path, site_key_dir: Path, tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str
) -> dict[str, object]:
    """Site A ingested in-process (csv source) into a lake with the hash embedder. The pid map goes to the session's
    own schemas (``cfg.db_url``): a session fixture runs before any test's private ``TB_DB_URL``."""
    from adapter.pipeline import AdapterConfig, run_ingest
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_contracts import RebuildResult

    lake_dir = tmp_path_factory.mktemp("lake")

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(lake_dir).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=st.snapshot,
            tables=st.tables,
            chunks=st.chunks,
            embedded_new=st.embedded_new,
            seconds=st.seconds,
        )

    cfg = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=site_key_dir,
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id="DEMO-A",
        audit_dir=lake_dir / "audit",
        rebuild=rebuild,
        db_url=f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=s{os.getpid()}ingested_",
    )
    report = run_ingest(cfg, "csv", str(synth_dir / "site-a"), snapshot=SNAPSHOT, load_fhir=False)
    return {
        "lake_dir": lake_dir,
        "report": report,
        "cfg": cfg,
        "key": (site_key_dir / "site_hmac.key").read_bytes(),
    }


@pytest.fixture
def orch_box(synth_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """T-714 (D-482): the real orchestrator app in the production trust configuration, with the console's real
    backend bound to it (``tests/orch_box.py``). A fresh box per test."""
    from tests.orch_box import build

    return build(tmp_path / "orch-box", synth_dir, monkeypatch)
