"""Rule-set package caps (plan 10 row 10G-6, review 16-23, ASVS 12.1.2; D-1102).

One checker for every place a rule-set zip is opened: the offline install (``criteria_compiler.import_ruleset``) and
the compiler's draft read for a trial simulation (``orchestrator.scenarios.cohort.load_draft``). It reads only the
zip's central directory and refuses, with a named reason, before any member is read or extracted:

* more than :data:`RULESET_ZIP_MAX_MEMBERS` members (directories count);
* a member over :data:`RULESET_ZIP_MAX_MEMBER_BYTES` uncompressed, or all members over
  :data:`RULESET_ZIP_MAX_TOTAL_BYTES` uncompressed;
* a member whose uncompressed size is over :data:`RULESET_ZIP_MAX_RATIO` times its compressed size (members of
  :data:`RATIO_FLOOR_BYTES` or less are not judged by ratio: a short file of one repeated character is not a bomb);
* a member name that is absolute (``/x``, ``\\x``, ``C:x``), holds a ``..`` part or a backslash or a NUL, is a
  symbolic link, or is the same as another member's name.

The sizes are the ones the central directory declares; Python's ``zipfile`` never returns more than a member's
declared size (a member that inflates past it fails its CRC check), so the declared sizes bound what is read.
"""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Iterable
from pathlib import PurePosixPath

RULESET_ZIP_MAX_MEMBERS = 2000
RULESET_ZIP_MAX_MEMBER_BYTES = 100_000_000
RULESET_ZIP_MAX_TOTAL_BYTES = 200_000_000
RULESET_ZIP_MAX_RATIO = 200
RATIO_FLOOR_BYTES = 1_000_000


class ZipRefused(ValueError):
    """A rule-set package refused before any member was read; ``code`` names the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _unsafe_name(name: str) -> str:
    if "\x00" in name or "\\" in name:
        return "a backslash or NUL in the name"
    p = PurePosixPath(name)
    if p.is_absolute() or (len(name) >= 2 and name[1] == ":"):
        return "an absolute path"
    if ".." in p.parts:
        return "a '..' part"
    return ""


def check_infos(infos: Iterable[zipfile.ZipInfo]) -> list[str]:
    """Check the central directory entries; return the member names (files and directories) in order."""
    infos = list(infos)
    if len(infos) > RULESET_ZIP_MAX_MEMBERS:
        raise ZipRefused("zip.members", f"the rule-set zip has {len(infos)} members; at most "
                         f"{RULESET_ZIP_MAX_MEMBERS:,} are accepted")  # fmt: skip
    seen: set[str] = set()
    total = 0
    for i in infos:
        n = i.filename
        why = _unsafe_name(n)
        if why:
            raise ZipRefused("zip.name", f"unsafe path {n!r} in the rule-set zip ({why})")
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ZipRefused("zip.symlink", f"{n!r} in the rule-set zip is a symbolic link")
        key = n.rstrip("/")
        if key in seen:
            raise ZipRefused("zip.duplicate", f"{n!r} appears more than once in the rule-set zip")
        seen.add(key)
        if i.file_size > RULESET_ZIP_MAX_MEMBER_BYTES:
            raise ZipRefused("zip.member_size", f"{n!r} is {i.file_size:,} bytes uncompressed; a member of the "
                             f"rule-set zip may be at most {RULESET_ZIP_MAX_MEMBER_BYTES:,} bytes")  # fmt: skip
        if i.file_size > RATIO_FLOOR_BYTES and i.file_size > RULESET_ZIP_MAX_RATIO * max(i.compress_size, 1):
            raise ZipRefused("zip.ratio", f"{n!r} expands {i.file_size:,} bytes from {i.compress_size:,}; a member "
                             f"of the rule-set zip may expand at most {RULESET_ZIP_MAX_RATIO} times")  # fmt: skip
        total += i.file_size
        if total > RULESET_ZIP_MAX_TOTAL_BYTES:
            raise ZipRefused("zip.total_size", f"the rule-set zip holds more than {RULESET_ZIP_MAX_TOTAL_BYTES:,} "
                             "bytes uncompressed")  # fmt: skip
    return [i.filename for i in infos]


def check_ruleset_zip(z: zipfile.ZipFile) -> list[str]:
    """Check an open rule-set zip before any member is read; return its member names. Raises :class:`ZipRefused`."""
    return check_infos(z.infolist())
