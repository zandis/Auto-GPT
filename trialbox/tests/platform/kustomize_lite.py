"""A pure-Python stand-in for ``kustomize build`` of the platform overlays, enough for the day-2 tests (T-633): resources
(files and directories, anywhere on disk), components, ``configMapGenerator`` with create, ``merge`` and ``replace``,
and the ``images`` transformer applied at each level, as kustomize applies it (an overlay's ``images`` entry names the
image as the level below left it: its repository). No name hashes, no patches: ``kustomize`` itself runs where it is
installed (``_rendered``)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tools.trialbox import platform as pf


def _generated(d: Path, k: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    out = []
    for g in k.get("configMapGenerator") or []:
        data: dict[str, str] = {}
        for f in g.get("files") or []:
            key, _, src = f.partition("=")
            data[key if src else Path(key).name] = (d / (src or key)).read_text(encoding="utf-8")
        for e in g.get("envs") or []:
            for line in (d / e).read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    kk, _, vv = line.partition("=")
                    data[kk] = vv
        for lit in g.get("literals") or []:
            kk, _, vv = lit.partition("=")
            data[kk] = vv
        cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": g["name"]}, "data": data}
        out.append((cm, str(g.get("behavior") or "create")))
    return out


def _set_images(objs: list[dict[str, Any]], images: list[dict[str, Any]]) -> None:
    by = {i["name"]: i for i in images}
    for _, spec, _ in pf.pod_specs(pf.PlatformState(objs)):
        for c in pf.containers(spec):
            repo, tag, digest = pf.split_ref(str(c.get("image") or ""))
            i = by.get(repo)
            if i is None:
                continue
            name = i.get("newName") or repo
            if i.get("digest"):
                c["image"] = f"{name}@{i['digest']}"
            elif i.get("newTag"):
                c["image"] = f"{name}:{i['newTag']}"
            else:
                c["image"] = name + (f":{tag}" if tag else "") + (f"@{digest}" if digest else "")


def _apply(d: Path, k: dict[str, Any], objs: list[dict[str, Any]]) -> None:
    """The generators and the images transformer of ``d`` on everything accumulated at its level."""
    for cm, behavior in _generated(d, k):
        name = cm["metadata"]["name"]
        old = next((o for o in objs if o["kind"] == "ConfigMap" and o["metadata"]["name"] == name), None)
        if behavior == "merge":
            assert old is not None, f"{d}: merge into a missing ConfigMap {name}"
            old["data"].update(cm["data"])
        elif behavior == "replace":
            assert old is not None, f"{d}: replace of a missing ConfigMap {name}"
            old["data"] = cm["data"]
        else:
            assert old is None, f"{d}: ConfigMap {name} generated twice"
            objs.append(cm)
    _set_images(objs, k.get("images") or [])


def _resources(d: Path, k: dict[str, Any], objs: list[dict[str, Any]]) -> None:
    for r in k.get("resources") or []:
        p = (d / r).resolve()
        if p.is_dir():
            objs.extend(_load(p))
        else:
            objs.extend(x for x in yaml.safe_load_all(p.read_text(encoding="utf-8")) if x)
    for c in k.get("components") or []:  # a component works on its parent's accumulated objects
        cd = (d / c).resolve()
        kc = yaml.safe_load((cd / "kustomization.yaml").read_text(encoding="utf-8")) or {}
        _resources(cd, kc, objs)
        _apply(cd, kc, objs)


def _load(d: Path) -> list[dict[str, Any]]:
    k = yaml.safe_load((d / "kustomization.yaml").read_text(encoding="utf-8")) or {}
    objs: list[dict[str, Any]] = []
    _resources(d, k, objs)
    _apply(d, k, objs)
    return objs


def build(overlay: Path) -> list[dict[str, Any]]:
    return _load(overlay.resolve())


def rendered(overlay: Path) -> str:
    """``kustomize build`` when installed (TB_KUSTOMIZE or PATH), else the stand-in."""
    exe = os.environ.get("TB_KUSTOMIZE") or shutil.which("kustomize")
    if exe:
        return subprocess.run([exe, "build", str(overlay)], check=True, capture_output=True, text=True).stdout
    return yaml.safe_dump_all(build(overlay), sort_keys=False)
