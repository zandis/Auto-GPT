"""Gate 5's cross-path kit: every exit of the box, driven with the planted people, judged on the bytes that leave.

A road is one exit as the product builds it (:data:`ROADS`): the model payload, a mail as handed to its transport (a
send and a reply), the support bundle as built, the enrolment report as downloaded, the sponsor pack as exported.
Each takes one planted text at a time (and a control text with no identifier), and gives back what left: every byte
string the exit wrote or sent, and whether the product refused.

The judge (:func:`judge`) reads what left as a receiver could: inside gzip, zip, tar, PDF and MIME, and through every
layer of percent, base64, quoted-printable, entity and backslash escape, zero-width and soft-hyphen removal and
width folding. It is written apart from the gate's own reading (``tb_common.output_gate``), so a decoding the gate
loses is still found here. A finding is one line, ``<invariant> road=<road> person=<letter> id=<identifier>
class=<class>: <what>``:

* ``survives``: a planted identifier (or a part of a name, or 12 or more digits of a pseudonym) is in a decoding of
  what left;
* ``refusal-left-bytes``: the exit refused, yet something left;
* ``control-refused``: the text with no identifier did not leave (an exit that refuses everything is no gate);
* ``ungated``: what left was not released by ``prepare_output`` for this exit (``output_gate.leave``).

Which product sites each road drives is :data:`ROAD_SITES`, read against the output-sink inventory
(``tools/output_sinks.py``): a site in an exit area with no road and no reviewed reason fails
``test_every_exit_site_has_a_road``.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import email
import functools
import gzip
import hashlib
import io
import json
import quopri
import re
import tarfile
import unicodedata
import urllib.parse
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy as email_policy
from pathlib import Path
from typing import Any

import pytest
from tb_common import output_gate

from tests import gate5_people as gp

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 22, 4, 31, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------ what left
@dataclass
class Outcome:
    plant: str  # the plant's id, or "control"
    placement: str  # where in the exit the text was put (a subject, a body, an attachment, a member)
    refused: bool
    left: list[tuple[str, bytes]] = field(default_factory=list)  # (where, bytes)
    released: set[str] = field(default_factory=set)  # sha256 of every byte string the gate released for the exit


class Spy:
    """Records the bytes ``output_gate.leave`` hands to an exit (by sha256), wherever the exit imported it from."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *modules: Any) -> None:
        self.seen: set[str] = set()
        real = output_gate.leave

        def leave(released: object, exit_name: str) -> bytes:
            data = real(released, exit_name)
            self.seen.add(hashlib.sha256(data).hexdigest())
            return data

        monkeypatch.setattr(output_gate, "leave", leave)
        for mod in modules:
            if hasattr(mod, "leave"):
                monkeypatch.setattr(mod, "leave", leave)

    def take(self) -> set[str]:
        out, self.seen = self.seen, set()
        return out


# ------------------------------------------------------------------------------------------------ the judge
_FORMAT = {chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) == "Cf"}


def _unformat(text: str) -> str:
    return "".join(c for c in text if c not in _FORMAT)


def _containers(data: bytes, where: str, depth: int = 0) -> Iterator[tuple[str, str]]:
    """``(where, text)`` of everything a receiver could open in ``data`` (written apart from the gate's reader)."""
    if depth < 5:
        if data.startswith(b"\x1f\x8b"):
            yield from _containers(gzip.decompress(data), where + ">gzip", depth + 1)
        elif zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    yield where + ">zip name", n
                    yield from _containers(z.read(n), f"{where}>{n}", depth + 1)
        elif data.startswith(b"%PDF"):
            from pypdf import PdfReader

            pdf = PdfReader(io.BytesIO(data))
            yield where + ">pdf", "\n".join(p.extract_text() or "" for p in pdf.pages)
        elif len(data) >= 512:
            for name, body in _tar_members(data):
                yield where + ">tar name", name
                if body is not None:
                    yield from _containers(body, f"{where}>{name}", depth + 1)
        if re.match(rb"[\x21-\x39\x3b-\x7e]+:", data) and (b"\n\n" in data or b"\r\n\r\n" in data):
            msg = email.message_from_bytes(data, policy=email_policy.default)
            for part in msg.walk():
                yield where + ">headers", "\n".join(f"{k}: {v}" for k, v in part.items())
                if not part.is_multipart():
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        yield from _containers(payload, where + ">part", depth + 1)
    yield where, data.decode("utf-8", errors="replace")


