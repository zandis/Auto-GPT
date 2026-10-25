"""CONSENT and RELEASE: the consent explainer (spec v4 Phase B, "Consent Explainer"; agents draft, humans approve).

``CONSENT <study> [lang=en,ja,zh-TW]`` with the IRB-approved informed-consent form (ICF) attached drafts a
plain-language explainer: key facts by section (purpose, procedures, risks, benefits, rights, ...) and a few teach-back
questions, in every requested language. Three checks run before anyone sees it:

1. **Grounding (program).** Every statement carries a verbatim ICF quote; a quote not found in the ICF removes the
   statement, and a number the quote does not contain removes it too.
2. **Second model.** The verifier build (Gemma 4 next to the gpt-oss-120b judge on the Spark) checks each statement in
   each language against its quote and back-translates it into English. Anything it does not call ``supported`` is
   held back. Without a verifier the statements are marked ``unverified`` and the review sheet says so.
3. **Human.** The draft goes to the requester as a review sheet plus DRAFT patient pages. Nothing is released until a
   reviewer (the coordinator or PI, ``permissions.RELEASE``, default ``reviewers``) sends ``RELEASE <job id>``
   (optionally ``drop=I03,Q2`` to remove items, ``keep=I07`` to include a held item) or presses Release in the console.

The explainer is a reading aid. It is not the consent form, not a signature and not part of the regulated consent
record: every page says so in its own language, and the site's consent process and eConsent system stay as they are.
The ICF is study material (D1), never patient data, so the outputs are ``aggregate``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from tb_common.crypto import sha256_bytes
from tb_common.llm import LlmClient, LlmError
from tb_contracts import JobOutput, ParseRequest

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_stamp
from orchestrator.reports import consent_html

SCHEMA = "trialbox.consent@1"
LANGS = ("en", "ja", "zh-TW")
LANG_NAMES = {"en": "English", "ja": "Japanese", "zh-TW": "Traditional Chinese (Taiwan)"}
SECTIONS = (
    "purpose",
    "procedures",
    "duration",
    "risks",
    "benefits",
    "alternatives",
    "obligations",
    "rights",
    "privacy",
    "costs",
    "contacts",
)
REQUIRED = ("purpose", "procedures", "risks", "benefits", "alternatives", "rights", "contacts")
ICF_EXT = (".pdf", ".docx", ".txt", ".md")
MAX_ICF_CHARS = 60_000
MIN_QUOTE = 12
# reading-ease hint per sentence: words (en) or characters (ja, zh-TW)
LONG_SENTENCE = {"en": 25, "ja": 60, "zh-TW": 50}
_ID = re.compile(r"^(?:I\d{2}|Q\d)$")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_SENT = re.compile(r"(?<=[.!?。！？])\s*")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-"})


# ------------------------------------------------------------------------------------------------ text helpers
def norm(text: str) -> str:
    """Comparison form: NFKC, unified quotes and dashes, collapsed white space, lower case."""
    t = unicodedata.normalize("NFKC", text).translate(_QUOTES).lower()
    t = re.sub(r"[*_`#>]+", " ", t)  # Markdown emphasis and headings in .md consent forms
    return re.sub(r"\s+", " ", t).strip()


def numbers(text: str) -> list[str]:
    return [n.replace(",", "") for n in _NUM.findall(unicodedata.normalize("NFKC", text))]


def quote_found(quote: str, icf_norm: str) -> bool:
    """The quote sits verbatim in the ICF; an elided quote (``...``) must match piece by piece, in order."""
    pieces = [norm(p).strip(" .,;:\"'") for p in re.split(r"\.{3}|…", quote)]
    pieces = [p for p in pieces if p]
    if not pieces or sum(len(p) for p in pieces) < MIN_QUOTE:
        return False
    pos = 0
    for p in pieces:
        at = icf_norm.find(p, pos)
        if at < 0:
            return False
        pos = at + len(p)
    return True


def numbers_ok(text: str, source: str) -> bool:
    """Every number in ``text`` appears in ``source`` (the quote, or the source-language text plus its quote)."""
    have = set(numbers(source))
    return all(n in have for n in numbers(text))


def translation_numbers_ok(source: str, translated: str, quote: str) -> bool:
    """No number lost or changed in translation; a new number is allowed only when the quote has it or it is a small
    count a language writes as a digit ("once a week" is 週1回, "three groups" is 3つ)."""
    have = numbers(translated)
    if any(n not in have for n in numbers(source)):
        return False
    known = set(numbers(source)) | set(numbers(quote))
    return all(n in known or (n.isdigit() and int(n) <= 12) for n in have)


def long_sentences(text: str, lang: str) -> int:
    limit = LONG_SENTENCE.get(lang, 25)
    out = 0
    for s in (x for x in _SENT.split(text) if x.strip()):
        size = len(s.split()) if lang == "en" else len(re.sub(r"\s", "", s))
        out += size > limit
    return out


def detect_language(text: str) -> str:
    kana = len(re.findall(r"[぀-ヿ]", text))
    han = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if kana > 20 and kana * 10 > han:
        return "ja"
    if han > latin / 3:
        return "zh-TW"
    return "en"


def parse_langs(raw: str | None) -> list[str]:
    if not raw:
        return list(LANGS)
    out: list[str] = []
    for tok in raw.split(","):
        code = {"en": "en", "ja": "ja", "jp": "ja", "zh": "zh-TW", "zh-tw": "zh-TW", "tw": "zh-TW"}.get(tok.lower())
        if code is None:
            raise StepFailed("received", f"lang={tok}: supported languages are en, ja, zh-TW")
        if code not in out:
            out.append(code)
    return out


def ids(raw: str | None) -> list[str]:
    out = [t.strip().upper() for t in (raw or "").split(",") if t.strip()]
    bad = [t for t in out if not _ID.match(t)]
    if bad:
        raise StepFailed("release", f"unknown item id(s) {', '.join(bad)}: use the ids on the review sheet (I03, Q2)")
    return out


# ------------------------------------------------------------------------------------------------ the ICF
def paragraphs_from_text(text: str) -> list[dict[str, str]]:
    """Paragraph ids P1..Pn in reading order; a Markdown heading becomes the heading of the paragraphs under it."""
    out: list[dict[str, str]] = []
    heading = ""
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        b = block.strip()
        if not b:
            continue
        if b.startswith("#") and "\n" not in b:
            heading = b.lstrip("#").strip()
            continue
        out.append({"id": f"P{len(out) + 1}", "heading": heading, "text": re.sub(r"\s*\n\s*", " ", b)})
    return out


def read_icf(ctx: Ctx) -> tuple[str, str, list[dict[str, str]]]:
    files = [f for f in ctx.job.inputs or [] if f.filename.lower().endswith(ICF_EXT)]
    if not files:
        raise StepFailed("received", "Attach the IRB-approved informed-consent form (PDF, DOCX, TXT or MD).")
    files.sort(key=lambda f: (not f.filename.lower().endswith((".pdf", ".docx")), f.filename))
    f = files[0]
    data = ctx.input_bytes(f)
    ctx.state("parsing")
    if f.filename.lower().endswith((".txt", ".md")):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        parsed = ctx.services.parser.parse(ParseRequest(minio_key=f.minio_key, job_id=ctx.job.job_id))
        text = "\n\n".join(
            (f"# {s.title}\n\n" if s.title else "") + re.sub(r"\n(?=\S)", "\n\n", s.text) for s in parsed.sections
        )
    paras = paragraphs_from_text(text)
    if sum(len(p["text"]) for p in paras) < 200:
        raise StepFailed("parsing", f"{f.filename}: no readable consent text found (scanned PDF without OCR?)")
    if sum(len(p["text"]) for p in paras) > MAX_ICF_CHARS:
        raise StepFailed("parsing", f"{f.filename}: longer than {MAX_ICF_CHARS} characters; attach the ICF only")
    return f.filename, sha256_bytes(data), paras


# ------------------------------------------------------------------------------------------------ contact masking
class ContactMask:
    """Names and telephone numbers in the ICF (the study contacts) become tokens such as ``[[CONTACT_A]]`` before any
    model sees the text, and are put back afterwards. The gateway's PHI tripwire refuses a call carrying a name or a
    phone number, whoever it belongs to; and a number put back by the program cannot be mistyped by a model."""

    def __init__(self, mrn_regex: str | None = None) -> None:
        from guard.guard import Guard

        self.guard = Guard(mrn_regex)
        self.tokens: dict[str, str] = {}  # original -> token

    def _token(self, original: str) -> str:
        if original not in self.tokens:
            n = len(self.tokens)
            label = chr(65 + n % 26) * (1 + n // 26)
            self.tokens[original] = f"[[CONTACT_{label}]]"
        return self.tokens[original]

    def mask(self, text: str) -> str:
        from tb_common import phi_guard

        spans = [(f.start, f.end) for f in self.guard.detect(text)]
        for pat in (phi_guard.PHONE, phi_guard.EN_NAME):
            spans += [(m.start(), m.end()) for m in pat.finditer(text)]
        for name in phi_guard._cjk_names(text):
            spans += [(m.start(), m.end()) for m in re.finditer(re.escape(name), text)]
        merged: list[tuple[int, int]] = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        tokens = [self._token(text[a:b]) for a, b in merged]  # numbered in reading order
        for (a, b), token in reversed(list(zip(merged, tokens, strict=True))):
            text = text[:a] + token + text[b:]
        return text

    def unmask(self, value: Any) -> Any:
        if isinstance(value, str):
            for original, token in self.tokens.items():
                value = value.replace(token, original)
            return value
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        return value


# ------------------------------------------------------------------------------------------------ drafting
@dataclass
class Models:
    draft: LlmClient
    verifier: LlmClient | None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def chat(self, llm: LlmClient, prompt: str, variables: dict[str, Any], job_id: str) -> dict[str, Any]:
        res = llm.chat_json(prompt, variables, job_id=job_id)  # data class: TB_DATA_CLASS, else D1 (phi: false)
        self.calls += 1
        self.tokens_in += res.tokens_in
        self.tokens_out += res.tokens_out
        return dict(res.data)


def draft(
    m: Models, study: str, paras: list[dict[str, str]], source: str, langs: list[str], job_id: str
) -> dict[str, Any]:
    """The explainer record: canonical items in the ICF language, translations, and every check's result."""
    icf_norm = norm(" ".join(p["text"] for p in paras))
    para_ids = {p["id"] for p in paras}
    raw = m.chat(
        m.draft,
        "consent_explain",
        {"study": study, "language": source, "language_name": LANG_NAMES[source], "paragraphs": paras},
        job_id,
    )
    items: list[dict[str, Any]] = []
    for i, it in enumerate(raw.get("items") or [], start=1):
        text, quote = str(it.get("text", "")).strip(), str(it.get("quote", "")).strip()
        removed = None
        if not quote_found(quote, icf_norm):
            removed = "quote not found in the consent form"
        elif not numbers_ok(text, quote):
            removed = "a number is not in the quote"
        items.append(
            {
                "id": f"I{i:02d}",
                "section": it.get("section") if it.get("section") in SECTIONS else "purpose",
                "quote": quote,
                "para": it.get("para") if it.get("para") in para_ids else "",
                "removed": removed,
                "texts": {source: {"text": text}},
            }
        )
    questions: list[dict[str, Any]] = []
    for i, q in enumerate(raw.get("questions") or [], start=1):
        qt, ans, quote = (str(q.get(k, "")).strip() for k in ("question", "answer", "quote"))
        removed = None
        if not quote_found(quote, icf_norm):
            removed = "quote not found in the consent form"
        elif not numbers_ok(ans, quote):
            removed = "a number is not in the quote"
        questions.append(
            {
                "id": f"Q{i}",
                "quote": quote,
                "para": q.get("para") if q.get("para") in para_ids else "",
                "removed": removed,
                "texts": {source: {"question": qt, "answer": ans}},
            }
        )
    issues: list[str] = []
    for lang in langs:
        if lang == source:
            continue
        try:
            _translate(m, items, questions, source, lang, job_id)
        except (LlmError, KeyError, ValueError) as exc:
            issues.append(f"{lang}: translation failed ({type(exc).__name__}); language left out")
    done_langs = [lang for lang in langs if lang == source or any(lang in it["texts"] for it in items)]
    verified = m.verifier is not None
    for lang in done_langs:
        checks: dict[str, dict[str, Any]] = {}
        if m.verifier is not None:
            try:
                checks = _verify(m, m.verifier, items, questions, lang, job_id)
            except (LlmError, KeyError, ValueError) as exc:
                issues.append(f"{lang}: second-model check failed ({type(exc).__name__}); statements unverified")
        for rec in (*items, *questions):
            t = rec["texts"].get(lang)
            if t is None:
                continue
            body = t.get("text") or f"{t.get('question', '')} {t.get('answer', '')}"
            src = rec["texts"][source]
            src_body = src.get("text") or f"{src.get('question', '')} {src.get('answer', '')}"
            t["long_sentences"] = long_sentences(body, lang)
            c = checks.get(rec["id"])
            if c is None:
                t.update(status="unverified" if not verified or not checks else "held", verdict=None)
                if verified and checks:
                    t["problem"] = "the second model returned no verdict"
            else:
                t.update(
                    status="ok" if c["verdict"] == "supported" else "held",
                    verdict=c["verdict"],
                    back_translation=c["back_translation"],
                    problem=c["problem"],
                )
            if lang != source and not translation_numbers_ok(src_body, body, rec["quote"]):
                t.update(status="held", problem="a number differs from the source statement")
    present = {it["section"] for it in items if not it["removed"]}
    return {
        "items": items,
        "questions": questions,
        "languages": done_langs,
        "missing_sections": [s for s in REQUIRED if s not in present],
        "issues": issues,
        "verified": verified,
    }


