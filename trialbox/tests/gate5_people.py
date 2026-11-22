"""Gate 5's synthetic people and the ways their identifiers are written (the cross-path test of what may leave the box,
review 2026-11-22 §3.2 and §3.5, as the owner ruled for gate 5).

Four made-up people, one per way a name is written in a note without a label (Japanese, Traditional Chinese, English,
and a romanised Japanese name with macrons). Each has a name, a chart number, a phone number, an e-mail address, a
national identifier and a pseudonym. The numbers are made at run time from a fixed seed (the same every run, written
nowhere in the tree); none is a real person's.

Every identifier is planted in every encoding class the two reviews of #1314 list (``CLASSES``): percent-encoding in
one to five layers and between ``%2F`` boundaries, base64 and base64url (also inside JSON, as a sign-in ``state``
carries it), quoted-printable with a soft break and beside ``=C2=B0``, HTML entities with and without ``;``, ``\\x``
and ``\\u`` escapes, a zero-width joiner or space and a soft hyphen inside it, a decomposed macron, full-width digits,
a pseudonym cut at a read limit and one with an encoded digit beside it, and a chart number written as a JSON
integer. A class says which identifiers it applies to.
"""

from __future__ import annotations

import base64
import json
import quopri
import random
import unicodedata
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

from tb_common.crypto import pid_for_mrn

KEY = b"gate5-synthetic-site-key"
SEED = 20261122
IDENTIFIERS = ("name", "chart", "phone", "email", "national_id", "pseudonym")
INTERNAL = "hospa.test"  # the example settings' internal domain: an address there is staff, never a patient


@dataclass(frozen=True)
class Person:
    letter: str
    lang: str
    name: str  # as the record writes it
    parts: tuple[str, ...]  # the name and each of its parts: none may survive
    sentence: str  # the name in a sentence, with no label
    chart: str
    phone: str
    email: str
    national_id: str
    pseudonym: str

    def snippet(self, ident: str) -> str:
        """The identifier in the words a note, a log line or a mail would put around it (no ``name:`` label)."""
        return {
            "name": self.sentence,
            "chart": f"follow-up for {self.chart} next week",
            "phone": f"call back {self.phone} today",
            "email": f"e-mail: {self.email}",
            "national_id": f"ID {self.national_id} on file",
            "pseudonym": f"/patients/{self.pseudonym}/notes",
        }[ident]

    def value(self, ident: str) -> str:
        return self.name if ident == "name" else str(getattr(self, ident))


def _my_number(rng: random.Random) -> str:
    """Twelve digits whose last is the check digit of the first eleven (a Japanese individual number's form)."""
    body = "".join(str(rng.randrange(10)) for _ in range(11))
    rev = [int(c) for c in body][::-1]
    rest = sum(p * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(rev, 1)) % 11
    return body + str(0 if rest <= 1 else 11 - rest)


def _tw_id(rng: random.Random) -> str:
    return (
        rng.choice("ABCDEFGHJKLMNPQRSTUVXYWZIO") + rng.choice("12") + "".join(str(rng.randrange(10)) for _ in range(8))
    )


def people() -> list[Person]:
    rng = random.Random(SEED)

    def digits(n: int) -> str:
        return "".join(str(rng.randrange(10)) for _ in range(n))

    def chart() -> str:
        return "7" + digits(7)  # eight digits: the example settings' chart-number rule

    rows = [
        ("A", "ja", "佐藤花子", ("佐藤花子", "佐藤", "花子"), "患者は佐藤花子。既往歴に糖尿病。"),
        ("B", "zh-TW", "陳美玲", ("陳美玲", "美玲"), "病人陳美玲今天回診，血壓穩定。"),
        ("C", "en", "John Smith", ("John Smith", "Smith"), "Patient John Smith, 65M, presents with chest pain."),
        ("D", "en", "Yūko Satō", ("Yūko Satō", "Satō", "Yūko"), "Patient Yūko Satō was admitted for review."),
    ]
    out = []
    for letter, lang, name, parts, sentence in rows:
        c = chart()
        phone = (
            f"0{rng.choice('789')}0-{digits(4)}-{digits(4)}"
            if lang != "zh-TW"
            else f"09{digits(2)}-{digits(3)}-{digits(3)}"
        )
        nid = _tw_id(rng) if lang == "zh-TW" else _my_number(rng)
        out.append(
            Person(
                letter, lang, name, parts, sentence, c, phone, f"pt{digits(5)}@example.org", nid, pid_for_mrn(KEY, c)
            )
        )
    return out


