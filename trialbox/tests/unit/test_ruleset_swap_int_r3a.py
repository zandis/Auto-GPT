"""INT-R3A (deep check of master 6c73db64, row R3 (a)): an approval swaps the rulesets' working copy whole.

``RulesetRepo.materialize`` removed the working copy of a ruleset and then renamed the new one in, so a reader that
met an approval read no folder, a folder going away, or half of one: in 200 rewrites the deep check counted 19,172
``FileNotFoundError`` and 19 partial loads. A partial load is a screening on half a ruleset.

* the writer builds the new copy beside the old, fsyncs it, and exchanges the two folders in one rename;
* the reader holds what it read against the approval tag's tree (the git hashes of every file) and refuses a read
  that differs with :class:`tb_common.ruleset.RulesetReadIncomplete`, never with a partial ruleset;
* a caller that runs a study gets that refusal, not "no approved version" and never a ruleset.
"""

from __future__ import annotations

import json
import multiprocessing
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from criteria_compiler import repo as repo_mod
from criteria_compiler.repo import RulesetRepo
from tb_common import ruleset as ruleset_mod
from tb_common.ruleset import approved_here, load_approved
from tb_contracts import ApproveRequest

import tests.unit.test_compiler_service as compiler_tests
from tests.rulesets_guard import RULESETS

RID = "NEUR-COH"
REWRITES = 200
env = compiler_tests.env  # the compiler fixture of the swap-probe test


class _Never(Exception):
    """Stands in for the typed refusal where the tree has none (master): nothing raises it."""


def _incomplete() -> type[BaseException]:
    return getattr(ruleset_mod, "RulesetReadIncomplete", _Never)


def _version_files(n: int) -> dict[str, bytes]:
    """Version 1.0.<n> of a small synthetic ruleset: every criterion's text names the version it belongs to, and
    an odd version has one criterion more, so a read that mixes two versions shows."""
    base = RULESETS / RID
    version = f"1.0.{n}"
    manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
    irs = sorted((base / "ir").glob("*.json"))
    if n % 2 == 0:
        irs = irs[:2]
    manifest.update(version=version, criteria=[p.stem for p in irs])
    files = {"manifest.yaml": yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode()}
    for p in irs:
        ir = json.loads(p.read_text(encoding="utf-8"))
        ir["text"] = f"{ir['text']} [{version}]"
        files[f"ir/{p.name}"] = json.dumps(ir, ensure_ascii=False, indent=1).encode()
    for p in sorted((base / "valuesets").glob("*.json")):
        files[f"valuesets/{p.name}"] = p.read_bytes()
    return files


def _approve(repo: RulesetRepo, n: int) -> None:
    """The approval's own steps (``CompilerService.approve``): the draft branch, the tag, the promotion."""
    branch = f"draft/job-{n}"
    repo.write_dir(branch, "main", f"{RID}/", _version_files(n), f"approve {RID} v1.0.{n}")
    tag = f"{RID}/v1.0.{n}"
    repo.tag(tag, branch, f"{tag} approved by tester@hospa.test", "tester@hospa.test")
    repo.promote(RID, tag, f"release {tag}", "tester@hospa.test")


def _box(tmp_path: Path) -> tuple[RulesetRepo, Path]:
    path = tmp_path / "rulesets"
    repo = RulesetRepo(path)
    _approve(repo, 1)
    return repo, path


def _on_disk(folder: Path) -> dict[str, bytes] | None:
    if not folder.is_dir():
        return None
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _whole(rs: Any) -> bool:
    """A loaded ruleset is one version: the criteria the manifest lists, each of the manifest's version."""
    ids = sorted(c.id for c in rs.criteria)
    return ids == sorted(rs.manifest.criteria) and all(c.text.endswith(f"[{rs.version}]") for c in rs.criteria)


