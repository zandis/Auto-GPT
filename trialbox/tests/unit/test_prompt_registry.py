"""The prompt registry (WS-02.3, D-201; T-101): prompts and output schemas are registry objects, resolved by
``(id, version)``; a changed text or schema is refused; PRODUCTION needs a qualification record; the gateway resolves
the prompt and its trace names ``prompt_id@version``."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from channels.base import ClassifiedIntent
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from matching.cascade.judge import AgreementJudge, JudgeReply
from tb_common.audit import AuditLog
from tb_common.llm import LlmClient, LlmError, load_prompt, render
from tb_common.policy.classes import Environment
from tb_contracts import inline_schema
from tb_llm import json_schema_format, prompt_registry
from tb_llm.prompt_registry import (
    BASELINE,
    BASELINE_COMMIT,
    PROMPTS_DIR,
    PromptRegistry,
    PromptRegistryError,
    schema_sha,
    sha256_bytes,
)
from tracestore.store import TraceStore

from tests.unit.test_gateway import JUDGE_VARS, H, _mock, _pinned_registry

TRIALBOX = Path(__file__).resolve().parents[2]
REPO = TRIALBOX.parent
ENTRIES = prompt_registry.default_registry().entries()


# ------------------------------------------------------------------------------------------------ the shipped registry
def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False)


@pytest.mark.req("LLM-20", "MOD-5")
@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.ref)
def test_moved_prompt_is_byte_identical_to_its_old_path(entry: prompt_registry.PromptEntry) -> None:
    """Acceptance (1): the texts were moved, not edited. The move's base is the commit the registry was created from
    (``BASELINE_COMMIT``, which was origin/master at the time); a clone without it (shallow CI) skips."""
    if (entry.id, entry.version, entry.sha256) not in BASELINE:
        pytest.skip("registered after the move: no old path")
    tree = _git("ls-tree", "-r", "--name-only", BASELINE_COMMIT, "--", "trialbox/services")
    if tree.returncode != 0:
        pytest.skip(f"{BASELINE_COMMIT} is not in this clone")
    (old,) = [p for p in tree.stdout.decode().split() if p.endswith(f"/prompts/{entry.file}")]
    before = _git("show", f"{BASELINE_COMMIT}:{old}")
    assert before.returncode == 0, before.stderr
    assert (PROMPTS_DIR / entry.file).read_bytes() == before.stdout, f"{entry.file} differs from {old}"
    assert sha256_bytes(before.stdout) == entry.sha256


@pytest.mark.req("LLM-20", "MOD-5")
def test_every_entry_resolves_and_every_prompt_file_is_registered() -> None:
    """Acceptance (2): a prompt file edited without a new registry entry fails here (and at load everywhere)."""
    reg = prompt_registry.default_registry()
    assert reg.problems("TEST") == [] and reg.problems("PRODUCTION") == []
    files = {p.name for p in PROMPTS_DIR.glob("*.md")}
    assert files == {e.file for e in ENTRIES}, "every prompt file is a registry entry and the reverse"
    assert not list((TRIALBOX / "services").glob("*/prompts/*.md")), "prompts live in libs/tb_llm/prompts only"
    for e in ENTRIES:
        p = load_prompt(f"{e.id}_v{e.version}")
        assert (p.meta.id, p.meta.version, p.meta.output_schema, p.sha256) == (e.id, e.version, e.schema, e.sha256)
    assert {(e.id, e.version, e.sha256) for e in ENTRIES} >= BASELINE


@pytest.mark.req("LLM-20", "MOD-5")
def test_code_defined_schema_is_pinned_too() -> None:
    assert {x.schema_ref for x in ENTRIES if x.schema_ref} == {"channels.base:ClassifiedIntent"}
    for x in ENTRIES:
        if x.schema_ref:
            assert x.schema_sha256 == schema_sha(ClassifiedIntent.model_json_schema()), x.ref
        else:
            assert x.schema is not None and x.schema_sha256 == schema_sha(inline_schema(x.schema)), x.ref


@pytest.mark.req("LLM-20", "MOD-5")
def test_active_set_is_the_newest_version_per_id() -> None:
    """Acceptance (4), the data side: the admin models page lists this (the page wiring is outside T-101)."""
    rows = prompt_registry.active_set()
    by = {r["id"]: r for r in rows}
    assert len(rows) == len(by) == len({e.id for e in ENTRIES})
    assert by["judge"]["ref"] == "judge@4" and by["ir_extract"]["version"] == 2
    assert by["judge"]["sha256"] == load_prompt("judge").sha256
    assert set(by["judge"]) >= {"sha256", "schema", "approved_by", "date", "qualification"}


# ------------------------------------------------------------------------------------------------ a private registry
def _copy(tmp_path: Path, *refs: str) -> Path:
    """A registry of the given shipped entries in ``tmp_path/prompts`` (files copied byte for byte)."""
    d = tmp_path / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in ENTRIES:
        if e.ref in refs:
            shutil.copy(PROMPTS_DIR / e.file, d / e.file)
            rows.append({k: v for k, v in e.__dict__.items()})
    (d / "registry.yaml").write_text(yaml.safe_dump({"version": "t", "prompts": rows}, sort_keys=False))
    return d / "registry.yaml"


def _bump(path: Path, new_version: int, *, qualification: Any = None, schema: str | None = "keep") -> str:
    """Register judge@<new_version>: judge_v4's text with the version changed and one sentence added."""
    d = path.parent
    text = (PROMPTS_DIR / "judge_v4.md").read_text(encoding="utf-8").replace("version: 4", f"version: {new_version}")
    data = yaml.safe_load(path.read_text())
    row = dict(next(r for r in data["prompts"] if r["id"] == "judge"))
    if schema is None:
        text = text.replace("output_schema: llm_judge_output\n", "output_schema: null\n")
        row.update(schema=None, schema_sha256=None)
    text += "\nA new sentence.\n"
    f = d / f"judge_v{new_version}.md"
    f.write_text(text, encoding="utf-8")
    row.update(version=new_version, file=f.name, sha256=sha256_bytes(f.read_bytes()), qualification=qualification)
    data["prompts"].append(row)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return text