def _tar_members(data: bytes) -> list[tuple[str, bytes | None]]:
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            return [(m.name, fh.read() if (fh := tar.extractfile(m)) else None) for m in tar.getmembers()]
    except tarfile.TarError:
        return []


_B64 = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")


def _layers(text: str) -> list[tuple[str, str]]:
    """Each decoding a receiver could apply, one layer at a time, as ``(name, text)``."""
    out = [("fold", unicodedata.normalize("NFKC", _unformat(text)))]
    if "%" in text:
        out.append(("percent", urllib.parse.unquote(text)))
    if "&" in text:
        import html

        out.append(("entity", html.unescape(text)))
    if "\\x" in text:

        def xrun(m: re.Match[str]) -> str:
            raw = codecs.escape_decode(m.group(0).encode("ascii"))[0]
            return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else m.group(0)

        out.append(("x-escape", re.sub(r"(?:\\x[0-9a-fA-F]{2})+", xrun, text)))
    if "\\u" in text:
        joined = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text)
        out.append(("u-escape", joined.encode("utf-16", "surrogatepass").decode("utf-16", errors="replace")))
    if "=" in text:
        soft = text.replace("=\r\n", "").replace("=\n", "")
        out.append(("quoted-printable", quopri.decodestring(soft.encode("utf-8")).decode("utf-8", errors="replace")))

    def b64(m: re.Match[str]) -> str:
        run = m.group(0).rstrip("=")
        for alt in (run, run.replace("-", "+").replace("_", "/")):
            try:
                return base64.b64decode(alt + "=" * (-len(alt) % 4)).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
        return m.group(0)

    if _B64.search(text):
        out.append(("base64", _B64.sub(b64, text)))
    return [(n, t) for n, t in out if t != text]


def views(data: bytes, where: str) -> list[tuple[str, str]]:
    """``(chain, text)``: every container's text and every chain of decodings of it (at most seven layers)."""
    found: list[tuple[str, str]] = []
    for place, text in _containers(data, where):
        seen = {text}
        frontier = [(place, text)]
        found.append((place, text))
        for _ in range(7):
            nxt = []
            for chain, t in frontier:
                for name, d in _layers(t):
                    if d not in seen and len(seen) < 200:
                        seen.add(d)
                        nxt.append((f"{chain}>{name}", d))
            found += nxt
            frontier = nxt
    return found


def _digits_re(value: str) -> re.Pattern[str]:
    """The value's characters with any of the separators a person or a form puts between them."""
    chars = [re.escape(c) for c in value if c.isalnum()]
    return re.compile(r"[\s\-./()]?".join(chars), re.I)


def needles(person: gp.Person, ident: str) -> list[tuple[str, re.Pattern[str]]]:
    if ident == "name":
        return [(f"name part {i}", re.compile(re.escape(part), re.I)) for i, part in enumerate(person.parts)]
    value = person.value(ident)
    if ident == "pseudonym":
        # a pseudonym halved at a read limit still names its person to anyone holding the other half
        return [("pseudonym", re.compile(re.escape(value), re.I))] + [
            (f"pseudonym {k} digits", re.compile(f"{re.escape(value[:k])}|{re.escape(value[-k:])}", re.I))
            for k in (12,)
        ]
    if ident == "email":
        return [("email", re.compile(re.escape(value), re.I))]
    return [(ident, _digits_re(value))]


def survivors(o: Outcome, person: gp.Person, ident: str) -> list[str]:
    out: list[str] = []
    for where, data in o.left:
        for chain, text in views(data, where):
            for what, rx in needles(person, ident):
                if rx.search(text):
                    out.append(f"{what} in {chain}")
                    break
            if out:
                return out
    return out