# ---------------------------------------------------------------------------------------- writer and readers
def _reader(path: Path, started: Any, done: Any, out: Any) -> None:
    """One service reading the ruleset in a loop (its own process, as the orchestrator and the console are)."""
    counts = {"whole": 0, "refused": 0, "missing": 0, "partial": 0, "other": 0}
    seen: list[str] = []
    started.set()
    while not done.is_set():
        try:
            rs = load_approved(path, RID)
            key = "whole" if _whole(rs) else "partial"
        except _incomplete():
            key = "refused"
        except FileNotFoundError:
            key = "missing"
        except Exception as exc:  # anything else a reader met (a missing manifest says "not approved")
            key = "other"
            seen.append(f"{type(exc).__name__}: {exc}"[:160])
        counts[key] += 1
    out.put((counts, seen[:5]))


def test_readers_never_meet_a_missing_or_partial_ruleset_while_approvals_rewrite_it(tmp_path: Path) -> None:
    repo, path = _box(tmp_path)
    mp = multiprocessing.get_context("fork")
    done, out = mp.Event(), mp.Queue()
    readers = [(mp.Event(), i) for i in range(2)]
    procs = [mp.Process(target=_reader, args=(path, started, done, out)) for started, _ in readers]
    for p in procs:
        p.start()
    try:
        for started, _ in readers:
            assert started.wait(30)
        for n in range(2, REWRITES + 2):
            _approve(repo, n)
    finally:
        done.set()
        results = [out.get(timeout=60) for _ in procs]
        for p in procs:
            p.join(30)
    counts = {k: sum(c[k] for c, _ in results) for k in results[0][0]}
    seen = [s for _, ss in results for s in ss]
    print(f"{REWRITES} approvals, the readers' loads: {counts}")
    assert counts["whole"] > 0, counts
    assert (counts["missing"], counts["partial"], counts["other"]) == (0, 0, 0), (counts, seen[:5])
    assert _on_disk(path / RID) == _version_files(REWRITES + 1)


# ---------------------------------------------------------------------------------------- a kill at each step
_KILLABLE = {"os": ("write", "fsync", "rename", "replace"), "shutil": ("rmtree",)}


class _Kill(Exception):
    pass


class _Steps:
    """Counts the materialisation's file-system steps; raises :class:`_Kill` before or after step ``at``."""

    def __init__(self, at: int | None = None, after: bool = False) -> None:
        self.n, self.at, self.after = 0, at, after

    def wrap(self, fn: Any) -> Any:
        def step(*a: Any, **k: Any) -> Any:
            here = self.n
            self.n += 1
            if here == self.at and not self.after:
                raise _Kill(here)
            out = fn(*a, **k)
            if here == self.at and self.after:
                raise _Kill(here)
            return out

        return step


def _patch(monkeypatch: pytest.MonkeyPatch, steps: _Steps) -> None:
    for name, fns in _KILLABLE.items():
        real = getattr(repo_mod, name, None)
        if real is None:  # master's module has no os: its steps are shutil's and pathlib's
            continue
        proxy = SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if not k.startswith("__")})
        for fn in fns:
            setattr(proxy, fn, steps.wrap(getattr(real, fn)))
        monkeypatch.setattr(repo_mod, name, proxy)
    if hasattr(repo_mod, "_exchange"):
        monkeypatch.setattr(repo_mod, "_exchange", steps.wrap(repo_mod._exchange))


def _total_steps(tmp_path: Path) -> int:
    repo, _ = _box(tmp_path / "count")
    branch = "draft/count"
    repo.write_dir(branch, "main", f"{RID}/", _version_files(2), "v1.0.2")
    steps = _Steps()
    mp = pytest.MonkeyPatch()
    try:
        _patch(mp, steps)
        repo.promote(RID, branch, "release")
    finally:
        mp.undo()
    return steps.n