def _translate(
    m: Models, items: list[dict[str, Any]], questions: list[dict[str, Any]], source: str, target: str, job: str
) -> None:
    live_items = [it for it in items if not it["removed"]]
    live_qs = [q for q in questions if not q["removed"]]
    out = m.chat(
        m.draft,
        "consent_translate",
        {
            "source": source,
            "target": target,
            "source_name": LANG_NAMES[source],
            "target_name": LANG_NAMES[target],
            "items": [{"id": it["id"], "text": it["texts"][source]["text"]} for it in live_items],
            "questions": [{"id": q["id"], **q["texts"][source]} for q in live_qs],
        },
        job,
    )
    by_item = {str(x["id"]): str(x["text"]).strip() for x in out.get("items") or []}
    by_q = {str(x["id"]): x for x in out.get("questions") or []}
    for it in live_items:
        if by_item.get(it["id"]):
            it["texts"][target] = {"text": by_item[it["id"]]}
    for q in live_qs:
        x = by_q.get(q["id"])
        if x is not None and str(x.get("question", "")).strip():
            q["texts"][target] = {"question": str(x["question"]).strip(), "answer": str(x.get("answer", "")).strip()}


def _verify(
    m: Models, llm: LlmClient, items: list[dict[str, Any]], questions: list[dict[str, Any]], lang: str, job: str
) -> dict[str, dict[str, Any]]:
    entries = [
        {"id": it["id"], "quote": it["quote"], "text": it["texts"][lang]["text"]}
        for it in items
        if not it["removed"] and lang in it["texts"]
    ] + [
        {"id": q["id"], "quote": q["quote"], "text": f"{q['texts'][lang]['question']} — {q['texts'][lang]['answer']}"}
        for q in questions
        if not q["removed"] and lang in q["texts"]
    ]
    if not entries:
        return {}
    out = m.chat(llm, "consent_verify", {"language": lang, "language_name": LANG_NAMES[lang], "entries": entries}, job)
    return {
        str(c["id"]): {
            "verdict": str(c["verdict"]),
            "back_translation": str(c.get("back_translation", "")),
            "problem": str(c.get("problem", "")),
        }
        for c in out.get("checks") or []
    }