def judge(road: str, cls: str, outcomes: list[Outcome], plants: dict[str, gp.Plant]) -> list[str]:
    found: list[str] = []
    for o in outcomes:
        if o.plant == "control":
            if o.refused or not o.left:
                found.append(f"control-refused road={road} person=- id=- class={cls}: {o.placement}")
            continue
        p = plants[o.plant]
        head = f"road={road} person={p.person.letter} id={p.ident} class={cls}"
        if o.refused and o.left:
            found.append(f"refusal-left-bytes {head}: {o.placement}")
        for line in survivors(o, p.person, p.ident):
            found.append(f"survives {head}: {o.placement}: {line}")
    ungated = [
        f"{o.placement}:{w}"
        for o in outcomes
        for w, d in o.left
        if hashlib.sha256(d).hexdigest() not in o.released and _EXIT_OF[road] != "model"
    ]
    if ungated:
        found.append(
            f"ungated road={road} person=- id=- class={cls}: {len(ungated)} of what left did not pass prepare_output"
        )
    return found


# ------------------------------------------------------------------------------------------------ the roads
Drive = Callable[[list[tuple[str, str]], Path, pytest.MonkeyPatch], list[Outcome]]


@dataclass(frozen=True)
class Road:
    name: str
    exit: str  # a key of output_gate.EXITS
    drive: Drive  # [(plant id or "control", text)] -> outcomes
    cannot: dict[str, str] = field(default_factory=dict)  # class -> why the exit has no way to carry it


def _model(items: list[tuple[str, str]], tmp: Path, mp: pytest.MonkeyPatch) -> list[Outcome]:
    """The payload the gateway sends a model, as the gate projects it for three purposes (as JSON on the wire)."""
    mp.setenv("TB_AUDIT_DIR", str(tmp / "audit"))
    out = []
    for pid, text in items:
        for purpose, data in (
            ("chart_text", {"text": text}),
            ("judge", {"criterion_text": "Adult with gout", "excerpts": [{"date": "2026-01-02", "text": text}]}),
            ("chat", {"messages": [{"role": "user", "content": f"Summarise: {text}"}]}),
        ):
            try:
                payload = output_gate.prepare_output(purpose, "model", data)
            except output_gate.OutputRefused:
                out.append(Outcome(pid, purpose, True))
                continue
            out.append(Outcome(pid, purpose, False, [(purpose, json.dumps(payload, ensure_ascii=False).encode())]))
    return out


def _gateway(tmp: Path, sent: list[bytes]) -> Any:
    from mail_gateway.gateway import Gateway
    from mail_gateway.store import MailDB
    from tb_common.audit import AuditLog
    from tb_common.config import Config, load_env, load_settings
    from tb_common.objstore import FsStore

    env = load_env(dotenv=tmp / "none.env", environ={"MAIL_FROM_ADDR": "trialbox@" + gp.INTERNAL})
    settings = load_settings(ROOT / "deploy" / "settings.example.yaml")
    return Gateway(
        Config(env=env, settings=settings),
        FsStore(tmp / "obj"),
        MailDB(),
        AuditLog(tmp / "audit", "Asia/Taipei"),
        lambda _frm, _to, data: sent.append(data),
        jobs=lambda req: pytest.fail("no job on this road"),
        secrets_dir=tmp,
        allow_phi_zip=True,
        outputs_current=lambda _job, _files: True,
    )


JOB = "01JB0000000000000000000000"


