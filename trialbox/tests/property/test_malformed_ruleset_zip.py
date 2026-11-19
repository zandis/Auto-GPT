"""Card 10G-43 (OT-5): the rule-set zip on malformed input (``criteria_compiler.import_ruleset.read_zip``, behind it
``tb_common.zipcap.check_ruleset_zip`` of 10G-6 / D-1102).

``read_zip`` returns ``(id, files, manifest)`` or refuses with :class:`ImportRefused`. Inputs: bytes that are no zip,
damaged zips, and real zips whose members, names and ``manifest.yaml`` are generated.
"""

from __future__ import annotations

import io
import warnings
import zipfile

import pytest
import yaml
from criteria_compiler.import_ruleset import ImportRefused, read_zip
from hypothesis import example, given
from hypothesis import strategies as st
from tb_common.zipcap import ZipRefused, check_ruleset_zip

from tests.malformed_kit import SETTINGS, Escaped, returns_or_refuses

_NAMES = st.one_of(
    st.sampled_from(["manifest.yaml", "r1/manifest.yaml", "r1/ir.json", "r1/", "../x", "/abs", "a\\b", "r1/r1/x",
                     "manifest.yaml/", "r1/a/manifest.yaml", "x" * 300]),
    st.text(alphabet=st.sampled_from("ar1/._-\\:\x00山"), min_size=1, max_size=16),
)  # fmt: skip
_MANIFEST = st.one_of(
    st.sampled_from([b"", b"id: r1\n", b"id: r2\n", b"- a\n- b\n", b"just text", b"id: [", b"\xff\xfe", b"7",
                     b"id: r1\nstatus: approved\n", b"{id: {a: 1}}", b"id: null", b"!!python/object:x {}"]),
    st.binary(max_size=64),
)  # fmt: skip


_YAML_SCALAR = st.one_of(st.none(), st.booleans(), st.integers(), st.text(alphabet="ar1-_ ", max_size=6))
#: manifests that are YAML mappings (the reader's own shape); one that is not is H10G43-02
_MAPPING = st.dictionaries(st.sampled_from(["id", "status", "version", "x"]), _YAML_SCALAR | st.just("r1"), max_size=4)


@st.composite
def zips(draw: st.DrawFn, *, damage: bool = False, any_manifest: bool = False) -> bytes:
    """A real zip with generated members and names. ``damage``: truncated or one byte changed (H10G43-01);
    ``any_manifest``: a ``manifest.yaml`` of any bytes (H10G43-02), else a YAML mapping."""
    buf = io.BytesIO()
    method = draw(st.sampled_from([zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED]))
    with warnings.catch_warnings(), zipfile.ZipFile(buf, "w", method) as z:
        warnings.simplefilter("ignore", UserWarning)  # a duplicate name (two names zipfile writes alike) is wanted
        for name in draw(st.lists(_NAMES, max_size=6, unique=True)):
            if name.endswith("manifest.yaml"):
                body = draw(_MANIFEST) if any_manifest else yaml.safe_dump(draw(_MAPPING)).encode()
            else:
                body = draw(st.binary(max_size=64))
            z.writestr(name, body)
    data = buf.getvalue()
    cut = draw(st.sampled_from(["truncate", "flip"])) if damage else "whole"
    if cut == "truncate" and data:
        data = data[: draw(st.integers(0, 10**6)) % len(data)]
    elif cut == "flip" and data:
        i = draw(st.integers(0, 10**6)) % len(data)
        data = data[:i] + bytes([data[i] ^ draw(st.integers(1, 255))]) + data[i + 1 :]
    return data


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


_REFUSAL = (ImportRefused,)


@SETTINGS
@given(zips())
@example(_zip({"r1/manifest.yaml": b"id: r1\n", "r1/ir.json": b"{}"}))
@example(_zip({"r1/manifest.yaml": b"id: r2\n"}))
@example(_zip({"manifest.yaml": b"{}"}))
def test_read_zip_returns_or_refuses(data: bytes) -> None:
    """Intact zips whose manifest is a mapping: what is left once H10G43-01 and -02 (their own tests) are set apart."""
    returns_or_refuses(lambda: read_zip(data), _REFUSAL)


@SETTINGS
@given(st.one_of(zips(), zips(damage=True, any_manifest=True)))
def test_the_caps_check_returns_names_or_refuses(data: bytes) -> None:
    """The 10G-6 check on the central directory alone: names, or :class:`ZipRefused`, on any zip that opens."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return  # not a zip: the opening, not the caps check (H10G43-01 is about read_zip's caller)
    with z:
        returns_or_refuses(lambda: check_ruleset_zip(z), (ZipRefused,))


@SETTINGS
@given(st.one_of(st.binary(max_size=256), zips(damage=True)))
@example(b"")
@pytest.mark.xfail(strict=True, raises=Escaped, reason="H10G43-01: bytes that are no zip, or a damaged zip, raise zipfile.BadZipFile "
                                       "(or another reader error), not ImportRefused")  # fmt: skip
def test_h10g43_01_bytes_that_are_no_zip(data: bytes) -> None:
    returns_or_refuses(lambda: read_zip(data), _REFUSAL)


@SETTINGS
@given(zips(any_manifest=True))
@example(_zip({"manifest.yaml": b"- a\n"}))
@example(_zip({"manifest.yaml": b"\xff"}))
@example(_zip({"manifest.yaml": b"id: ["}))
@pytest.mark.xfail(
    strict=True, raises=Escaped, reason="H10G43-02: a manifest.yaml that is no YAML mapping escapes read_zip"
)
def test_h10g43_02_a_manifest_that_is_no_mapping(data: bytes) -> None:
    returns_or_refuses(lambda: read_zip(data), _REFUSAL)