# ------------------------------------------------------------------------------------------------ release rules
def released_view(rec: dict[str, Any], lang: str, drop: list[str], keep: list[str]) -> dict[str, Any]:
    """What a patient page in ``lang`` shows: statements and questions that passed (or that a reviewer kept)."""

    def shown(x: dict[str, Any]) -> bool:
        t = x["texts"].get(lang)
        if x["removed"] or t is None or x["id"] in drop:
            return False
        return t.get("status") in ("ok", "unverified") or (x["id"] in keep and t.get("status") == "held")

    return {
        "items": [x for x in rec["items"] if shown(x)],
        "questions": [x for x in rec["questions"] if shown(x)],
    }


def counts(rec: dict[str, Any]) -> dict[str, int]:
    allx = rec["items"] + rec["questions"]
    statuses = [t.get("status") for x in allx if not x["removed"] for t in x["texts"].values()]
    return {
        "items": len(rec["items"]),
        "questions": len(rec["questions"]),
        "removed": sum(1 for x in allx if x["removed"]),
        "held": statuses.count("held"),
        "unverified": statuses.count("unverified"),
        "ok": statuses.count("ok"),
    }


# ------------------------------------------------------------------------------------------------ scenarios
def subject(study: str, cmd: str, outcome: str, detail: str, job_id: str) -> str:
    """Study and outcome first, the job id last (the UX thread's subject format)."""
    return f"[{study}] {cmd} {outcome}: {detail} · job {job_id}"