def _mail_send(items: list[tuple[str, str]], tmp: Path, mp: pytest.MonkeyPatch) -> list[Outcome]:
    """A send through ``Gateway.deliver`` with the text in the subject, in the body, and in an aggregate attachment."""
    from mail_gateway import gateway as gw_mod
    from tb_contracts import SendAttachment, SendRequest

    sent: list[bytes] = []
    gw = _gateway(tmp, sent)
    spy = Spy(mp, gw_mod)
    out = []
    for n, (pid, text) in enumerate(items):
        key = f"outputs/{JOB}/summary-{n}.csv"
        gw.store.put(key, f"count,note\n12,{text}\n".encode())
        for placement, kw in (
            ("subject", {"subject": f"Done · {text}", "body_md": "Done."}),
            ("body", {"subject": "Done · FEAS GZQO", "body_md": f"Results:\n\n{text}\n"}),
            (
                "attachment",
                {
                    "subject": "Done · FEAS GZQO",
                    "body_md": "Counts attached.",
                    "attachments": [SendAttachment(minio_key=key, filename="summary.csv", tag="aggregate")],
                },
            ),
        ):
            req = SendRequest(
                job_id=JOB, to=["pi@" + gp.INTERNAL], tag="aggregate", idempotency_key=f"g5-{n}-{placement}", **kw
            )
            before = len(sent)
            try:
                state = gw.deliver(req).state
            except Exception as exc:  # a request the gateway refuses before anything is built
                state = type(exc).__name__
            left = [(placement, d) for d in sent[before:]]
            out.append(Outcome(pid, placement, state != "sent", left, spy.take()))
    return out


def _mail_reply(items: list[tuple[str, str]], tmp: Path, mp: pytest.MonkeyPatch) -> list[Outcome]:
    """The gateway's reply to a refused request: it quotes the request's subject and gives the reason."""
    from mail_gateway import gateway as gw_mod
    from mail_gateway import intake

    sent: list[bytes] = []
    gw = _gateway(tmp, sent)
    spy = Spy(mp, gw_mod)
    out = []
    for n, (pid, text) in enumerate(items):
        for placement, subject, reason in (("quoted subject", text, "unknown command"), ("reason", "CASE GZQO", text)):
            mid = f"<g5-{n}-{placement[0]}@{gp.INTERNAL}>"
            m = intake.Inbound(b"", mid, "crc1@" + gp.INTERNAL, subject, None, True, "")
            before = len(sent)
            gw._reply(m, f"TrialBox could not process your message: {reason}.")
            left = [(placement, d) for d in sent[before:]]
            quoted = pid == "control" and any(gp.CONTROL.encode()[:20] in d.replace(b"=\n", b"") for _, d in left)
            out.append(Outcome(pid, placement, pid == "control" and not quoted, left, spy.take()))
    return out


