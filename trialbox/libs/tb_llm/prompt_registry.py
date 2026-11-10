"""The prompt registry (WS-02.3, D-201): every prompt TrialBox sends is a registry object, resolved by (id, version).

``libs/tb_llm/prompts/registry.yaml`` lists one entry per prompt version::

    - id: judge                 # the prompt id (the ``X-TB-Prompt`` header names ``id@version``)
      version: 4
      file: judge_v4.md         # in ``libs/tb_llm/prompts/``; the text is the file's bytes
      sha256: 17db…             # of the file's bytes: a text that differs is refused at load
      schema: llm_judge_output  # the output schema (``schemas/<name>.schema.json``, or ``schema_ref``)
      schema_ref: null          # ``module:Class`` when the schema is a pydantic model, not a file
      schema_sha256: 0c1f…      # of the canonical self-contained schema the caller sends (``schema_sha``)
      approved_by: …
      date: 2026-11-05
      qualification: {record: eval/qualification/<build>.json, sha256: …}   # or {baseline: <commit>}, or null

Rules (each refusal is a :class:`PromptRegistryError` with a stable ``reason``):

* ``get(id, version=None)`` returns the text, the schema name and the sha; ``version=None`` is the newest registered
  version (the active one); an id or version the registry does not list is refused (``prompt_unknown``);
* the file's sha256 must equal the registry's (``prompt_changed``), and its front matter must name the same id,
  version and output schema (``registry_invalid``): editing a prompt without a new registry entry fails the suite
  (``tests/unit/test_prompt_registry.py``), the gateway and every loader;
* a file-backed schema is re-hashed and must equal ``schema_sha256`` (``prompt_schema_changed``): the fields the
  quote check and the two-model rule read (``verdict``, ``quote``, ``quote_date``) cannot change silently either;
* in PRODUCTION (``TB_ENV``) an entry needs a non-null ``qualification`` (``prompt_unqualified``): a record file
  (provisional, until T-012's ``trialbox eval qualify`` record schema lands: ``{record: <path under trialbox/>,
  sha256: <of that file>}``, the file must exist with that sha) or, only for the prompts in service when the registry
  was created, ``{baseline: <commit>}`` (the exact ``(id, version, sha256)`` triples are frozen in :data:`BASELINE`
  here, so a new entry cannot claim it);
* a prompt with no schema is refused for a patient route (data class D2, D3 or D4: ``prompt_schema_missing``).

The ``unpinned:`` list names the few prompts whose text is built in code (``ref``, ``context_of_use``, ``source``,
``reason``): the gateway lets exactly that ``id@version`` through for exactly that context of use, marked unpinned.

A version named in a job record (``id@version``, :func:`resolve_ref`) keeps resolving to that text after a newer
version is registered. :func:`active_set` is the admin page's list (one entry per id, the newest).
"""

from __future__ import annotations

import hashlib
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
TRIALBOX = Path(__file__).resolve().parents[2]  # qualification record paths are relative to trialbox/
PATIENT_CLASSES = frozenset({"D2", "D3", "D4"})
_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)
_HEX = re.compile(r"^[0-9a-f]{64}$")

# The prompts in service on origin/master when the registry was created (T-101, from 6e11e25): their texts were moved
# here byte for byte and were run before any qualification record existed. Only these exact (id, version, sha256)
# triples may carry ``qualification: {baseline: 6e11e25}``; anything new needs a record.
BASELINE_COMMIT = "6e11e25"
BASELINE: frozenset[tuple[str, int, str]] = frozenset(
    {
        ("assist", 1, "6fecaff99607e9d4b67427696a6e9a78aca433ce60bf611ca510468d99e5d9c2"),
        ("chart_facts", 1, "9fc73194a8897d00f4f7e8e8af2f4339d311f53bb61dce58418a04bf24be773a"),
        ("classify_intent", 1, "6d93975458b1d455ec79e4ea55c85bd15a0499b0fcf04526d5a631c1905e391f"),
        ("classify_intent", 2, "bb17b158d9d58f4623ef753730926fcbf208a2eeaea7707ace0f864762d9ffb2"),
        ("concept_map", 1, "6721408d8227a4d6d55c4d917472ca67a8063a99d2986e8a8a3a1a6444a14006"),
        ("consent_explain", 1, "4f5b90c56b2371094236a6210468976ef46d734614bbfa87f8c649d7360f6998"),
        ("consent_translate", 1, "8aab2417dd60215e6b27ece9b82044f15949cbd24ef8d5b82d1b2525b8e0fe98"),
        ("consent_verify", 1, "a2c68131275bc97e313a34da886370398d0665f603dbd74c5ea84e2f57239b1e"),
        ("draft_doc", 1, "2c9bc8a9d7c0bb1b62d5a89066e2ea8ad696b739bc8cc95b22f8844efd45ff1d"),
        ("ie_locate", 1, "bbff3a9fdf3bb3dc7cb633f5b443abab0336d5f5f81d3669da482c814d78f5a1"),
        ("ir_extract", 1, "a30c810c6998340b0b162f92c8ebd5899b565346f54ee006ccf3599613b8fcb5"),
        ("ir_extract", 2, "bec957be30fc46ab47aafeae5e2666ce187dbfcf4d2d949f00855953abf34674"),
        ("judge", 3, "bfbae7066925ea1de94f4163dd686f0bea3c483f5d48db5c03518d1c52111017"),
        ("judge", 4, "17db3b50b3f874a2e7253c806942739170f8f7a947d4548aed8e9eafa4cdef6e"),
    }
)


