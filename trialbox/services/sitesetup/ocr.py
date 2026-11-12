"""OCR on the box, behind one small interface (D-131: scanned paper charts are read on the box, never sent out).

:class:`TesseractOcr` runs ``tesseract`` with Japanese, Traditional Chinese and English when it is installed (the
offline installer ships it with the ``jpn``, ``chi_tra`` and ``eng`` language data). Without it, :class:`NoOcr` says
so plainly and every other chart input (pasted text, .txt, Word, a PDF with a text layer) still works. Tests use a
fake (``tests/unit/test_site_setup.py``); no test needs the binary.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

LANGS = ("jpn", "chi_tra", "eng")


class Ocr(Protocol):
    name: str

    def available(self) -> bool: ...

    def image_text(self, data: bytes) -> str: ...


@dataclass
class NoOcr:
    name: str = "none"

    def available(self) -> bool:
        return False

    def image_text(self, data: bytes) -> str:
        raise RuntimeError("OCR is not installed on this box")


@dataclass
class TesseractOcr:
    binary: str = "tesseract"
    timeout: float = 120.0
    name: str = "tesseract"

    def _path(self) -> str | None:
        return shutil.which(self.binary)

    def langs(self) -> list[str]:
        path = self._path()
        if path is None:
            return []
        out = subprocess.run([path, "--list-langs"], capture_output=True, text=True, timeout=30, check=False)
        have = {x.strip() for x in out.stdout.splitlines()[1:]}
        return [lang for lang in LANGS if lang in have]

    def available(self) -> bool:
        return bool(self.langs())

    def image_text(self, data: bytes) -> str:
        path = self._path()
        if path is None:
            raise RuntimeError("OCR is not installed on this box")
        langs = "+".join(self.langs()) or "eng"
        out = subprocess.run(
            [path, "stdin", "stdout", "-l", langs], input=data, capture_output=True, timeout=self.timeout, check=False
        )
        if out.returncode != 0:
            raise RuntimeError(f"OCR failed ({out.returncode})")
        return out.stdout.decode("utf-8", errors="replace")


def default_ocr() -> Ocr:
    t = TesseractOcr()
    return t if t.available() else NoOcr()