def lang_label(langs: list[str]) -> str:
    return ", ".join(lang.upper() if lang != "zh-TW" else "zh-TW" for lang in langs)


def models(ctx: Ctx) -> Models:
    if ctx.services.llm is None:
        raise StepFailed("received", "No language model is configured on this box (LLM_BASE_URL / TB_GATEWAY_URL).")
    return Models(ctx.services.llm, ctx.services.verifier)


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    study = (job.ruleset or "").upper()
    if not study:
        raise StepFailed("received", "CONSENT needs a study code: CONSENT GZQO lang=en,ja,zh-TW")
    langs = parse_langs((job.options or {}).get("lang"))
    filename, icf_sha, paras = read_icf(ctx)
    source = detect_language(" ".join(p["text"] for p in paras))
    if source not in langs:
        langs = [source, *langs]
    m = models(ctx)
    ctx.state("running")
    mask = ContactMask(ctx.cfg.settings.mrn_regex)
    masked = [{**p, "text": mask.mask(p["text"]), "heading": mask.mask(p["heading"])} for p in paras]
    body = mask.unmask(draft(m, study, masked, source, langs, job.job_id))
    rec: dict[str, Any] = {
        "schema": SCHEMA,
        "study": study,
        "job_id": job.job_id,
        "created": job_stamp(ctx),
        "site": ctx.cfg.settings.site.id,
        "requested_by": job.requested_by,
        "icf": {"filename": filename, "sha256": icf_sha, "language": source, "paragraphs": len(paras)},
        "source_language": source,
        "models": {"draft": m.draft.model, "verifier": m.verifier.model if m.verifier else None},
        **body,
        "release": None,
    }
    rec["counts"] = counts(rec)
    ctx.state("reporting")
    to = [job.requested_by]
    outputs = [ctx.publish(f"consent_{study}.json", _json(rec), "aggregate", to)]
    outputs.append(ctx.publish(f"consent_{study}_review.html", consent_html.review(rec), "aggregate", to))
    for lang in rec["languages"]:
        page = consent_html.patient(rec, lang, released_view(rec, lang, [], []), release=None)
        outputs.append(ctx.publish(f"consent_{study}_{lang}_DRAFT.html", page, "aggregate", to))
    c = counts(rec)
    ctx.metrics(llm_calls=m.calls, tokens_in=m.tokens_in, tokens_out=m.tokens_out)
    summary = _draft_mail(rec, c)
    return Outcome(
        summary_md=summary,
        deliveries=[
            Delivery(
                to=to,
                outputs=[o for o in outputs if not o.filename.endswith(".json")],
                subject=subject(study, "CONSENT", "draft ready for review", lang_label(rec["languages"]), job.job_id),
                body_md=summary,
            )
        ],
    )


