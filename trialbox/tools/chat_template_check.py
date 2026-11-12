"""G-1 of the deep review (2026-11-12, 13 §8.1): is the judge's chat template the one its weights folder carries?

Compose starts the judge with ``--chat-template`` (the developer's file at a pinned revision, DEP-007, D-392:
``models/registry.yaml`` ``chat_template``); the quantised folder has a template of its own. This check, the part
``chat-template`` of the complete run, writes down:

* the sha256 of the template the serving configuration passes: the file the judge was started with (the serving
  record's ``chat_template``), else the registry row's file under the models root, else that file fetched from the
  developer's repository at the registry's revision (public; no token is read or sent);
* the sha256 of the weights folder's own template (``chat_template.jinja``, else ``tokenizer_config.json``'s
  ``chat_template``), read by the Hugging Face tokenizer of that folder;
* token identity on :data:`N_PROMPTS` synthetic prompts: the ids the judge's server gives (``POST /tokenize`` with
  the messages) against the ids of the folder's tokenizer, with the folder's template and with the passed one.

**Pass: identical** (the two hashes, and every prompt's ids). Identical: ``--chat-template`` can go. Different:
every later test uses the developer's file, and the canary runs again first.

The tokenizer side needs ``transformers``, which the box's environment does not carry: it runs where the model
server's image is (``TB_BENCH_EMBED_CMD``, the VM's ``tb-embed-py``; this interpreter when unset):

    python -m tools.chat_template_check hf --model <repo or folder> --prompts prompts.json --out hf.json \\
        [--template <file>]

Synthetic prompts only (fictional notes written here); no patient data, no key in any file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
N_PROMPTS = 20
SECONDS = 300.0  # the estimate's row: the image's start, the tokenizer's load, 20 short calls (set high: unmeasured)
HF_URL = "https://huggingface.co/{source}/resolve/{revision}/{name}"

_NOTES = {
    "ja": ("痛風の既往あり。尿酸値 8.{i} mg/dL。アロプリノール 100 mg を内服中。結核の既往なし。",
           "この患者は基準「活動性結核がない」を満たしますか。JSON で答えてください。"),
    "zh-TW": ("病人有痛風病史，尿酸 8.{i} mg/dL，目前服用 allopurinol 100 mg。否認結核病史。",
              "此病人是否符合「無活動性結核」條件？請以 JSON 回答。"),
    "en": ("History of gout. Uric acid 8.{i} mg/dL. On allopurinol 100 mg daily. Denies tuberculosis.",
           "Does this patient meet the criterion 'no active tuberculosis'? Answer in JSON."),
}  # fmt: skip
_SYSTEM = "You are a careful clinical trial screening assistant. Answer only with the JSON object asked for."


def prompts(n: int = N_PROMPTS) -> list[list[dict[str, str]]]:
    """``n`` fictional judge-style prompts in ja, zh-TW and en: user only, system and user, and a second turn (the
    template's role handling, its line ends and its special tokens are what differ between two templates)."""
    out: list[list[dict[str, str]]] = []
    langs = list(_NOTES)
    for i in range(n):
        note, ask = _NOTES[langs[i % len(langs)]]
        user = f"{ask}\n\n```json\n{json.dumps({'note': note.format(i=i % 10), 'case': i}, ensure_ascii=False)}\n```"
        msgs = [{"role": "user", "content": user}]
        if i % 4 in (1, 3):
            msgs.insert(0, {"role": "system", "content": _SYSTEM})
        if i % 4 >= 2:
            msgs += [{"role": "assistant", "content": '{"verdict": "unknown"}'}, {"role": "user", "content": ask}]
        out.append(msgs)
    return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compare(server: Sequence[list[int] | None], folder: list[list[int]],
            passed: list[list[int]] | None) -> dict[str, Any]:  # fmt: skip
    """Per prompt: the server's ids against the folder tokenizer's, and the folder's template against the passed
    one. ``different`` lists the first prompts that differ, with the first position that does."""

    def diff(a: Sequence[list[int] | None], b: list[list[int]]) -> list[dict[str, Any]]:
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            if x is None or list(x) != list(y):
                at = next((k for k, (p, q) in enumerate(zip(x or [], y, strict=False)) if p != q),
                          min(len(x or []), len(y)))  # fmt: skip
                out.append({"prompt": i, "first_difference_at": at, "lengths": [len(x or []), len(y)]})
        return out

    d_server = diff(server, folder)
    if len(server) != len(folder):
        d_server = [{"prompt": -1, "lengths": [len(server), len(folder)]}]
    out: dict[str, Any] = {"prompts": len(folder), "tokens": sum(len(x) for x in folder),
                           "server_equals_folder": not d_server, "server_different": d_server[:5]}  # fmt: skip
    if passed is not None:
        d_passed = diff(passed, folder)
        out.update({"passed_equals_folder": not d_passed and len(passed) == len(folder),
                    "passed_different": d_passed[:5]})  # fmt: skip
    return out


# ---------------------------------------------------------------- the tokenizer side (in the model server's image)
def hf_side(model: str, prompts_file: Path, out: Path, template: Path | None) -> int:
    import transformers  # type: ignore[import-not-found]  # in the model server's image, not in the box's venv
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model, local_files_only=True)
    msgs = json.loads(prompts_file.read_text(encoding="utf-8"))
    own = tok.chat_template if isinstance(tok.chat_template, str) else json.dumps(tok.chat_template, sort_keys=True)

    def ids(m: list[dict[str, str]], tpl: str | None) -> list[int]:
        got = tok.apply_chat_template(m, tokenize=True, add_generation_prompt=True, chat_template=tpl)
        got = got["input_ids"] if isinstance(got, dict) or hasattr(got, "input_ids") else got
        return [int(x) for x in got]

    res: dict[str, Any] = {"model": model, "transformers": transformers.__version__,
                           "folder_template_sha256": sha256_text(own or ""), "folder_template_chars": len(own or ""),
                           "ids": [ids(m, None) for m in msgs], "ids_passed": None}  # fmt: skip
    if template is not None:
        text = template.read_text(encoding="utf-8")
        res.update({"passed_template_sha256": sha256_text(text), "ids_passed": [ids(m, text) for m in msgs]})
    out.write_text(json.dumps(res), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- the part (on the VM, beside the servers)
def passed_template(record: dict[str, Any], models_roots: list[Path], cache: Path) -> dict[str, Any]:
    """The template the serving configuration passes to the judge, as a file here: ``{"path", "sha256", "from"}``, or
    ``{"path": None, "why"}``. Order: the record's ``chat_template`` (the server was started with it), the registry
    row's file under a models root (what compose passes), the developer's file at the registry's revision."""
    from tools import pin_model, serving_config

    started_with, _ = serving_config.chat_template_of(record)
    _, builds = pin_model._committed()
    row = builds.get(next(b for b, endpoint, *_ in pin_model.PROFILE_PAIRS["rtxpro6000"] if endpoint == "serving"), {})
    tpl = pin_model.template_of(row) or {}
    tried: list[str] = []
    cands = [(Path(started_with), "the serving record (--chat-template)")] if started_with else []
    cands += [(r / str(tpl["file"]), "the registry row's file under the models root") for r in models_roots
              if tpl.get("file")]  # fmt: skip
    for path, what in cands:
        if path.is_file():
            return {"path": str(path), "sha256": pin_model.file_sha256(path), "from": what,
                    "served_with_it": bool(started_with)}  # fmt: skip
        tried.append(str(path))
    if tpl.get("source") and tpl.get("revision"):
        url = HF_URL.format(source=tpl["source"], revision=tpl["revision"], name=Path(str(tpl["file"])).name)
        dest = cache / "chat_template.passed.jinja"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:  # https, the registry row's own source
                data = r.read()
            cache.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return {"path": str(dest), "sha256": hashlib.sha256(data).hexdigest(), "served_with_it": False,
                    "from": f"fetched: {tpl['source']} at {tpl['revision']}"}  # fmt: skip
        except (OSError, ValueError) as exc:
            tried.append(f"{url} ({str(exc)[:80]})")
    return {"path": None, "why": "not on this machine and not fetched; looked at: " + "; ".join(tried)}


def server_ids(v1_url: str, served: str, msgs: list[list[dict[str, str]]], key: str = "") -> list[list[int] | None]:
    """The ids the server's own tokenizer and template give each prompt (``POST /tokenize``; None: no answer)."""
    from tools.run_metrics import server_root

    out: list[list[int] | None] = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for m in msgs:
        body = json.dumps({"model": served, "messages": m, "add_generation_prompt": True}).encode()
        hdr = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
        try:
            req = urllib.request.Request(server_root(v1_url) + "/tokenize", data=body, headers=hdr)
            with opener.open(req, timeout=60) as r:
                out.append([int(x) for x in json.loads(r.read())["tokens"]])
        except (OSError, ValueError, KeyError, TypeError):
            out.append(None)
    return out


def run(a: Any) -> dict[str, Any]:
    """The part ``chat-template``: the checks of the module docstring and the ``chat_template`` block of its result."""
    from tools.complete_run import JUDGE, VENDOR_RECORD, _one

    t0 = time.perf_counter()
    work = a.dir / "chat-template"
    work.mkdir(parents=True, exist_ok=True)
    rec_path = a.live_record if a.live_record and Path(a.live_record).is_file() else VENDOR_RECORD
    record = json.loads(Path(rec_path).read_text(encoding="utf-8"))
    judge: dict[str, Any] = next((s for s in record.get("servers") or [] if s.get("role") == "judge"), {})
    roots = [Path(p) for p in (os.environ.get("TB_MODELS_DIR"), "/models", ROOT / "deploy" / "models") if p]
    passed = passed_template(record, roots, work)
    msgs = prompts()
    (work / "prompts.json").write_text(json.dumps(msgs, ensure_ascii=False), encoding="utf-8")
    runner = shlex.split(os.environ.get("TB_BENCH_EMBED_CMD", "")) or [sys.executable]
    cmd = [*runner, "-m", "tools.chat_template_check", "hf", "--model", str(judge.get("model") or ""),
           "--prompts", str(work / "prompts.json"), "--out", str(work / "hf.json")]  # fmt: skip
    if passed["path"]:  # a copy in the work folder: the image that runs the tokenizer sees this folder, not /models
        local = work / "chat_template.passed.jinja"
        if Path(passed["path"]) != local:
            shutil.copyfile(passed["path"], local)
        cmd += ["--template", str(local)]
    (work / "hf.json").unlink(missing_ok=True)
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800, check=False)
        err = r.stderr.strip()[-300:] if r.returncode else ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        err = str(exc)[:300]
    hf = json.loads((work / "hf.json").read_text(encoding="utf-8")) if (work / "hf.json").exists() else {}
    served = server_ids(a.judge_url, JUDGE, msgs, os.environ.get("TB_GPU_KEY", "")) if a.judge_url else []
    cmp = compare(served, hf.get("ids") or [], hf.get("ids_passed")) if hf.get("ids") else {}
    folder_sha, passed_sha = hf.get("folder_template_sha256"), hf.get("passed_template_sha256")
    checks: list[tuple[str, bool, Any]] = [
        ("the weights folder's tokenizer and chat template were read", bool(hf.get("folder_template_chars")),
         err or folder_sha),
        ("the template the serving configuration passes is here", bool(passed["path"]),
         passed.get("from") or passed.get("why")),
        ("the two templates are identical (sha256 of the text)", bool(folder_sha) and folder_sha == passed_sha,
         {"folder": folder_sha, "passed": passed_sha}),
        (f"{len(msgs)} prompts: the server's token ids equal the folder tokenizer's", bool(cmp)
         and cmp["server_equals_folder"], cmp.get("server_different") or sum(1 for s in served if s is None)),
        (f"{len(msgs)} prompts: the passed template gives the same token ids as the folder's", bool(cmp)
         and bool(cmp.get("passed_equals_folder")), cmp.get("passed_different", "no passed template")),
    ]  # fmt: skip
    block = {"judge_model": judge.get("model"), "judge_started_with": judge.get("chat_template"),
             "passed": passed, "passed_text_sha256": passed_sha, "folder_template_sha256": folder_sha,
             "folder_template_chars": hf.get("folder_template_chars"), "transformers": hf.get("transformers"),
             "tokens": cmp, "identical": all(c[1] for c in checks)}  # fmt: skip
    return {"stages": _one("G-1 chat template: the passed file against the weights folder's own", checks,
                           time.perf_counter() - t0), "chat_template": block}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    hf = sub.add_parser("hf", help="the tokenizer side: token ids of the prompts with the folder's tokenizer")
    hf.add_argument("--model", required=True, help="the judge's repository name (the local cache) or its folder")
    hf.add_argument("--prompts", type=Path, required=True)
    hf.add_argument("--out", type=Path, required=True)
    hf.add_argument("--template", type=Path, help="the template file the serving configuration passes")
    a = ap.parse_args(argv)
    return hf_side(a.model, a.prompts, a.out, a.template)


if __name__ == "__main__":
    raise SystemExit(main())