class PromptRegistryError(RuntimeError):
    """A refused prompt; ``reason`` is the stable code the gateway answers with."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def schema_sha(schema: Any) -> str:
    """sha256 of a JSON schema in canonical form (sorted keys, no whitespace): the same value whether the registry
    hashes ``tb_contracts.inline_schema(name)`` or the gateway hashes the ``response_format`` a caller sent."""
    return sha256_bytes(json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


@lru_cache(maxsize=64)
def file_schema_sha(name: str) -> str | None:
    """``schema_sha`` of ``schemas/<name>.schema.json`` made self-contained, or None when no such file exists."""
    from tb_contracts import SCHEMAS_DIR, inline_schema

    if not (SCHEMAS_DIR / f"{name}.schema.json").is_file():
        return None
    return schema_sha(inline_schema(name))


def parse_ref(ref: str) -> tuple[str, int | None]:
    """``judge@4`` -> ``("judge", 4)``; ``judge`` -> ``("judge", None)``. A malformed version is refused."""
    pid, sep, ver = ref.strip().partition("@")
    if not sep:
        return pid, None
    if not ver.isdigit():
        raise PromptRegistryError("prompt_unknown", f"prompt reference {ref!r}: the version must be a number")
    return pid, int(ver)


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


def _entry(row: Any, where: str) -> PromptEntry:
    if not isinstance(row, dict):
        raise PromptRegistryError("registry_invalid", f"{where}: an entry must be a mapping")
    missing = [k for k in ("id", "version", "file", "sha256", "approved_by", "date", "qualification") if k not in row]
    unknown = sorted(set(row) - set(PromptEntry.__dataclass_fields__))
    if missing or unknown:
        raise PromptRegistryError("registry_invalid", f"{where}: missing {missing}, unknown {unknown}")
    pid, ver = row["id"], row["version"]
    if not isinstance(pid, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", pid) or "@" in pid:
        raise PromptRegistryError("registry_invalid", f"{where}: bad id {pid!r}")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        raise PromptRegistryError("registry_invalid", f"{where}: bad version {ver!r}")
    for k in ("sha256", "schema_sha256"):
        v = row.get(k)
        if v is not None and not (isinstance(v, str) and _HEX.match(v)):
            raise PromptRegistryError("registry_invalid", f"{where}: {k} must be 64 lower-case hex characters")
    if not row["sha256"]:
        raise PromptRegistryError("registry_invalid", f"{where}: sha256 is required")
    if row.get("schema") is None and (row.get("schema_sha256") or row.get("schema_ref")):
        raise PromptRegistryError("registry_invalid", f"{where}: schema_sha256/schema_ref without a schema")
    if row.get("schema") is not None and not row.get("schema_sha256"):
        raise PromptRegistryError("registry_invalid", f"{where}: a schema needs its schema_sha256")
    q = row["qualification"]
    if q is not None and not (
        isinstance(q, dict)
        and (set(q) == {"baseline"} or set(q) == {"record", "sha256"})
        and all(isinstance(v, str) and v for v in q.values())
    ):
        raise PromptRegistryError(
            "registry_invalid", f"{where}: qualification must be null, {{baseline: <commit>}} or {{record, sha256}}"
        )
    d = row["date"]
    return PromptEntry(
        id=pid,
        version=ver,
        file=str(row["file"]),
        sha256=str(row["sha256"]),
        schema=None if row.get("schema") is None else str(row["schema"]),
        schema_ref=None if row.get("schema_ref") is None else str(row["schema_ref"]),
        schema_sha256=row.get("schema_sha256"),
        approved_by=str(row["approved_by"]),
        date=d.isoformat() if isinstance(d, date) else str(d),
        qualification=None if q is None else dict(q),
    )


class PromptRegistry:
    def __init__(self, data: dict[str, Any], base_dir: Path, *, root: Path = TRIALBOX) -> None:
        rows = data.get("prompts") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise PromptRegistryError("registry_invalid", "the registry needs a 'prompts' list")
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
        # prompts whose text is built in code (benchmarks on fictional patients), named here so that the gateway
        # passes exactly this id@version for exactly this context of use; nothing about their text is pinned
        self.unpinned: dict[str, dict[str, str]] = {}
        for i, row in enumerate(data.get("unpinned") or []):
            keys = {"ref", "context_of_use", "source", "reason"}
            if not isinstance(row, dict) or set(row) != keys or not all(isinstance(v, str) and v for v in row.values()):
                raise PromptRegistryError("registry_invalid", f"unpinned[{i}]: needs exactly {sorted(keys)}")
            pid, ver = parse_ref(row["ref"])
            if ver is None or pid in self.ids:
                raise PromptRegistryError(
                    "registry_invalid", f"unpinned[{i}]: {row['ref']!r} needs id@version, unpinned"
                )
            self.unpinned[row["ref"]] = dict(row)

    @classmethod
    def load(cls, path: Path | None = None, *, root: Path = TRIALBOX) -> PromptRegistry:
        p = path or REGISTRY_PATH
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
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

    def _verify(self, e: PromptEntry) -> ResolvedPrompt:
        key = (e.id, e.version)
        if key in self._verified:
            return self._verified[key]
        path = (self.base_dir / e.file).resolve()
        if path.parent != self.base_dir.resolve() or not path.is_file():
            raise PromptRegistryError("prompt_unknown", f"{e.ref}: file {e.file!r} is not in {self.base_dir}")
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
        fm = yaml.safe_load(m.group(1)) if m else None
        if not isinstance(fm, dict) or fm.get("id") != e.id or fm.get("version") != e.version:
            raise PromptRegistryError("registry_invalid", f"{e.ref}: the file's front matter names another prompt")
        if fm.get("output_schema") != e.schema:
            raise PromptRegistryError(
                "registry_invalid", f"{e.ref}: front matter schema {fm.get('output_schema')!r}, registry {e.schema!r}"
            )
        if e.schema is not None and e.schema_ref is None:
            have = file_schema_sha(e.schema)
            if have is None:
                raise PromptRegistryError("prompt_schema_missing", f"{e.ref}: schemas/{e.schema}.schema.json missing")
            if have != e.schema_sha256:
                raise PromptRegistryError(
                    "prompt_schema_changed",
                    f"{e.ref}: schema {e.schema} changed (sha256 {have[:12]}…, registry {str(e.schema_sha256)[:12]}…)",
                )
        r = ResolvedPrompt(e, text, path)
        self._verified[key] = r
        return r

    def check_qualification(self, e: PromptEntry, environment: str | None = None) -> None:
        """PRODUCTION only: the entry carries a qualification that holds (a record file with its sha, or the frozen
        baseline). Elsewhere a missing record is allowed, so a new version can be qualified in VALIDATION."""
        env = (environment if environment is not None else _environment()).strip().upper()
        if env != "PRODUCTION":
            return
        q = e.qualification
        if q is None:
            raise PromptRegistryError(
                "prompt_unqualified", f"{e.ref} has no qualification record: refused in PRODUCTION"
            )
        if "baseline" in q:
            if q["baseline"] != BASELINE_COMMIT or (e.id, e.version, e.sha256) not in BASELINE:
                raise PromptRegistryError(
                    "prompt_unqualified", f"{e.ref}: only the prompts in service at {BASELINE_COMMIT} are baseline"
                )
            return
        rec = (self.root / q["record"]).resolve()
        if not rec.is_relative_to(self.root.resolve()) or not rec.is_file():
            raise PromptRegistryError("prompt_unqualified", f"{e.ref}: qualification record {q['record']} not found")
        if sha256_bytes(rec.read_bytes()) != q["sha256"]:
            raise PromptRegistryError("prompt_unqualified", f"{e.ref}: qualification record {q['record']} changed")

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
        """Raise on the first start-time problem (the gateway calls this when it starts in PRODUCTION)."""
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
