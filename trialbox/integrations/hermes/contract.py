"""Static contract of the pinned Hermes release (spec v4 §9.12, HER-7, HER-20; S1-11).

The TrialBox plugins and profiles rely on a small part of Hermes' API and configuration surface. This module reads
that surface from the vendored source tree (``TB_HERMES_SRC``, default ``.cache/hermes-src/<tag>``) with :mod:`ast`
only, without importing Hermes or installing its dependencies, and :func:`contract_problems` lists every difference
from what TrialBox needs. It runs on every upgrade: a failure keeps the site on the pin or on ``native`` (HER-7).
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "hermes-src"

# qualified name (module path.Class.method or module path.function) -> parameter names TrialBox passes or reads
REQUIRED_SIGNATURES: dict[str, tuple[str, ...]] = {
    "hermes_cli.plugins.PluginContext.register_platform": ("name", "label", "adapter_factory", "check_fn"),
    "hermes_cli.plugins.PluginContext.register_hook": ("hook_name", "callback"),
    "gateway.platforms.base.BasePlatformAdapter.__init__": ("config", "platform"),
    "gateway.platforms.base.BasePlatformAdapter.connect": ("is_reconnect",),
    "gateway.platforms.base.BasePlatformAdapter.disconnect": (),
    "gateway.platforms.base.BasePlatformAdapter.send": ("chat_id", "content", "reply_to", "metadata"),
    "gateway.platforms.base.BasePlatformAdapter.get_chat_info": ("chat_id",),
    "gateway.platforms.base.BasePlatformAdapter.handle_message": ("event",),
    "gateway.platforms.base.BasePlatformAdapter.build_source": ("chat_id", "chat_type", "user_id", "message_id"),
    "gateway.platforms.base.BasePlatformAdapter.on_processing_complete": ("event", "outcome"),
    "tools.mcp_tool_schema.mcp_prefixed_tool_name": ("server_name", "tool_name"),
}
# Hooks the two plugins register (HER-21 and §9.6 item 10).
REQUIRED_HOOKS = frozenset(
    {
        "pre_tool_call",
        "post_tool_call",
        "pre_llm_call",
        "post_llm_call",
        "on_session_start",
        "on_session_end",
        "pre_gateway_dispatch",
    }
)
# Keyword arguments TrialBox reads from each hook's fire site.
REQUIRED_HOOK_KWARGS: dict[str, frozenset[str]] = {
    "pre_tool_call": frozenset({"tool_name", "args", "session_id", "task_id"}),
    "pre_llm_call": frozenset({"session_id", "sender_id", "platform"}),
    "pre_gateway_dispatch": frozenset({"event"}),
    "on_session_start": frozenset({"session_id", "platform"}),
}
HOOK_FIRE_SITES: dict[str, str] = {
    "pre_tool_call": "hermes_cli/plugins.py",
    "pre_llm_call": "agent/turn_context.py",
    "pre_gateway_dispatch": "gateway/run_inbound.py",
    "on_session_start": "agent/conversation_loop.py",
}
MESSAGE_EVENT_FIELDS = frozenset({"text", "source", "message_id", "raw_message"})
# PlatformEntry fields tb_relay_adapter passes to register_platform (relay-authenticated senders, HER-16).
PLATFORM_ENTRY_FIELDS = frozenset({"trusted_inbound"})
# The pre_tool_call directive tb_policy_audit returns on allow to attach the turn's assertion (HER-15): the literal
# that hermes_cli/plugins.py must still branch on, and the merged args it must hand to dispatch.
MODIFY_DIRECTIVE_LITERALS = ('action == "modify"', "modified_args")
# MCP per-server keys the profiles set (read by tools/mcp_tool*.py as ``<x>.get("<key>")``).
MCP_SERVER_KEYS = frozenset(
    {
        "url",
        "enabled",
        "client_cert",
        "client_key",
        "ssl_verify",
        "strict_redirect_headers",
        "timeout",
        "connect_timeout",
        "tools",
        "include",
        "sampling",
        "elicitation",
    }
)
# Top-level config sections whose keys are free-form (not enumerated in DEFAULT_CONFIG).
DYNAMIC_SECTIONS = frozenset({"model", "mcp_servers", "platforms", "platform_toolsets", "providers", "hooks"})
# Leaf keys of an auxiliary task block (``_aux(...)`` in DEFAULT_CONFIG builds them).
AUX_TASK_KEYS = frozenset({"provider", "model", "base_url", "api_key", "timeout", "enabled", "extra_body"})
# Keys read outside DEFAULT_CONFIG: dotted key -> (source file, literal that must occur in it).
EXTRA_CONFIG_KEYS: dict[str, tuple[str, str]] = {
    "plugins.enabled": ("hermes_cli/plugins_discovery.py", '"plugins", "enabled"'),
    "plugins.disabled": ("hermes_cli/plugins_discovery.py", '"plugins", "disabled"'),
}


@dataclass
class HermesSurface:
    signatures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    valid_hooks: frozenset[str] = frozenset()
    fail_closed_hooks: frozenset[str] = frozenset()
    bounded_hooks: frozenset[str] = frozenset()
    hook_kwargs: dict[str, frozenset[str]] = field(default_factory=dict)
    message_event_fields: frozenset[str] = frozenset()
    mcp_keys_read: frozenset[str] = frozenset()
    toolsets: dict[str, bool] = field(default_factory=dict)  # name -> is a leaf toolset (no includes, not a preset)
    default_config: dict[str, Any] = field(default_factory=dict)  # nested dict of keys (leaves: None)
    approval_modes: tuple[str, ...] = ()
    min_spawn_depth: int | None = None
    platform_entry_fields: frozenset[str] = frozenset()
    pre_tool_call_modify: bool = False


def default_source(tag: str) -> Path | None:
    """``TB_HERMES_SRC`` if set, else ``.cache/hermes-src/<tag>`` when it exists."""
    env = os.environ.get("TB_HERMES_SRC")
    if env:
        return Path(env)
    p = CACHE / tag
    return p if p.is_dir() else None


def _parse(src: Path, rel: str) -> ast.Module:
    return ast.parse((src / rel).read_text(encoding="utf-8"), filename=rel)


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    a = fn.args
    return tuple(x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs] if x.arg not in ("self", "cls"))


def _signatures(src: Path, wanted: Iterable[str]) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    by_module: dict[str, list[str]] = {}
    for q in wanted:
        parts = q.split(".")
        for i in range(len(parts) - 1, 0, -1):
            rel = "/".join(parts[:i]) + ".py"
            if (src / rel).is_file():
                by_module.setdefault(rel, []).append(q)
                break
    for rel, names in by_module.items():
        tree = _parse(src, rel)
        mod = rel[:-3].replace("/", ".")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[f"{mod}.{node.name}"] = _params(node)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out[f"{mod}.{node.name}.{item.name}"] = _params(item)
        del names
    return out


def _module_set(tree: ast.Module, name: str) -> frozenset[str]:
    for node in tree.body:
        target: ast.expr
        val: ast.expr | None
        if isinstance(node, ast.AnnAssign):
            target, val = node.target, node.value
        elif isinstance(node, ast.Assign):
            target, val = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == name and isinstance(val, (ast.Set, ast.Tuple)):
            return frozenset(str(e.value) for e in val.elts if isinstance(e, ast.Constant))
    return frozenset()


def _hook_kwargs(src: Path, hook: str, rel: str) -> frozenset[str]:
    for node in ast.walk(_parse(src, rel)):
        if (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == hook
        ):
            return frozenset(k.arg for k in node.keywords if k.arg)
    return frozenset()


def _dataclass_fields(src: Path, rel: str, cls: str) -> frozenset[str]:
    for node in _parse(src, rel).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return frozenset(
                s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
            )
    return frozenset()


def _mcp_keys(src: Path) -> frozenset[str]:
    keys: set[str] = set()
    for f in sorted((src / "tools").glob("mcp_tool*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return frozenset(keys)


def _toolsets(src: Path) -> dict[str, bool]:
    for node in _parse(src, "toolsets.py").body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "TOOLSETS":
            assert isinstance(node.value, ast.Dict)
            out: dict[str, bool] = {}
            for k, v in zip(node.value.keys, node.value.values, strict=True):
                if not isinstance(k, ast.Constant):
                    continue
                name = str(k.value)
                composite = any(kw.arg in ("includes", "posture") for kw in getattr(v, "keywords", []))
                out[name] = not composite and not name.startswith("hermes-")
            return out
    return {}


def _dict_keys(node: ast.expr) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(node, ast.Dict):
        return out
    for k, v in zip(node.keys, node.values, strict=True):
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            out[k.value] = _dict_keys(v) if isinstance(v, ast.Dict) else None
    return out


def _default_config(src: Path) -> dict[str, Any]:
    for node in _parse(src, "hermes_cli/config_defaults.py").body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DEFAULT_CONFIG" for t in node.targets
        ):
            return _dict_keys(node.value)
    return {}


def _int_const(src: Path, rel: str, name: str) -> int | None:
    for node in _parse(src, rel).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            v = node.value
            return int(v.value) if isinstance(v, ast.Constant) and isinstance(v.value, int) else None
    return None


def extract(src: Path) -> HermesSurface:
    """Read the TrialBox-relevant surface of the Hermes source tree at ``src``."""
    plugins = _parse(src, "hermes_cli/plugins.py")
    dispatch = _parse(src, "hermes_cli/plugins_dispatch.py")
    approval = _parse(src, "hermes_cli/approval_mode.py")
    return HermesSurface(
        signatures=_signatures(src, REQUIRED_SIGNATURES),
        valid_hooks=_module_set(plugins, "VALID_HOOKS"),
        fail_closed_hooks=_module_set(dispatch, "_HOOK_TIMEOUT_FAIL_CLOSED_HOOKS"),
        bounded_hooks=_module_set(dispatch, "_HOOK_TIMEOUT_BOUNDED_HOOKS"),
        hook_kwargs={h: _hook_kwargs(src, h, rel) for h, rel in HOOK_FIRE_SITES.items()},
        message_event_fields=_dataclass_fields(src, "gateway/platforms/event.py", "MessageEvent"),
        mcp_keys_read=_mcp_keys(src),
        toolsets=_toolsets(src),
        default_config=_default_config(src),
        approval_modes=tuple(sorted(_module_set(approval, "VALID_APPROVAL_MODES"))),
        min_spawn_depth=_int_const(src, "tools/delegate_tool_config.py", "_MIN_SPAWN_DEPTH"),
        platform_entry_fields=_dataclass_fields(src, "gateway/platform_registry.py", "PlatformEntry"),
        pre_tool_call_modify=all(
            lit in (src / "hermes_cli/plugins.py").read_text(encoding="utf-8") for lit in MODIFY_DIRECTIVE_LITERALS
        ),
    )


def contract_problems(s: HermesSurface) -> list[str]:
    """Every way the release's API surface differs from what ``tb_relay_adapter``/``tb_policy_audit`` need."""
    out: list[str] = []
    for q, params in REQUIRED_SIGNATURES.items():
        have = s.signatures.get(q)
        if have is None:
            out.append(f"{q} missing")
        elif missing := [p for p in params if p not in have]:
            out.append(f"{q} lacks parameters {missing}")
    if missing_hooks := sorted(REQUIRED_HOOKS - s.valid_hooks):
        out.append(f"hooks not in VALID_HOOKS: {missing_hooks}")
    for hook, kw in REQUIRED_HOOK_KWARGS.items():
        if lacking := sorted(kw - s.hook_kwargs.get(hook, frozenset())):
            out.append(f"hook {hook} fire site lacks kwargs {lacking}")
    if "pre_tool_call" not in s.fail_closed_hooks:
        out.append("pre_tool_call no longer fails closed on hook timeout (plugins.hook_callback_timeout)")
    if lacking_fields := sorted(MESSAGE_EVENT_FIELDS - s.message_event_fields):
        out.append(f"MessageEvent lacks fields {lacking_fields}")
    if lacking_keys := sorted(MCP_SERVER_KEYS - s.mcp_keys_read):
        out.append(f"MCP client no longer reads server keys {lacking_keys}")
    if lacking_entry := sorted(PLATFORM_ENTRY_FIELDS - s.platform_entry_fields):
        out.append(f"PlatformEntry lacks fields {lacking_entry}")
    if not s.pre_tool_call_modify:
        out.append("pre_tool_call no longer applies 'modify' directives (the per-call assertion route, HER-15)")
    if "manual" not in s.approval_modes:
        out.append(f"approvals.mode 'manual' not offered (modes {list(s.approval_modes)})")
    return out