def _bundle(items: list[tuple[str, str]], tmp: Path, mp: pytest.MonkeyPatch) -> list[Outcome]:
    """The support bundle as built (``tools/support_bundle.build``), one bundle per text: the text in an added file,
    and (for a cut) in a collected service log longer than the builder's read limit, across that limit."""
    from tools import support_bundle as sb

    mp.setattr(sb, "MAX_MEMBER", 4096)  # the read limit is four times this: a short log can cross it
    for k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR"):
        mp.delenv(k, raising=False)
    spy = Spy(mp, sb)
    out = []
    for n, (pid, text) in enumerate(items):
        box = tmp / f"box{n}"
        deploy, logs, audit = box / "deploy", box / "logs", box / "audit"
        (deploy / "secrets").mkdir(parents=True)
        audit.mkdir()
        env = ["TB_TZ=Asia/Taipei", f"TB_LOG_DIR={logs}", f"TB_AUDIT_HOST_DIR={audit}"]
        (deploy / ".env").write_text("\n".join(env) + "\n", encoding="utf-8")
        (deploy / "settings.yaml").write_text('mrn_regex: "^\\\\d{8}$"\n', encoding="utf-8")
        day = logs / "services" / "2026-11-21"
        day.mkdir(parents=True)
        limit = sb.MAX_MEMBER * 4
        if pid.startswith("cut_at_read_limit."):
            filler = ("worker idle; queue empty\n" * (limit // 25 + 1))[: limit - 20 - len(text) // 2]
            log = filler + "\n" + text + "\nnext line\n"
            placement = "service log across the read limit"
            add: list[Path] = []
        else:
            log = "worker idle; queue empty\n" * 4
            f = box / "case" / "case.txt"
            f.parent.mkdir()
            f.write_text(f"note: {text}\n", encoding="utf-8")
            placement = "added file"
            add = [f]
        with gzip.open(day / "orchestrator.log.gz", "wb") as fh:
            fh.write(log.encode("utf-8"))
        target = box / "usb"
        try:
            built = sb.build(deploy, target, add=add, commands=False, now=NOW, say=lambda _s: None)
        except sb.BundleRefused:
            left = [(p.name, p.read_bytes()) for p in target.glob("*")] if target.exists() else []
            out.append(Outcome(pid, placement, True, left, spy.take()))
            continue
        # each member as it left (a member is what the gate would release), and the archive's member names
        members = [(f"bundle:{n}", b or b"") for n, b in _tar_members(gzip.decompress(built.read_bytes()))]
        out.append(Outcome(pid, placement, False, members, spy.take()))
    return out


def _enrolment_report(items: list[tuple[str, str]], tmp: Path, mp: pytest.MonkeyPatch) -> list[Outcome]:
    """The study's enrolment report as downloaded (``lifecycle_api.report_files``, CSV and XLSX): the text as a
    withdrawal's typed reason and as a screen-fail reason."""
    from datacore import lifecycle as lc
    from orchestrator import lifecycle_api

    spy = Spy(mp, lifecycle_api)
    out = []
    for pid, text in items:
        rep: dict[str, Any] = {
            "counts": dict.fromkeys(lc.STATES, 3),
            "ever": dict.fromkeys(lc.STATES, 7),
            "months": [{"month": "2026-10", **dict.fromkeys(lc.STATES, 1)}],
            "screen_fail_reasons": {text: 1},
            "withdrawals": [{"record": "S-0001", "day": "2026-11-01", "reason": text}],
        }
        try:
            files = lifecycle_api.report_files(rep, "GZQO", "2026-11-22T04:31:00")
        except output_gate.OutputRefused:
            out.append(Outcome(pid, "report", True, [], spy.take()))
            continue
        left = [(k, v.encode("utf-8") if isinstance(v, str) else v) for k, v in files.items()]
        out.append(Outcome(pid, "report", False, left, spy.take()))
    return out


def _sponsor_pack(items: list[tuple[str, str]], tmp: Path, mp: pytest.MonkeyPatch) -> list[Outcome]:
    """The sponsor pack as exported (``console.app.build_sponsor_pack``): the text in an aggregate file the job made,
    and in the protocol's population as entered at import."""
    from console import app as console_app
    from tb_contracts import Job

    spy = Spy(mp, console_app)
    fields = {"job_id": JOB, "type": "FEAS", "ruleset": "GZQO", "requested_by": "pi@" + gp.INTERNAL}
    job = Job.model_validate({**fields, "state": "done", "received_at": NOW.isoformat()})
    out = []
    for pid, text in items:
        for placement, files, detail in (
            ("aggregate file", [("counts.csv", f"criterion,n\nage,12\nnote,{text}\n".encode())], {"title": "Gout"}),
            ("population", [("counts.csv", b"criterion,n\nage,12\n")], {"population": {"disease_stage": text}}),
        ):
            try:
                pack = console_app.build_sponsor_pack(job, files, detail, None)
            except output_gate.OutputRefused:
                out.append(Outcome(pid, placement, True, [], spy.take()))
                continue
            out.append(Outcome(pid, placement, False, [("sponsor_pack.zip", pack)], spy.take()))
    return out


_ONLY_BUNDLE = "only the support bundle reads a source up to a limit"
ROADS: tuple[Road, ...] = (
    Road("model", "model", _model, {"cut_at_read_limit": _ONLY_BUNDLE}),
    Road("mail_send", "mail", _mail_send, {"cut_at_read_limit": _ONLY_BUNDLE}),
    Road("mail_reply", "mail", _mail_reply, {"cut_at_read_limit": _ONLY_BUNDLE}),
    Road("support_bundle", "support", _bundle),
    Road("download_enrolment_report", "download", _enrolment_report, {"cut_at_read_limit": _ONLY_BUNDLE}),
    Road("export_sponsor_pack", "export", _sponsor_pack, {"cut_at_read_limit": _ONLY_BUNDLE}),
)
ROAD = {r.name: r for r in ROADS}
_EXIT_OF = {r.name: r.exit for r in ROADS}


def drive(road: Road, cls: str, tmp: Path, mp: pytest.MonkeyPatch) -> list[str]:
    plants = {p.id: p for p in gp.plants(cls)}
    items = [(p.id, p.text) for p in plants.values()] + [("control", gp.CONTROL)]
    return judge(road.name, cls, road.drive(items, tmp, mp), plants)


def summary(findings: list[str]) -> str:
    return "\n".join(sorted(findings))


# ------------------------------------------------------------------------------------------------ exit sites
#: the inventory's areas (``tools/output_sinks.py``) and the exit each is
AREA_EXIT = {
    "model": "model",
    "mail": "mail",
    "download": "download",
    "job file": "download",
    "support": "support",
    "package": "export",
}
#: (file, function) of each inventory site a road drives: the road runs that code, or the one door it sends through
ROAD_SITES: dict[tuple[str, str], str] = {
    **{
        ("services/mail_gateway/gateway.py", f): "mail_send"
        for f in ("Gateway._after_main", "Gateway._attempt", "Gateway.send")
    },
    ("services/mail_gateway/gateway.py", "Gateway._reply"): "mail_reply",
    ("services/mail_gateway/app.py", "send"): "mail_send",  # the route hands the request to Gateway.deliver
    ("services/mail_gateway/outbound.py", "smtp_transport.send"): "mail_send",  # the transport the gateway calls
    ("services/mail_gateway/outbound.py", "seven_zip"): "mail_send",  # an attachment packed inside the message
    # the orchestrator's mails reach the gateway's /send route (MailHttp) and leave through Gateway.deliver
    ("services/orchestrator/clients.py", "MailHttp.send"): "mail_send",
    **{
        ("services/orchestrator/core.py", f): "mail_send"
        for f in (
            "Orchestrator._deliver",
            "Orchestrator._failed_mail",
            "Orchestrator._received_mail",
            "Orchestrator.send",
        )
    },
    ("services/orchestrator/app.py", "notice"): "mail_send",
    ("services/orchestrator/lifecycle_api.py", "router.get_report_file"): "download_enrolment_report",
    ("services/console/app.py", "build_sponsor_pack"): "export_sponsor_pack",
    ("services/console/app.py", "create_app.sponsor_pack"): "export_sponsor_pack",
}
#: inventory sites in an exit area that cannot carry patient text, each with why (a reviewed reason, as gate 2's
#: non-kinds: one no longer found fails, so the table cannot rot)
NOT_PATIENT_EXITS: dict[tuple[str, str], str] = {
    ("libs/tb_common/refdata.py", "Cassette.body"): "packs reference data (code lists), never a patient's record",
    ("libs/tb_common/refdata.py", "pack_tar"): "packs reference data (code lists), never a patient's record",
    ("services/console/phone.py", "register.favicon"): "the installed icon file",
    ("services/orchestrator/setup_api.py", "router.template"): "a blank set-up template shipped with the box",
}


@functools.cache
def sites() -> tuple[Any, ...]:
    """The output-sink inventory of this tree (read once per process)."""
    from tools.output_sinks import inventory

    return tuple(sorted(set(inventory())))


def bundle_sites() -> set[tuple[str, str]]:
    """The support bundle builder's own sites: every function of it drives into the one archive the road builds."""
    return {(s.file, s.function) for s in sites() if s.area == "support"}


def uncovered() -> list[str]:
    """Inventory sites in an exit area with no road and no reviewed reason."""
    support = bundle_sites()
    out = []
    for s in sites():
        if s.area in ("model", "log"):
            continue  # the model exit is the gateway's (a test keeps every model call behind it); logs are H-79's
        key = (s.file, s.function)
        if key in ROAD_SITES or key in NOT_PATIENT_EXITS or key in support:
            continue
        out.append(f"{AREA_EXIT.get(s.area, '?' + s.area)}: {s.file} {s.function} ({s.sink})")
    return out
