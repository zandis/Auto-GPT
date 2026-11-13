"""The text of a file a person attached to a job (UX-004): one reader for the scenarios.

A chart, a consent form, a cohort table or a feedback sheet comes as UTF-8, or from a Japanese or Taiwanese
Windows as Shift_JIS or Big5. :func:`tb_common.encoding.decode_upload` gives the right text or refuses; this
turns the refusal into the step's failure with one sentence a person can act on. Nothing is replaced by U+FFFD.

One more refusal is made here (review of this card): the decoder chooses between Shift_JIS and Big5, and a few
characters of EUC-JP or GB18030 decode as one of them without an error, as other characters (``已转院了`` in GB18030
came out as half-width kana and was stored). A file that EUC-JP or GB18030 reads at least as well as the chosen
character set is refused. A long text does not meet this: its score in its own character set is clearly higher.
"""

from __future__ import annotations

from tb_common import encoding
from tb_common.encoding import EncodingRefused, decode_upload

from orchestrator.clients import StepFailed

#: character sets the decoder never chooses and that can pass for the ones it does
_OTHERS = ("euc_jp", "gb18030")


def why_unreadable(filename: str, exc: EncodingRefused) -> str:
    """The sentence for a file whose character set cannot be told: no codec names or scores, never the text."""
    where = f" (line {exc.line})" if exc.line is not None else ""
    return (
        f"{filename}: the file's character set cannot be told for certain{where}. Save it as UTF-8 and send it again."
    )


def read(data: bytes) -> str:
    """The text of ``data``, or :class:`EncodingRefused`."""
    text, codec = decode_upload(data)
    if not codec.startswith("utf"):
        mine = encoding.score(codec, text)
        for other in _OTHERS:
            try:
                theirs = data.decode(other)
            except UnicodeDecodeError:
                continue
            if encoding.score(other, theirs) >= mine:
                raise EncodingRefused(f"the file reads as well in another character set as in {codec}")
    return text


def upload_text(data: bytes, filename: str, step: str) -> str:
    """The text of ``data``; a file in no one character set fails ``step`` (:class:`StepFailed`)."""
    try:
        return read(data)
    except EncodingRefused as exc:
        raise StepFailed(step, why_unreadable(filename, exc)) from exc