@pytest.mark.req("LLM-20", "MOD-5")
def test_sha_mismatch_is_refused(tmp_path: Path) -> None:
    path = _copy(tmp_path, "judge@3", "judge@4")
    assert PromptRegistry.load(path).get("judge", 4).sha256 == load_prompt("judge_v4").sha256
    f = path.parent / "judge_v4.md"
    f.write_bytes(f.read_bytes().replace(b"quote", b"Quote", 1))  # one letter, same version
    reg = PromptRegistry.load(path)
    with pytest.raises(PromptRegistryError) as exc:
        reg.get("judge", 4, environment="DEV")  # refused in every environment, not only PRODUCTION
    assert exc.value.reason == "prompt_changed"
    with pytest.raises(PromptRegistryError):
        reg.get("judge")  # the active version is the changed one
    assert reg.get("judge", 3).ref == "judge@3"  # the other version is unaffected
    assert any("prompt_changed" in p for p in reg.problems("TEST"))


@pytest.mark.req("LLM-20", "MOD-5")
def test_unknown_id_or_version_is_refused(tmp_path: Path) -> None:
    reg = PromptRegistry.load(_copy(tmp_path, "judge@3", "judge@4"))
    for args in (("judge", 5), ("judge", 2), ("nope", None)):
        with pytest.raises(PromptRegistryError) as exc:
            reg.get(*args)
        assert exc.value.reason == "prompt_unknown"
    with pytest.raises(PromptRegistryError):
        reg.resolve_ref("judge@x")
    with pytest.raises(LlmError):
        load_prompt("judge_v99")