def test_a_kill_at_any_step_of_the_swap_leaves_the_whole_old_or_the_whole_new_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    total = _total_steps(tmp_path)
    assert total >= 2, total
    old, new = _version_files(1), _version_files(2)
    for at in range(total):
        for after in (False, True):
            repo, path = _box(tmp_path / f"k{at}{int(after)}")
            repo.write_dir("draft/k", "main", f"{RID}/", new, "v1.0.2")
            repo.tag(f"{RID}/v1.0.2", "draft/k", "approved by tester@hospa.test", "tester@hospa.test")
            with monkeypatch.context() as mp:
                _patch(mp, _Steps(at, after))
                with pytest.raises(_Kill):
                    repo.promote(RID, f"{RID}/v1.0.2", "release")
            where = f"kill {'after' if after else 'before'} step {at} of {total}"
            left = _on_disk(path / RID)
            assert left is not None, f"{where}: the working copy is missing"
            assert left in (old, new), f"{where}: the working copy is neither the old nor the new version"
            assert load_approved(path, RID).version in ("1.0.1", "1.0.2"), where
            RulesetRepo(path)  # the next start
            assert sorted(p.name for p in path.iterdir() if p.name != ".git") == [RID], where
            assert _on_disk(path / RID) == left, where
            repo.materialize(RID)
            assert _on_disk(path / RID) == new and load_approved(path, RID).version == "1.0.2", where


# ---------------------------------------------------------------------------------------- the reader's check
def _truncate(folder: Path) -> None:
    p = folder / "ir" / f"{RID}-INC-02.json"
    p.write_bytes(p.read_bytes()[:40])


def _change(folder: Path) -> None:
    p = folder / "valuesets" / "VS_MEMORY_CLINIC_VISIT.json"
    p.write_bytes(p.read_bytes().replace(b'"', b"'", 1))


def _drop(folder: Path) -> None:
    (folder / "ir" / f"{RID}-INC-03.json").unlink()


def _add(folder: Path) -> None:
    shutil.copy(folder / "ir" / f"{RID}-INC-03.json", folder / "ir" / f"{RID}-INC-04.json")


def _empty(folder: Path) -> None:
    (folder / "ir" / f"{RID}-INC-01.json").write_bytes(b"")


TAMPER = [_truncate, _change, _drop, _add, _empty]


@pytest.mark.parametrize("tamper", TAMPER, ids=lambda f: f.__name__.strip("_"))
def test_a_folder_that_differs_from_its_approval_is_refused_by_type(tmp_path: Path, tamper: Any) -> None:
    _, path = _box(tmp_path)
    assert _whole(load_approved(path, RID))
    tamper(path / RID)
    with pytest.raises(_incomplete()) as got:
        load_approved(path, RID)
    assert type(got.value).__name__ == "RulesetReadIncomplete"
    assert not isinstance(got.value, ruleset_mod.RulesetNotApproved)  # never "no approved version"


# ---------------------------------------------------------------------------------------- the callers
def test_no_caller_screens_on_a_refused_load(tmp_path: Path) -> None:
    from orchestrator.scenarios import feas
    from orchestrator.scenarios.review import approved_or_none

    _, path = _box(tmp_path)
    _drop(path / RID)
    calls: list[tuple[str, Any]] = []

    class Screened(Exception):
        pass

    def state(s: str) -> None:
        calls.append(("state", s))
        raise Screened(s)

    ctx = SimpleNamespace(
        rulesets_dir=path,
        job=SimpleNamespace(ruleset=RID, options={}, inputs=[], ruleset_version=None),
        today=lambda: __import__("datetime").date(2026, 11, 25),
        update=lambda **k: calls.append(("update", k)),
        state=state,
    )
    with pytest.raises(_incomplete()):
        feas.run(ctx)  # type: ignore[arg-type]
    assert calls == []  # the job never reached "running"
    with pytest.raises(_incomplete()):  # retention, calibration: a refusal, never "not approved" (None)
        approved_or_none(ctx, RID, None, run=False)  # type: ignore[arg-type]
    assert approved_here(path, RID) is False  # the timer starts no job for it; it asks again next time


def test_the_typed_refusal_is_its_own_type() -> None:
    cls = _incomplete()
    assert cls is not _Never and not issubclass(cls, (ruleset_mod.RulesetNotApproved, OSError, ValueError))