def release(ctx: Ctx) -> Outcome:
    job = ctx.job
    target = (job.options or {}).get("target", "")
    src = ctx.orch.db.get(target) if target else None
    if src is None or src.type != "CONSENT":
        raise StepFailed("release", f"{target or 'the job'} is not a consent explainer job: RELEASE <CONSENT job id>")
    if src.state != "done":
        raise StepFailed("release", f"consent job {target} is {src.state}, not done; nothing to release")
    study = (src.ruleset or "").upper()
    rec_out = next((o for o in src.outputs or [] if o.filename == f"consent_{study}.json"), None)
    if rec_out is None:
        raise StepFailed("release", f"consent job {target} has no explainer record")
    rec = json.loads(ctx.store.get(rec_out.minio_key))
    opts = job.options or {}
    drop, keep = ids(opts.get("drop")), ids(opts.get("keep"))
    known = {x["id"]: x for x in rec["items"] + rec["questions"]}
    unknown = [i for i in drop + keep if i not in known]
    if unknown:
        raise StepFailed("release", f"no item {', '.join(unknown)} in consent job {target}")
    not_keepable = [i for i in keep if known[i]["removed"]]
    if not_keepable:
        raise StepFailed(
            "release", f"{', '.join(not_keepable)}: removed because the quote is not in the consent form; cannot keep"
        )
    ctx.update(ruleset=study)
    ctx.state("reporting")
    rel = {"by": job.requested_by, "at": job_stamp(ctx), "job_id": job.job_id, "drop": drop, "keep": keep}
    rec = {**rec, "release": rel}
    to = sorted({job.requested_by, src.requested_by} - {"scheduler", "system"})
    outputs: list[JobOutput] = []
    shown: dict[str, int] = {}
    for lang in rec["languages"]:
        view = released_view(rec, lang, drop, keep)
        shown[lang] = len(view["items"]) + len(view["questions"])
        if not view["items"]:
            continue
        page = consent_html.patient(rec, lang, view, release=rel)
        outputs.append(ctx.publish(f"consent_{study}_{lang}.html", page, "aggregate", to))
    if not outputs:
        raise StepFailed("release", "every statement was removed or held back; nothing to release")
    ctx.publish(f"consent_{study}_released.json", _json(rec), "aggregate", to)
    ctx.orch.audit.append(
        "consent.release",
        job_id=job.job_id,
        ruleset=study,
        actor=job.requested_by,
        output_sha=",".join(o.sha256 for o in outputs),
        detail={"consent_job": target, "drop": drop, "keep": keep, "languages": list(shown)},
    )
    langs = [lang for lang in rec["languages"] if shown.get(lang)]
    summary = (
        f"Consent explainer for **{study}** released by {job.requested_by} (consent job `{target}`).\n\n"
        + "\n".join(f"- {lang}: {shown[lang]} statements and questions" for lang in langs)
        + (f"\n- dropped by the reviewer: {', '.join(drop)}" if drop else "")
        + (f"\n- held items kept by the reviewer: {', '.join(keep)}" if keep else "")
        + "\n\n"
        + consent_html.DISCLAIMER["en"]
    )
    return Outcome(
        summary_md=summary,
        deliveries=[
            Delivery(
                to=to,
                outputs=outputs,
                subject=subject(study, "CONSENT", "released", lang_label(langs), job.job_id),
                body_md=summary,
            )
        ],
    )


