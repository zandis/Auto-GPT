"""The text of a file a person attached to a job (UX-004): one reader for the scenarios.

A chart, a consent form, a cohort table or a feedback sheet comes as UTF-8, or from a Japanese or Taiwanese
Windows as Shift_JIS or Big5. :func:`tb_common.encoding.decode_upload` gives the right text or refuses; this
turns the refusal into the step's failure with a sentence a person can act on. Nothing is replaced by U+FFFD.
"""

from __future__ import annotations

from tb_common.encoding import EncodingRefused, decode_upload

from orchestrator.clients import StepFailed


def why_unreadable(filename: str, exc: EncodingRefused) -> str:
    """The sentence for a file whose character set cannot be told."""
    where = f" (line {exc.line})" if exc.line is not None else ""
    return (
        f"{filename}: the file's character set cannot be told for certain{where}: {exc.message}. "
        "Save it as UTF-8 and send it again."
    )


def upload_text(data: bytes, filename: str, step: str) -> str:
    """The text of ``data``; a file in no one character set fails ``step`` (:class:`StepFailed`)."""
    try:
        return decode_upload(data)[0]
    except EncodingRefused as exc:
        raise StepFailed(step, why_unreadable(filename, exc)) from exc