def extra_config_keys(src: Path) -> frozenset[str]:
    """The :data:`EXTRA_CONFIG_KEYS` whose reading code is present in the source tree."""
    return frozenset(k for k, (rel, lit) in EXTRA_CONFIG_KEYS.items() if lit in (src / rel).read_text(encoding="utf-8"))


def unknown_config_keys(
    config: Mapping[str, Any], defaults: Mapping[str, Any], extra: frozenset[str] = frozenset()
) -> list[str]:
    """Dotted keys of ``config`` that the release does not know (configuration diff, §9.12 / HER-37 (h))."""
    out: list[str] = []

    def walk(cfg: Mapping[str, Any], dflt: Mapping[str, Any], prefix: str) -> None:
        in_aux_task = prefix.startswith("auxiliary.") and prefix.count(".") == 2
        for k, v in cfg.items():
            key = f"{prefix}{k}"
            if not prefix and k in DYNAMIC_SECTIONS:
                continue
            if in_aux_task:
                if k not in AUX_TASK_KEYS and k not in dflt:
                    out.append(key)
                continue
            if k not in dflt:
                if key not in extra:
                    out.append(key)
                continue
            sub = dflt[k]
            if isinstance(v, Mapping) and (isinstance(sub, Mapping) or prefix == "auxiliary."):
                walk(v, sub if isinstance(sub, Mapping) else {}, key + ".")
            # otherwise a leaf, or a default built by a call (accepted as a whole)

    walk(config, defaults, "")
    return out