@pytest.mark.req("LLM-20", "MOD-5")
def test_changed_schema_is_refused(tmp_path: Path) -> None:
    """The quote check reads ``quote``/``quote_date`` of the judge's schema: the schema cannot change silently."""
    path = _copy(tmp_path, "judge@4")
    data = yaml.safe_load(path.read_text())
    data["prompts"][0]["schema_sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(PromptRegistryError) as exc:
        PromptRegistry.load(path).get("judge", 4)
    assert exc.value.reason == "prompt_schema_changed"


@pytest.mark.req("LLM-20", "MOD-5")
def test_front_matter_must_match_the_entry(tmp_path: Path) -> None:
    path = _copy(tmp_path, "judge@4")
    data = yaml.safe_load(path.read_text())
    data["prompts"][0]["version"] = 7  # an entry pointing at another version's file
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(PromptRegistryError) as exc:
        PromptRegistry.load(path).get("judge", 7)
    assert exc.value.reason == "registry_invalid"


@pytest.mark.req("LLM-20", "MOD-5")
def test_new_version_needs_a_qualification_record_in_production(tmp_path: Path) -> None:
    path = _copy(tmp_path, "judge@4")
    _bump(path, 5)  # qualification: null
    reg = PromptRegistry.load(path, root=tmp_path)
    assert reg.get("judge", environment="DEV").ref == "judge@5"  # DEV/VALIDATION may run it, to qualify it
    assert reg.get("judge", environment="VALIDATION").ref == "judge@5"
    with pytest.raises(PromptRegistryError) as exc:
        reg.get("judge", environment="PRODUCTION")
    assert exc.value.reason == "prompt_unqualified"
    assert reg.get("judge", 4, environment="PRODUCTION").ref == "judge@4"  # the baseline stays usable
    with pytest.raises(PromptRegistryError):
        reg.check("PRODUCTION")  # the start check

    # a new version cannot claim the baseline
    path2 = _copy(tmp_path / "b", "judge@4")
    _bump(path2, 5, qualification={"baseline": BASELINE_COMMIT})
    with pytest.raises(PromptRegistryError) as exc:
        PromptRegistry.load(path2).get("judge", 5, environment="PRODUCTION")
    assert exc.value.reason == "prompt_unqualified"

    # a record (provisional reference: path under trialbox/ + sha256) qualifies it; a changed record does not
    rec = tmp_path / "eval" / "qualification" / "judge-5.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"prompt": "judge@5", "result": "pass"}))
    path3 = _copy(tmp_path / "c", "judge@4")
    q = {"record": "eval/qualification/judge-5.json", "sha256": sha256_bytes(rec.read_bytes())}
    _bump(path3, 5, qualification=q)
    reg3 = PromptRegistry.load(path3, root=tmp_path)
    assert reg3.get("judge", environment="PRODUCTION").ref == "judge@5"
    rec.write_text(json.dumps({"prompt": "judge@5", "result": "fail"}))
    with pytest.raises(PromptRegistryError) as exc:
        PromptRegistry.load(path3, root=tmp_path).get("judge", environment="PRODUCTION")
    assert exc.value.reason == "prompt_unqualified"


@pytest.mark.req("LLM-20", "MOD-5")
def test_version_pinned_in_a_job_record_stays_after_a_registry_bump(tmp_path: Path) -> None:
    path = _copy(tmp_path, "judge@3", "judge@4")
    reg = PromptRegistry.load(path)
    job: dict[str, Any] = {"job_id": "J1", "judging": {"prompt": reg.get("judge").ref}}  # a job records judge@4
    before = reg.resolve_ref(job["judging"]["prompt"])
    _bump(path, 5)
    bumped = PromptRegistry.load(path)
    assert bumped.get("judge", environment="DEV").ref == "judge@5"  # new jobs get the new version
    again = bumped.resolve_ref(job["judging"]["prompt"])  # the old job keeps its own
    assert (again.ref, again.sha256, again.text) == (before.ref, before.sha256, before.text)
    assert load_prompt("judge_v4").sha256 == before.sha256


@pytest.mark.req("LLM-20", "MOD-5")
def test_prompt_without_schema_is_refused_for_patient_routes(tmp_path: Path) -> None:
    path = _copy(tmp_path, "judge@4")
    _bump(path, 5, schema=None)
    reg = PromptRegistry.load(path)
    assert reg.get("judge", 5).schema is None  # a public-data call may use it
    with pytest.raises(PromptRegistryError) as exc:
        reg.get("judge", 5, patient=True)
    assert exc.value.reason == "prompt_schema_missing"
    # and through the gateway: a D3 call naming it is refused before any route or model
    gw = _gw(tmp_path, prompts=reg)
    res = gw.chat(H(Data_Class="D3", Prompt="judge@5"), _body())
    assert res.status == 403 and res.body["error"]["code"] == "prompt_schema_missing", res.body


@pytest.mark.req("LLM-20", "MOD-5")
def test_registry_rejects_malformed_entries() -> None:
    good = next(e for e in ENTRIES if e.ref == "judge@4").__dict__
    for bad in (
        {**good, "sha256": "XYZ"},
        {**good, "qualification": {"baseline": BASELINE_COMMIT, "extra": 1}},
        {**good, "schema": None},  # a schema sha with no schema
        {k: v for k, v in good.items() if k != "approved_by"},
        {**good, "surprise": 1},
    ):
        with pytest.raises(PromptRegistryError) as exc:
            PromptRegistry({"prompts": [bad]}, PROMPTS_DIR)
        assert exc.value.reason == "registry_invalid"
    with pytest.raises(PromptRegistryError):
        PromptRegistry({"prompts": [good, good]}, PROMPTS_DIR)


# ------------------------------------------------------------------------------------------------ the gateway
def _gw(
    tmp_path: Path,
    *,
    prompts: PromptRegistry | None = None,
    env: Environment = Environment.TEST,
    traces: TraceStore | None = None,
    http: httpx.Client | None = None,
) -> Gateway:
    return Gateway(
        RoutingPolicy.load(),
        _pinned_registry(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=env),
        http=http or _mock("j-test"),
        guard=Guard("^\\d{8}$"),
        traces=traces,
        step_confirm=lambda caller, study, step: True,
        env={},
        prompts=prompts,
    )


def _body() -> dict[str, Any]:
    return {
        "messages": render(load_prompt("judge_v4"), JUDGE_VARS),
        "response_format": json_schema_format("judge", inline_schema("llm_judge_output")),
        "max_tokens": 512,
    }


@pytest.mark.req("LLM-20", "LLM-5")
def test_gateway_trace_names_prompt_id_at_version(tmp_path: Path) -> None:
    """Acceptance (3): the trace store line and the ledger name ``prompt_id@version`` (and its sha); the upstream
    request carries ``X-TB-Prompt-Version``."""
    seen: list[dict[str, str]] = []
    inner = _mock("j-test")

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.headers))
        return inner.post(str(req.url), content=req.content)

    traces = TraceStore(None, Guard("^\\d{8}$"))
    gw = _gw(
        tmp_path, env=Environment.PRODUCTION, traces=traces, http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    sha = load_prompt("judge_v4").sha256
    res = gw.chat(H(Data_Class="D3", Prompt="judge@4", Prompt_Sha=sha), _body())
    assert res.status == 200, res.body
    (body,) = [json.loads(str(r[0])) for r in traces.db.fetchall("SELECT body FROM traces")]
    assert body["attributes"]["tb.prompt"] == "judge@4"
    assert body["attributes"]["tb.prompt_registered"] is True
    assert seen[0]["x-tb-prompt-id"] == "judge" and seen[0]["x-tb-prompt-version"] == "4"
    assert seen[0]["x-tb-prompt-sha"] == sha
    rec = [json.loads(x) for f in (tmp_path / "audit").glob("*.jsonl") for x in f.read_text().splitlines()]
    (call,) = [r for r in rec if r["event"] == "llm.gateway.call"]
    assert call["prompt_version"] == "judge@4" and call["detail"]["prompt_sha"] == sha


@pytest.mark.req("LLM-20", "MOD-5")
@pytest.mark.parametrize(
    ("prompt", "extra", "code"),
    [
        ("judge@9", {}, "prompt_unknown"),
        ("judge", {}, "prompt_unknown"),  # a registered prompt is named with its version
        ("judge@4", {"Prompt_Sha": "0" * 64}, "prompt_changed"),
        ("judge@3", {"Prompt_Sha": "PLACEHOLDER"}, "prompt_changed"),  # v4's text sent as v3
    ],
)
def test_gateway_refuses_unknown_or_changed_prompt(
    tmp_path: Path, prompt: str, extra: dict[str, str], code: str
) -> None:
    if extra.get("Prompt_Sha") == "PLACEHOLDER":
        extra = {"Prompt_Sha": load_prompt("judge_v4").sha256}
    gw = _gw(tmp_path)
    res = gw.chat(H(Data_Class="D3", Prompt=prompt, **extra), _body())
    assert res.status == 403 and res.body["error"]["code"] == code, res.body


@pytest.mark.req("LLM-20", "MOD-5")
def test_gateway_refuses_another_schema_for_a_registered_prompt(tmp_path: Path) -> None:
    """The two-model rule and the quote check read the judge's schema fields: a caller cannot swap the schema."""
    body = _body()
    schema = json.loads(json.dumps(body["response_format"]["json_schema"]["schema"]))
    schema["properties"].pop("quote_date", None)
    body["response_format"] = json_schema_format("judge", schema)
    res = _gw(tmp_path).chat(H(Data_Class="D0", Prompt="judge@4"), body)
    assert res.status == 403 and res.body["error"]["code"] == "prompt_schema_changed", res.body


@pytest.mark.req("LLM-20", "MOD-5")
@pytest.mark.parametrize(
    ("env", "data_class", "ok"),
    [
        (Environment.TEST, "D3", True),  # synthetic data only in DEV/TEST (ENV_CEILING)
        (Environment.PRODUCTION, "D0", True),  # the public evaluation suites (mlbench_judge@1)
        (Environment.PRODUCTION, "D1", False),
        (Environment.PRODUCTION, "D3", False),
        (Environment.VALIDATION, "D2", False),
    ],
)
def test_gateway_unregistered_prompt(tmp_path: Path, env: Environment, data_class: str, ok: bool) -> None:
    gw = _gw(tmp_path, env=env)
    res = gw.chat(H(Data_Class=data_class, Prompt="mlbench_judge@1"), _body())
    if ok:
        assert res.body.get("error", {}).get("code") != "prompt_unregistered", res.body
    else:
        assert res.status == 403 and res.body["error"]["code"] == "prompt_unregistered", res.body


@pytest.mark.req("LLM-20", "MOD-5")
def test_gateway_start_in_production_refuses_a_changed_or_unqualified_prompt(tmp_path: Path) -> None:
    """Acceptance (2): editing a prompt without bumping the registry fails a start in PRODUCTION."""
    path = _copy(tmp_path, "judge@4")
    f = path.parent / "judge_v4.md"
    f.write_bytes(f.read_bytes() + b"\n")
    with pytest.raises(PromptRegistryError, match="prompt_changed"):
        _gw(tmp_path, prompts=PromptRegistry.load(path), env=Environment.PRODUCTION)
    _gw(tmp_path, prompts=PromptRegistry.load(path), env=Environment.TEST)  # a TEST box starts (and refuses use)
    path2 = _copy(tmp_path / "q", "judge@4")
    _bump(path2, 5)
    with pytest.raises(PromptRegistryError, match="prompt_unqualified"):
        _gw(tmp_path, prompts=PromptRegistry.load(path2), env=Environment.PRODUCTION)
    _gw(tmp_path, env=Environment.PRODUCTION)  # the shipped registry starts in PRODUCTION


@pytest.mark.req("LLM-20", "S1-06")
def test_v1_shim_sends_the_registered_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``tb_common.llm`` through the gateway: the labels carry ``judge@4`` and its sha; the gateway accepts them."""
    gw = _gw(tmp_path)
    sent: list[dict[str, str]] = []

    class Client:
        def complete(self, body: dict[str, Any], labels: Any) -> dict[str, Any]:
            h = labels.headers("orchestrator")
            sent.append(h)
            res = gw.chat({**h, "X-TB-Step": "s"}, body)
            assert res.status == 200, res.body
            return res.body

    c = LlmClient("http://unused", "m", gateway=Client())
    monkeypatch.setenv("TB_DATA_CLASS", "D0")
    r = c.chat_json("judge", JUDGE_VARS)
    assert sent[0]["X-TB-Prompt"] == "judge@4" and sent[0]["X-TB-Prompt-Sha"] == load_prompt("judge").sha256
    assert r.prompt_sha == load_prompt("judge").sha256


# ------------------------------------------------------------------------------------------------ the pair
@pytest.mark.req("LLM-20", "MOD-5")
def test_pair_never_agrees_across_two_prompt_texts() -> None:
    """The two-model rule: an agreement counts only when both models answered the same registered text."""

    class Fixed:
        def __init__(self, verdict: str, sha: str) -> None:
            self.reply = JudgeReply(verdict, 0.9, "q", "2026-10-01", "r", prompt="judge@4", prompt_sha=sha)

        def judge(self, **_: Any) -> JudgeReply:
            return self.reply

    kw: dict[str, Any] = {
        "criterion_text": "c",
        "note_question": "q",
        "index_date": date(2026, 10, 5),
        "excerpts": [],
        "study_id": "S",
        "data_class": "D0",
        "step_id": "s",
        "purpose": "screening",
    }
    sha = load_prompt("judge").sha256
    assert AgreementJudge(Fixed("fail", sha), Fixed("fail", sha)).judge(role="judge", **kw).verdict == "fail"
    pair = AgreementJudge(Fixed("fail", sha), Fixed("fail", "0" * 64))
    out = pair.judge(role="judge", **kw)
    assert out.verdict == "unknown" and pair.disagreements == 1
    other = AgreementJudge(Fixed("fail", sha), Fixed("fail", sha))
    other.verifier.reply = replace(other.verifier.reply, prompt="judge@3")
    assert other.judge(role="judge", **kw).verdict == "unknown"


@pytest.mark.req("LLM-20", "MOD-5")
def test_gateway_unpinned_prompt_only_for_its_context_of_use(tmp_path: Path) -> None:
    """``profile_summary@1`` (the D-148 cost bench, text in ``tools/bench_profile.py``) passes on an installed box
    for its own context of use only; another version or context is refused."""
    assert set(prompt_registry.default_registry().unpinned) == {"profile_summary@1"}
    gw = _gw(tmp_path, env=Environment.PRODUCTION)
    h = {"Data_Class": "D3", "Context_Of_Use": "patient_profile_summary"}
    ok = gw.chat(H(Prompt="profile_summary@1", **h), _body())
    assert ok.body.get("error", {}).get("code") not in ("prompt_unregistered",), ok.body
    for prompt, ctx in (("profile_summary@2", "patient_profile_summary"), ("profile_summary@1", "s3_note_judgement")):
        res = gw.chat(H(Prompt=prompt, Data_Class="D3", Context_Of_Use=ctx), _body())
        assert res.status == 403 and res.body["error"]["code"] == "prompt_unregistered", res.body
    with pytest.raises(PromptRegistryError):
        PromptRegistry(
            {"prompts": [], "unpinned": [{"ref": "x", "context_of_use": "c", "source": "s", "reason": "r"}]},
            PROMPTS_DIR,
        )
