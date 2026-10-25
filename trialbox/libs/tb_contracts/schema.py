"""JSON-Schema access and validation for the files in ``schemas/`` (the single source of truth)."""

from __future__ import annotations

import json
import os
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


def _schemas_dir() -> Path:
    env = os.environ.get("TB_SCHEMAS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "schemas"


SCHEMAS_DIR = _schemas_dir()


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Load ``schemas/<name>.schema.json`` (``name`` may include the suffix)."""
    fname = name if name.endswith(".schema.json") else f"{name}.schema.json"
    data: dict[str, Any] = json.loads((SCHEMAS_DIR / fname).read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def _registry() -> Registry[Any]:
    resources: list[tuple[str, Resource[Any]]] = []
    for f in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        res = Resource.from_contents(doc, default_specification=DRAFT202012)
        resources.append((f.name, res))
        resources.append((doc["$id"], res))
    return Registry().with_resources(resources)


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    return Draft202012Validator(schema, registry=_registry(), format_checker=FormatChecker())


def null_absent(schema: dict[str, Any], data: Any) -> Any:
    """``data`` with every absent property that ``schema`` requires *and* lets be ``null`` set to ``None``.

    Strict structured output (OpenAI-style ``strict: true``) needs every property listed as required, so an optional
    field is written as required and nullable; for TrialBox ``null`` and absent mean the same. This keeps answers that
    omit such a field (a non-strict endpoint, an older stub) valid. Nested objects with inline ``properties`` are
    handled; ``$ref`` targets are not followed."""
    if not isinstance(data, dict) or not isinstance(schema.get("properties"), dict):
        return data
    out = dict(data)
    props: dict[str, Any] = schema["properties"]
    for key in schema.get("required") or ():
        sub = props.get(key)
        t = sub.get("type") if isinstance(sub, dict) else None
        if key not in out and isinstance(t, list) and "null" in t:
            out[key] = None
    for key, value in out.items():
        sub = props.get(key)
        if isinstance(sub, dict) and isinstance(value, dict):
            out[key] = null_absent(sub, value)
    return out


def schema_errors(name: str, data: Any) -> list[str]:
    """Return human-readable validation errors of ``data`` against schema ``name`` (empty if valid)."""
    errs = sorted(_validator(name).iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errs]


def validate(name: str, data: Any) -> None:
    """Raise ``ValueError`` listing every violation of schema ``name``."""
    errs = schema_errors(name, data)
    if errs:
        raise ValueError(f"{name}: " + "; ".join(errs[:20]))


def dump(model: BaseModel) -> dict[str, Any]:
    """Serialize a contract model to JSON-compatible data (aliases such as ``class``). ``None`` is dropped except for
    required fields, whose ``null`` is part of the contract (e.g. ``Precheck.passed``, ``FunnelStep.pct``)."""
    data = model.model_dump(mode="json", by_alias=True)
    _drop_optional_none(model, data)
    return data


def _drop_optional_none(obj: Any, data: Any) -> None:
    if isinstance(obj, BaseModel) and isinstance(data, dict):
        root = getattr(obj, "root", None) if "root" in type(obj).model_fields else None
        if root is not None:
            _drop_optional_none(root, data)
            return
        for name, f in type(obj).model_fields.items():
            key = f.alias or name
            if key not in data:
                continue
            value = getattr(obj, name)
            if value is None and not f.is_required():
                del data[key]
            else:
                _drop_optional_none(value, data[key])
    elif isinstance(obj, BaseModel) and "root" in type(obj).model_fields:
        _drop_optional_none(getattr(obj, "root", None), data)
    elif isinstance(obj, (list, tuple)) and isinstance(data, list):
        for o, d in zip(obj, data, strict=False):
            _drop_optional_none(o, d)
    elif isinstance(obj, dict) and isinstance(data, dict):
        for k, o in obj.items():
            key = k.value if hasattr(k, "value") else k
            if key in data:
                _drop_optional_none(o, data[key])


def dump_json(model: BaseModel) -> str:
    """Canonical JSON text of a contract model (sorted keys, UTF-8, no spaces) — stable for hashing."""
    return json.dumps(dump(model), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def inline_schema(name: str) -> dict[str, Any]:
    """Self-contained copy of schema ``name``: cross-file ``$ref`` targets are copied into local ``$defs``.

    Used for ``response_format`` (guided decoding needs one document without external references).
    """
    root = load_schema(name)
    defs: dict[str, Any] = {}

    def resolve(node: Any, current: str) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str):
                    target_file, _, pointer = v.partition("#")
                    target_file = target_file or current
                    key = f"{target_file.removesuffix('.schema.json')}{pointer.replace('/$defs/', '__')}".replace(
                        "/", "_"
                    )
                    if key not in defs:
                        defs[key] = {}
                        doc = load_schema(target_file)
                        sub: Any = doc
                        for part in [p for p in pointer.split("/") if p]:
                            sub = sub[part]
                        defs[key] = resolve(
                            {kk: vv for kk, vv in sub.items() if kk not in ("$defs", "$schema", "$id")}, target_file
                        )
                    out[k] = f"#/$defs/{key}"
                elif k in ("$defs", "$schema", "$id"):
                    continue
                else:
                    out[k] = resolve(v, current)
            return out
        if isinstance(node, list):
            return [resolve(x, current) for x in node]
        return node

    fname = name if name.endswith(".schema.json") else f"{name}.schema.json"
    body: dict[str, Any] = resolve(root, fname)
    if defs:
        body["$defs"] = defs
    return body