# ------------------------------------------------------------------------------------------------ encoding classes
def _pct(layers: int) -> Callable[[str], str]:
    def enc(s: str) -> str:
        for _ in range(layers):
            s = urllib.parse.quote(s, safe="")
        return s

    return enc


def _mid(s: str, mark: str) -> str:
    """``mark`` inside the identifier's own value (the middle of the snippet's longest word)."""
    word = max(s.split(" "), key=len)
    at = s.index(word) + len(word) // 2
    return s[:at] + mark + s[at:]


def _fullwidth(s: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if c.isascii() and c.isalnum() else c for c in s)


def _state(s: str) -> str:
    blob = json.dumps({"next": s, "nonce": "n0nce"}, ensure_ascii=False).encode()
    return "GET /signin/callback?state=" + base64.urlsafe_b64encode(blob).decode().rstrip("=") + "&code=abc"


@dataclass(frozen=True)
class Class:
    id: str
    encode: Callable[[Person, str], str]  # (person, identifier) -> the text planted
    applies: frozenset[str] = frozenset(IDENTIFIERS)
    people: frozenset[str] = frozenset("ABCD")


def _on(f: Callable[[str], str]) -> Callable[[Person, str], str]:
    return lambda p, ident: f(p.snippet(ident))


def _value_on(f: Callable[[str], str]) -> Callable[[Person, str], str]:
    """The class applied to the identifier's value only, the words around it as they are."""
    return lambda p, ident: p.snippet(ident).replace(p.value(ident), f(p.value(ident)))


CLASSES: tuple[Class, ...] = (
    Class("plain", _on(lambda s: s)),
    # the name after its label, as a form or a header writes it: the recognisers mask it; none of it may stay
    Class("labelled_name", lambda p, _i: f"Name: {p.name}. Seen in clinic today.", frozenset({"name"})),
    *(Class(f"percent{n}", _on(_pct(n))) for n in range(1, 6)),
    Class("percent_2f_boundary", _value_on(lambda v: "%2F" + urllib.parse.quote(v, safe="") + "%2F")),
    Class("base64", _on(lambda s: base64.b64encode(s.encode()).decode())),
    Class("base64url", _on(lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("="))),
    Class("base64_json_state", _on(_state)),
    Class("quoted_printable", _on(lambda s: quopri.encodestring(s.encode()).decode())),
    Class("qp_soft_break", _value_on(lambda v: _mid(v, "=\n"))),
    Class("qp_degree_sign", _value_on(lambda v: "n=C2=B0" + v)),
    Class("html_entities", _on(lambda s: "".join(f"&#{ord(c)};" for c in s))),
    Class("html_entities_no_semicolon", _on(lambda s: "".join(f"&#x{ord(c):x}" for c in s) + " ")),
    Class("x_escape", _on(lambda s: "".join(f"\\x{b:02x}" for b in s.encode()))),
    Class("u_escape", _on(lambda s: "".join(f"\\u{ord(c):04x}" for c in s))),
    Class("zero_width_joiner", _value_on(lambda v: _mid(v, "\u200d"))),
    Class("zero_width_space", _value_on(lambda v: _mid(v, "\u200b"))),
    Class("soft_hyphen", _value_on(lambda v: _mid(v, "\u00ad"))),
    Class("decomposed_macron", _on(lambda s: unicodedata.normalize("NFD", s)), frozenset({"name"}), frozenset("D")),
    Class("fullwidth_digits", _value_on(_fullwidth), frozenset({"chart", "phone", "national_id", "pseudonym"})),
    Class("encoded_digit_beside", _value_on(lambda v: "%31" + v), frozenset({"pseudonym"})),
    Class("json_integer", lambda p, _i: json.dumps({"chart": int(p.chart), "n": 3}), frozenset({"chart"})),
    # the identifier cut at a read limit: a road that reads a limited number of bytes plants it across that limit
    Class("cut_at_read_limit", _on(lambda s: s), frozenset({"pseudonym"})),
)
CLASS = {c.id: c for c in CLASSES}


@dataclass(frozen=True)
class Plant:
    id: str  # "<class>.<person>.<identifier>"
    person: Person
    ident: str
    cls: str
    text: str


def plants(cls: str) -> list[Plant]:
    c = CLASS[cls]
    return [
        Plant(f"{cls}.{p.letter}.{i}", p, i, cls, c.encode(p, i))
        for p in people()
        if p.letter in c.people
        for i in IDENTIFIERS
        if i in c.applies
    ]


#: a text with no identifier in any form: each road must let it leave (a road that refuses all is caught)
CONTROL = "Screening for study GZQO finished: 12 candidates, 3 to review. Counts below 5 are shown as <5."