# ---------------------------------------------------------------------------------------- the integrator's rulings
def test_an_approval_where_the_folder_cannot_swap_is_refused_with_nothing_written(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """INTR3A-02: the approval wrote its commit and tag, then found the exchange unsupported. It is now probed
    before any write: refused by type (``CompileFailed`` from ``SwapUnsupported``), the repository as it was."""
    import errno

    from criteria_compiler.service import CompileFailed

    _approve, _compile, _decisions = compiler_tests._approve, compiler_tests._compile, compiler_tests._decisions

    res = _compile(env)
    _approve(env, _decisions(env["store"], res.review_xlsx_key))  # v1.0.0 stands: the next approval must exchange
    res = _compile(env)
    assert res.version != "1.0.0"
    repo: RulesetRepo = env["deps"].repo
    before = (repo.tags(), repo.ref("main"), _on_disk(repo.path / "GZQO"))
    assert res.branch
    draft = repo.ref(res.branch)
    assert before[2]

    def no_exchange(a: Path, b: Path) -> None:
        raise OSError(errno.EINVAL, "Invalid argument", str(b))

    monkeypatch.setattr(repo_mod, "_exchange", no_exchange, raising=False)
    with pytest.raises(CompileFailed) as got:
        env["comp"].approve(
            ApproveRequest(
                ruleset="GZQO",
                version=res.version,
                by="crc1@hospa.test",
                decisions=_decisions(env["store"], res.review_xlsx_key),
            )
        )
    assert got.value.step == "approve"
    assert type(got.value.__cause__).__name__ == "SwapUnsupported"
    assert (repo.tags(), repo.ref("main"), _on_disk(repo.path / "GZQO")) == before
    assert repo.ref(res.branch) == draft  # no commit on the draft's branch either
    assert sorted(p.name for p in repo.path.iterdir() if p.name.startswith(".") and p.name != ".git") == []


def test_list_rulesets_never_lists_a_dot_name(tmp_path: Path) -> None:
    """INTR3A-04: pathlib's glob matches hidden names, so ``.<ruleset>.tmp`` (a copy being built or swapped out)
    was listed as a ruleset while a materialisation ran."""
    from tb_common.ruleset import list_rulesets

    for name in ("RA-JAK", ".RA-JAK.tmp", ".swap-a.tmp"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "manifest.yaml").write_text("id: x\n", encoding="utf-8")
    assert list_rulesets(tmp_path) == ["RA-JAK"]


def test_an_offline_install_where_the_folder_cannot_swap_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import zipfile

    from criteria_compiler.import_ruleset import install

    repo, path = _box(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in _version_files(2).items():
            z.writestr(f"{RID}/{name}", data)
    before = (repo.tags(), repo.ref("main"), _on_disk(path / RID))

    def no_exchange(a: Path, b: Path) -> None:
        raise OSError(22, "Invalid argument", str(b))

    monkeypatch.setattr(repo_mod, "_exchange", no_exchange)
    with pytest.raises(Exception) as got:
        install(repo, buf.getvalue(), "tester")
    assert type(got.value).__name__ == "SwapUnsupported"
    assert (repo.tags(), repo.ref("main"), _on_disk(path / RID)) == before


def test_another_process_opening_the_repository_never_removes_a_copy_being_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The doctor and an install open the repository too: their clean-up must leave a running writer's copy."""
    repo, path = _box(tmp_path)
    real = repo_mod._exchange

    def opened_meanwhile(a: Path, b: Path) -> None:
        RulesetRepo(path)
        real(a, b)

    monkeypatch.setattr(repo_mod, "_exchange", opened_meanwhile)
    _approve(repo, 2)
    assert _on_disk(path / RID) == _version_files(2)
    assert not list(path.glob(".*.tmp"))


def test_one_damaged_ruleset_does_not_take_the_list_of_rulesets_down(tmp_path: Path) -> None:
    """A page that lists every ruleset goes on: the damaged one is shown as not approved, never as approved."""
    from console.backend import approval_state_of, criteria_of, ruleset_infos

    _, path = _box(tmp_path)
    _drop(path / RID)
    assert [(i.id, i.version, i.status) for i in ruleset_infos(path)] == [(RID, None, "draft")]
    assert criteria_of(path, RID) == [] and approval_state_of(path, RID) is None
