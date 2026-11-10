"""The prompt registry (WS-02.3, D-201): every prompt TrialBox sends is a registry object, resolved by (id, version).

``libs/tb_llm/prompts/registry.yaml`` lists one entry per prompt version::

    - id: judge                 # the prompt id (the ``X-TB-Prompt`` header names ``id@version``)
      version: 4
      file: judge_v4.md         # in ``libs/tb_llm/prompts/`` (or one of EXTERNAL_FILES, a path under trialbox/)
      sha256: 17db…             # of the file's bytes: a text that differs is refused at load
      schema: llm_judge_output  # the output schema (``schemas/<name>.schema.json``, or ``schema_ref``)
      schema_ref: null          # ``module:attr`` when the schema is a pydantic model or a dict in code
      schema_sha256: 5285…      # of the canonical self-contained schema the caller sends (``schema_sha``)
      approved_by: …
      date: 2026-11-05
      qualification: {record: libs/tb_llm/prompts/qualification/<file>.json, sha256: …}  # or {baseline: <commit>}

Rules (each refusal is a :class:`PromptRegistryError` with a stable ``reason``):

* ``get(id, version=None)`` returns the text, the schema and the sha; ``version=None`` is the newest registered
  version (the active one); an id or version the registry does not list is refused (``prompt_unknown``);
* the file's sha256 must equal the registry's (``prompt_changed``), and its front matter must name the same id,
  version and output schema (``registry_invalid``);
* the schema is re-hashed at load, a file schema through ``tb_contracts.inline_schema`` and a ``schema_ref`` by
  importing it, and must equal ``schema_sha256`` (``prompt_schema_changed``);
* in PRODUCTION (``TB_ENV``) an entry needs a qualification that holds (``prompt_unqualified``): either the frozen
  baseline (:data:`BASELINE`: the exact id, version, text sha and schema sha in service when the registry was made)
  or a record (provisional until T-012's record schema): a JSON file under ``libs/tb_llm/prompts/qualification/``
  (inside the image) with that file's sha256 in the entry, naming ``prompt`` (``id@version``), ``sha256`` and
  ``schema_sha256`` equal to the entry's;
* a prompt with no schema is refused for a patient route (data class D2, D3 or D4: ``prompt_schema_missing``);
* a template may use ``{{ … }}`` expressions only (no ``{% … %}`` blocks), so :meth:`PromptRegistry.check_messages`
  can tell whether sent messages are this template rendered: the literal text between the expressions must appear
  exactly, in order, with the first literal at the start and the last at the end of the message.

A version named in a job record (``id@version``, :func:`resolve_ref`) keeps resolving to that text after a newer
version is registered. :func:`active_set` is the admin page's list (one entry per id, the newest).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
REGISTRY_PATH = PROMPTS_DIR / "registry.yaml"
TRIALBOX = Path(__file__).resolve().parents[2]  # external files and qualification records are relative to trialbox/
QUALIFICATION_DIR = "libs/tb_llm/prompts/qualification"  # in the python image (deploy/docker/python.Dockerfile)
PATIENT_CLASSES = frozenset({"D2", "D3", "D4"})
_FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_SECTION = re.compile(r"^##\s+(system|user)\s*$", re.M)
_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
_HEX = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"[1-9][0-9]*")
# the one follow-up turn tb_common.llm.LlmClient adds after an out-of-schema answer (assistant, then this user text)
_CORRECTION = re.compile(r"Your previous output violated the JSON schema: .*\. Return only corrected JSON\.", re.S)

# A closed list of prompt files that stay outside libs/tb_llm/prompts/ because their folder is owned by another task
# right now (registered by reference, sha-pinned like the rest). Move them here when their owner is free.
EXTERNAL_FILES: frozenset[str] = frozenset({"services/edc/prompts/crf_prefill_v1.md"})

# The prompts in service when the registry was created, run before any qualification record existed. Only these
# exact (id, version, text sha256, schema sha256) tuples may carry ``qualification: {baseline: <commit>}`` with the
# commit given here; anything new, or any change to text or schema, needs a record.
#   6e11e25: the 14 prompt files moved byte for byte from services/*/prompts/ (T-101);
#   0cc908b: crf_prefill (services/edc, PR #56) and profile_summary (the D-148 cost bench, whose text was code in
#            tools/bench_profile.py; the registered template renders the same messages, held by the test).
BASELINE: dict[tuple[str, int, str, str], str] = {
    ("assist", 1, "6fecaff99607e9d4b67427696a6e9a78aca433ce60bf611ca510468d99e5d9c2",
     "5c084c0cffe5c99aaabb89063ef69cc4758331bae9fdbb9cbd96211b77ffb54d"): "6e11e25",
    ("chart_facts", 1, "9fc73194a8897d00f4f7e8e8af2f4339d311f53bb61dce58418a04bf24be773a",
     "8babbb594cc162c234cca409175945bb578f03b3e5b90b1c96c46b17cf5d34df"): "6e11e25",
    ("classify_intent", 1, "6d93975458b1d455ec79e4ea55c85bd15a0499b0fcf04526d5a631c1905e391f",
     "f65ac4efeff71bca478e0219cfba44a439566b722dae5024638aea2de4b99afb"): "6e11e25",
    ("classify_intent", 2, "bb17b158d9d58f4623ef753730926fcbf208a2eeaea7707ace0f864762d9ffb2",
     "f65ac4efeff71bca478e0219cfba44a439566b722dae5024638aea2de4b99afb"): "6e11e25",
    ("concept_map", 1, "6721408d8227a4d6d55c4d917472ca67a8063a99d2986e8a8a3a1a6444a14006",
     "6d27c256ed1c80505424526980e5c8ed3460c4d628f565b29a6f4c989f0fccdb"): "6e11e25",
    ("consent_explain", 1, "4f5b90c56b2371094236a6210468976ef46d734614bbfa87f8c649d7360f6998",
     "6443174dd6eebe4634c3608462bf55270e67f09fde99fd962a82d899738c739d"): "6e11e25",
    ("consent_translate", 1, "8aab2417dd60215e6b27ece9b82044f15949cbd24ef8d5b82d1b2525b8e0fe98",
     "8d1b1ce771d0ec042e64b1c82dfe544bf3e19c5d0f15051af127af8636d4d25b"): "6e11e25",
    ("consent_verify", 1, "a2c68131275bc97e313a34da886370398d0665f603dbd74c5ea84e2f57239b1e",
     "488787d41cbcf97b7c78d99e3b3b237f097de5473f5ff6fb67b400da7260d9a7"): "6e11e25",
    ("draft_doc", 1, "2c9bc8a9d7c0bb1b62d5a89066e2ea8ad696b739bc8cc95b22f8844efd45ff1d",
     "0ca0f27295ea9a22e5eb88ba437f3484ad7b3c80b7f9c80b6033df6892ca7312"): "6e11e25",
    ("ie_locate", 1, "bbff3a9fdf3bb3dc7cb633f5b443abab0336d5f5f81d3669da482c814d78f5a1",
     "7f69f64788b1aea0ed11ce10b340f094f2c6bc3a0f79cd3697a29b430d307188"): "6e11e25",
    ("ir_extract", 1, "a30c810c6998340b0b162f92c8ebd5899b565346f54ee006ccf3599613b8fcb5",
     "627c08da7bb5a53c96219c897a49fbd99dd218fd718074242277889a853fc671"): "6e11e25",
    ("ir_extract", 2, "bec957be30fc46ab47aafeae5e2666ce187dbfcf4d2d949f00855953abf34674",
     "627c08da7bb5a53c96219c897a49fbd99dd218fd718074242277889a853fc671"): "6e11e25",
    ("judge", 3, "bfbae7066925ea1de94f4163dd686f0bea3c483f5d48db5c03518d1c52111017",
     "5285acc3d211de370bca9f8b0f8125b31bd41b6a70ce10c0c275f5e0148e21ed"): "6e11e25",
    ("judge", 4, "17db3b50b3f874a2e7253c806942739170f8f7a947d4548aed8e9eafa4cdef6e",
     "5285acc3d211de370bca9f8b0f8125b31bd41b6a70ce10c0c275f5e0148e21ed"): "6e11e25",
    ("crf_prefill", 1, "7082eeeeec626c0059b1c97167000f4360bfaa3f5063eb5e8ef01c230d34c7a3",
     "66040684f002e167efcae7e78df07639561c4c7a7d3f15fe66e50c0586ad1880"): "0cc908b",
    ("profile_summary", 1, "64ee45f776b57812715ac2ea17f53c54c37949491888de4287fc31826524d921",
     "ddf7234ad8507e6db7aeb554128c6133db65de9ecdb33dcbd27720bdfb594f26"): "0cc908b",
}  # fmt: skip


class PromptRegistryError(RuntimeError):
    """A refused prompt; ``reason`` is the stable code the gateway answers with."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class _UniqueKeyLoader(yaml.SafeLoader):
    """``yaml.safe_load`` that refuses a key given twice in one mapping (the second would silently win)."""