def _draft_mail(rec: dict[str, Any], c: dict[str, int]) -> str:
    held = sorted(
        {x["id"] for x in rec["items"] + rec["questions"] for t in x["texts"].values() if t.get("status") == "held"}
    )
    lines = [
        f"Consent explainer **draft** for **{rec['study']}** from `{rec['icf']['filename']}` "
        f"({lang_label(rec['languages'])}). Nothing is given to patients until a reviewer releases it.",
        "",
        f"- {c['items']} statements and {c['questions']} teach-back questions drafted",
        f"- removed by the grounding check (quote not in the consent form): {c['removed']}",
        f"- held back by the second model: {', '.join(held) if held else 'none'}",
    ]
    if not rec["verified"]:
        lines.append("- second model: **not configured**; check every statement against its quote yourself")
    if rec["missing_sections"]:
        lines.append(f"- sections with no statement: {', '.join(rec['missing_sections'])}")
    lines += [f"- {i}" for i in rec["issues"]]
    lines += [
        "",
        "Open the review sheet, compare each statement with its consent-form quote, then send "
        f"`RELEASE {rec['job_id']}` (add `drop=I03,Q2` to remove items or `keep=I07` to include a held item), "
        "or press **Release** on the job page in the console.",
        "",
        consent_html.DISCLAIMER["en"],
    ]
    return "\n".join(lines)


def _json(rec: dict[str, Any]) -> bytes:
    return json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