def _no_duplicates(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    dup = sorted({str(k) for k in keys if keys.count(k) > 1})
    if dup:
        raise PromptRegistryError("registry_invalid", f"duplicate key(s) {dup} at line {node.start_mark.line + 1}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - a SafeLoader subclass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def schema_sha(schema: Any) -> str:
    """sha256 of a JSON schema in canonical form (sorted keys, no whitespace): the same value whether the registry
    hashes the schema it knows or the gateway hashes the ``response_format`` a caller sent."""
    return sha256_bytes(json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


@lru_cache(maxsize=64)
def file_schema_sha(name: str) -> str | None:
    """``schema_sha`` of ``schemas/<name>.schema.json`` made self-contained, or None when no such file exists."""
    from tb_contracts import SCHEMAS_DIR, inline_schema

    if not (SCHEMAS_DIR / f"{name}.schema.json").is_file():
        return None
    return schema_sha(inline_schema(name))


def ref_schema(ref: str) -> Any:
    """The schema a ``schema_ref`` (``module:attr``) names: a pydantic model's ``model_json_schema()`` or a dict."""
    mod, _, attr = ref.partition(":")
    obj = getattr(importlib.import_module(mod), attr)
    return obj.model_json_schema() if hasattr(obj, "model_json_schema") else obj


def parse_ref(ref: str) -> tuple[str, int | None]:
    """``judge@4`` -> ``("judge", 4)``; ``judge`` -> ``("judge", None)``. A version is ``[1-9][0-9]*`` or refused."""
    pid, sep, ver = ref.strip().partition("@")
    if not sep:
        return pid, None
    if not _VERSION.fullmatch(ver):
        raise PromptRegistryError("prompt_unknown", f"prompt reference {ref!r}: the version must be a number")
    return pid, int(ver)


def sections(text: str) -> dict[str, str]:
    """``{"system": …, "user": …}`` of a prompt file, stripped as ``tb_common.llm.load_prompt`` strips them."""
    m = _FM.match(text)
    body = m.group(2) if m else ""
    parts = _SECTION.split(body)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def matches_template(template: str, sent: str) -> bool:
    """True when ``sent`` can be ``template`` rendered: the literal pieces between ``{{ … }}`` expressions appear in
    ``sent`` exactly and in order, the first at its start and the last at its end (what an expression renders to is
    not checked)."""
    lits = _EXPR.split(template)
    if len(lits) == 1:
        return sent == template
    first, last = lits[0], lits[-1]
    if len(sent) < len(first) + len(last) or not (sent.startswith(first) and sent.endswith(last)):
        return False
    pos, limit = len(first), len(sent) - len(last)
    for lit in lits[1:-1]:
        j = sent.find(lit, pos, limit)
        if j < 0:
            return False
        pos = j + len(lit)
    return True


@dataclass(frozen=True)
class PromptEntry:
    id: str
    version: int
    file: str
    sha256: str
    schema: str | None
    schema_ref: str | None
    schema_sha256: str | None
    approved_by: str
    date: str
    qualification: dict[str, Any] | None

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "ref": self.ref,
            "file": self.file,
            "sha256": self.sha256,
            "schema": self.schema,
            "schema_sha256": self.schema_sha256,
            "approved_by": self.approved_by,
            "date": self.date,
            "qualification": self.qualification,
        }


@dataclass(frozen=True)
class ResolvedPrompt:
    entry: PromptEntry
    text: str
    path: Path

    @property
    def schema(self) -> str | None:
        return self.entry.schema

    @property
    def sha256(self) -> str:
        return self.entry.sha256

    @property
    def ref(self) -> str:
        return self.entry.ref


def _bad(where: str, msg: str) -> PromptRegistryError:
    return PromptRegistryError("registry_invalid", f"{where}: {msg}")


def _entry(row: Any, where: str) -> PromptEntry:
    if not isinstance(row, dict):
        raise _bad(where, "an entry must be a mapping")
    missing = [k for k in ("id", "version", "file", "sha256", "approved_by", "date", "qualification") if k not in row]
    unknown = sorted(set(row) - set(PromptEntry.__dataclass_fields__))
    if missing or unknown:
        raise _bad(where, f"missing {missing}, unknown {unknown}")
    pid, ver = row["id"], row["version"]
    if not isinstance(pid, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", pid):
        raise _bad(where, f"bad id {pid!r}")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        raise _bad(where, f"bad version {ver!r}")
    if not isinstance(row["sha256"], str) or not _HEX.match(row["sha256"]):
        raise _bad(where, "sha256 must be 64 lower-case hex characters")
    v = row.get("schema_sha256")
    if v is not None and not (isinstance(v, str) and _HEX.match(v)):
        raise _bad(where, "schema_sha256 must be 64 lower-case hex characters")
    if row.get("schema") is None and (row.get("schema_sha256") or row.get("schema_ref")):
        raise _bad(where, "schema_sha256/schema_ref without a schema")
    if row.get("schema") is not None and not row.get("schema_sha256"):
        raise _bad(where, "a schema needs its schema_sha256")
    if not isinstance(row["approved_by"], str) or not row["approved_by"].strip():
        raise _bad(where, "approved_by must name who approved it")
    d = row["date"]
    try:
        day = d if isinstance(d, date) else date.fromisoformat(str(d))
    except ValueError as exc:
        raise _bad(where, f"date {d!r} is not YYYY-MM-DD") from exc
    q = row["qualification"]
    if q is not None and not (
        isinstance(q, dict)
        and (set(q) == {"baseline"} or set(q) == {"record", "sha256"})
        and all(isinstance(x, str) and x for x in q.values())
    ):
        raise _bad(where, "qualification must be null, {baseline: <commit>} or {record, sha256}")
    f = str(row["file"])
    if "/" in f and f not in EXTERNAL_FILES:
        raise _bad(where, f"file {f!r}: a prompt file lives in libs/tb_llm/prompts/ (or is one of EXTERNAL_FILES)")
    return PromptEntry(
        id=pid,
        version=ver,
        file=f,
        sha256=row["sha256"],
        schema=None if row.get("schema") is None else str(row["schema"]),
        schema_ref=None if row.get("schema_ref") is None else str(row["schema_ref"]),
        schema_sha256=row.get("schema_sha256"),
        approved_by=row["approved_by"],
        date=day.isoformat(),
        qualification=None if q is None else dict(q),
    )


class PromptRegistry:
    def __init__(self, data: dict[str, Any], base_dir: Path, *, root: Path = TRIALBOX) -> None:
        rows = data.get("prompts") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise PromptRegistryError("registry_invalid", "the registry needs a 'prompts' list")
        unknown = sorted(set(data) - {"version", "prompts"})
        if unknown:
            raise PromptRegistryError("registry_invalid", f"unknown top-level key(s) {unknown}")
        self.base_dir = base_dir
        self.root = root
        self.version = str(data.get("version") or "")
        self._by: dict[tuple[str, int], PromptEntry] = {}
        for i, row in enumerate(rows):
            e = _entry(row, f"prompts[{i}]")
            if (e.id, e.version) in self._by:
                raise PromptRegistryError("registry_invalid", f"{e.ref} is registered twice")
            self._by[(e.id, e.version)] = e
        self._verified: dict[tuple[str, int], ResolvedPrompt] = {}

    @classmethod
    def load(cls, path: Path | None = None, *, root: Path = TRIALBOX) -> PromptRegistry:
        p = path or REGISTRY_PATH
        data = load_yaml(p.read_text(encoding="utf-8")) or {}
        return cls(data, p.parent, root=root)

    # ------------------------------------------------------------------------------------------------ lookups
    @property
    def ids(self) -> frozenset[str]:
        return frozenset(i for i, _ in self._by)

    def entries(self) -> list[PromptEntry]:
        return [self._by[k] for k in sorted(self._by)]

    def versions(self, prompt_id: str) -> list[int]:
        return sorted(v for i, v in self._by if i == prompt_id)

    def entry(self, prompt_id: str, version: int | None = None) -> PromptEntry:
        vs = self.versions(prompt_id)
        if not vs:
            raise PromptRegistryError("prompt_unknown", f"prompt {prompt_id!r} is not in the prompt registry")
        v = vs[-1] if version is None else version
        if v not in vs:
            raise PromptRegistryError("prompt_unknown", f"prompt {prompt_id}@{v} is not registered (have {vs})")
        return self._by[(prompt_id, v)]

    def active_set(self) -> list[PromptEntry]:
        """The prompts in use: per id the newest registered version (what ``get(id)`` returns)."""
        return [self.entry(i) for i in sorted(self.ids)]

    # ------------------------------------------------------------------------------------------------ checks
    def get(
        self, prompt_id: str, version: int | None = None, *, environment: str | None = None, patient: bool = False
    ) -> ResolvedPrompt:
        """The verified text of ``prompt_id`` at ``version`` (newest when None); see the module rules."""
        e = self.entry(prompt_id, version)
        r = self._verify(e)
        if patient and e.schema is None:
            raise PromptRegistryError(
                "prompt_schema_missing", f"{e.ref} has no output schema: refused for patient data (D2-D4)"
            )
        self.check_qualification(e, environment)
        return r

    def resolve_ref(self, ref: str, **kw: Any) -> ResolvedPrompt:
        """A job record's ``id@version`` (or bare id: the active version)."""
        pid, ver = parse_ref(ref)
        return self.get(pid, ver, **kw)

    def _path(self, e: PromptEntry) -> Path:
        if e.file in EXTERNAL_FILES:
            return (self.root / e.file).resolve()
        path = (self.base_dir / e.file).resolve()
        if path.parent != self.base_dir.resolve():
            raise PromptRegistryError("prompt_unknown", f"{e.ref}: file {e.file!r} is not in {self.base_dir}")
        return path

    def _verify(self, e: PromptEntry) -> ResolvedPrompt:
        key = (e.id, e.version)
        if key in self._verified:
            return self._verified[key]
        path = self._path(e)
        if not path.is_file():
            raise PromptRegistryError("prompt_unknown", f"{e.ref}: file {e.file!r} not found")
        raw = path.read_bytes()
        got = sha256_bytes(raw)
        if got != e.sha256:
            raise PromptRegistryError(
                "prompt_changed",
                f"{e.ref}: {e.file} has sha256 {got[:12]}…, the registry says {e.sha256[:12]}…: a changed prompt "
                "needs a new version in the registry (and a qualification record in PRODUCTION)",
            )
        text = raw.decode("utf-8")
        m = _FM.match(text)
        fm = load_yaml(m.group(1)) if m else None
        if not isinstance(fm, dict) or fm.get("id") != e.id or fm.get("version") != e.version:
            raise PromptRegistryError("registry_invalid", f"{e.ref}: the file's front matter names another prompt")
        if fm.get("output_schema") != e.schema:
            raise PromptRegistryError(
                "registry_invalid", f"{e.ref}: front matter schema {fm.get('output_schema')!r}, registry {e.schema!r}"
            )
        secs = sections(text)
        if set(secs) != {"system", "user"} or "{%" in text or "{#" in text:
            raise PromptRegistryError(
                "registry_invalid", f"{e.ref}: needs '## system' and '## user' and only {{{{ … }}}} expressions"
            )
        if e.schema is not None:
            if e.schema_ref is not None:
                try:
                    have: str | None = schema_sha(ref_schema(e.schema_ref))
                except (ImportError, AttributeError) as exc:
                    raise PromptRegistryError("prompt_schema_missing", f"{e.ref}: {e.schema_ref}: {exc}") from exc
            else:
                have = file_schema_sha(e.schema)
                if have is None:
                    raise PromptRegistryError(
                        "prompt_schema_missing", f"{e.ref}: schemas/{e.schema}.schema.json missing"
                    )
            if have != e.schema_sha256:
                raise PromptRegistryError(
                    "prompt_schema_changed",
                    f"{e.ref}: schema {e.schema} changed (sha256 {str(have)[:12]}…, "
                    f"registry {str(e.schema_sha256)[:12]}…)",
                )
        r = ResolvedPrompt(e, text, path)
        self._verified[key] = r
        return r

    def check_messages(self, r: ResolvedPrompt, messages: Any) -> None:
        """Refuse (``prompt_text_changed``) messages that are not ``r``'s template rendered: messages 1 and 2 are
        the system and user sections (see :func:`matches_template`); after them only the one schema-correction turn
        of ``tb_common.llm`` may follow (an assistant message, then the fixed correction text)."""
        secs = sections(r.text)
        ok = isinstance(messages, list) and len(messages) >= 2
        if ok:
            for i, role in enumerate(("system", "user")):
                m = messages[i]
                ok = (
                    ok
                    and isinstance(m, dict)
                    and m.get("role") == role
                    and isinstance(m.get("content"), str)
                    and matches_template(secs[role], m["content"])
                )
        if ok and len(messages) > 2:
            rest = messages[2:]
            ok = (
                len(rest) == 2
                and all(isinstance(m, dict) and isinstance(m.get("content"), str) for m in rest)
                and rest[0].get("role") == "assistant"
                and rest[1].get("role") == "user"
                and _CORRECTION.fullmatch(rest[1]["content"]) is not None
            )
        if not ok:
            raise PromptRegistryError(
                "prompt_text_changed", f"{r.ref}: the messages sent are not the registered template rendered"
            )

    def check_qualification(self, e: PromptEntry, environment: str | None = None) -> None:
        """PRODUCTION only: the entry carries a qualification that holds (module rules). Elsewhere a missing record
        is allowed, so a new version can be qualified in VALIDATION."""
        env = (environment if environment is not None else _environment()).strip().upper()
        if env != "PRODUCTION":
            return
        q = e.qualification
        if q is None:
            raise PromptRegistryError(
                "prompt_unqualified", f"{e.ref} has no qualification record: refused in PRODUCTION"
            )
        if "baseline" in q:
            if BASELINE.get((e.id, e.version, e.sha256, str(e.schema_sha256))) != q["baseline"]:
                raise PromptRegistryError(
                    "prompt_unqualified", f"{e.ref}: not a baseline prompt (text and schema as frozen in BASELINE)"
                )
            return
        qdir = (self.root / QUALIFICATION_DIR).resolve()
        rec = (self.root / q["record"]).resolve()
        if not rec.is_relative_to(qdir) or rec.suffix != ".json" or not rec.is_file():
            raise PromptRegistryError(
                "prompt_unqualified", f"{e.ref}: qualification record {q['record']} not found in {QUALIFICATION_DIR}/"
            )
        raw = rec.read_bytes()
        if sha256_bytes(raw) != q["sha256"]:
            raise PromptRegistryError("prompt_unqualified", f"{e.ref}: qualification record {q['record']} changed")
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        want = {"prompt": e.ref, "sha256": e.sha256, "schema_sha256": e.schema_sha256}
        if not isinstance(body, dict) or any(body.get(k) != v for k, v in want.items()):
            raise PromptRegistryError(
                "prompt_unqualified", f"{e.ref}: record {q['record']} does not name this prompt, text and schema"
            )

    def problems(self, environment: str | None = None) -> list[str]:
        """Every entry checked as :meth:`get` would (the start check): an empty list is a clean registry."""
        out: list[str] = []
        for e in self.entries():
            try:
                self.get(e.id, e.version, environment=environment)
            except PromptRegistryError as exc:
                out.append(f"{e.ref}: {exc.reason}: {exc}")
        return out

    def check(self, environment: str | None = None) -> None:
        """Raise on any start-time problem (the gateway calls this when it starts in PRODUCTION)."""
        bad = self.problems(environment)
        if bad:
            raise PromptRegistryError("registry_invalid", "prompt registry refused: " + "; ".join(bad))


def _environment() -> str:
    from tb_common.config import environment_name

    return environment_name(os.environ)


_default: PromptRegistry | None = None


def default_registry() -> PromptRegistry:
    global _default
    if _default is None:
        _default = PromptRegistry.load()
    return _default


def get(prompt_id: str, version: int | None = None, **kw: Any) -> ResolvedPrompt:
    """``prompt_registry.get(id, version=None)``: text, schema and sha of a registered prompt (D-201)."""
    return default_registry().get(prompt_id, version, **kw)


def resolve_ref(ref: str, **kw: Any) -> ResolvedPrompt:
    return default_registry().resolve_ref(ref, **kw)


def active_set() -> list[dict[str, Any]]:
    """The active prompt set for the admin models page: one row per id (newest version) with its sha, schema,
    approver, date and qualification."""
    return [e.as_dict() for e in default_registry().active_set()]


def main(argv: list[str] | None = None) -> int:
    """``python -m tb_llm.prompt_registry [--env PRODUCTION]``: check every entry; exit 1 on any problem."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = args[args.index("--env") + 1] if "--env" in args else None
    bad = default_registry().problems(env)
    for line in bad:
        print(line)
    print(f"prompt registry: {'clean' if not bad else f'{len(bad)} problem(s)'} ({len(default_registry().entries())})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
