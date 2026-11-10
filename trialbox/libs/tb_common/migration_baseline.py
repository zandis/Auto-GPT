"""The D-204 baseline: sha256 of every store's schema versions as they were when checksums began (T-104, D-204).

A store's ``_schema_version`` rows written before D-204 carry no checksum. :meth:`tb_common.db.Database.migrate`
back-fills them only when the script the code passes now has the checksum below; a store whose applied version was
edited before its box ever ran D-204 is refused instead of having the edited text recorded as if it had run. This
table is frozen: versions added after D-204 are recorded when they run and never appear here
(``tests/unit/test_migrations.py`` pins those). Keys are the store names given to ``Database.connect`` (the schema
without ``tb_prefix``); a store's scratch twins (``omop_<hash>``, ``orch_rerun_<hex>``) share their store's
entry (:func:`baseline_for`).
"""

from __future__ import annotations

import re

BASELINE: dict[str, tuple[str, ...]] = {
    "app": ("5e9714c8055ac691c6cf9c24fec249ce854e1b838a4961700a2a1422ba95aac3",),
    "auth": (
        "e9a25f1f3827e28dda3aa778c3a1fa46b7fc6b5a93ea23a5a3f27b160ada2f3e",
        "d92fa508ca37636a868a7ac4600d4d9dd0525152b15efa90c818a23971ffdee1",
    ),
    "datacore": (
        "124270ebcd80078b44955fc22be582db67169b8566cefc3d2d8d764cfb1bab24",
        "0e3a813b0aea05c327f1443e830e0379bd8c13e623aaf4005baed29bec0f494b",
        "758a9577e1643839cf7ece62ae10bed88404a46b69c6a0252029e062bcd917a3",
    ),
    "edc": ("4adb60686c2312912b6d2991b58d3fe2f901b4d59b539c418090f79bec9b7260",),
    "library": ("564fff938db5977ada9d769d6a285708f839f937e9bcbdafd24f72a19b9a58e3",),
    "mail": (
        "df646b957ffbad2bc96bb32327d51f6fe697e549781dc00f982d5065b8069908",
        "bde1c3613c70f347ce15a163c1c4df2c111ad93ad0e460c96c1687c14f9c20f2",
    ),
    "mpi": ("b52288b816a9aeca37187009f576159d8ee3901cdf539a57d962b30075cae022",),
    "omop": (
        "d1b8130f6cc7ae41e0cadec24ad648f9b00919482ac98228c7dd18ed02c4fedb",
        "a9dfd840a8666e0060540bc6171819d22541a021dcd15ee8e6687ad203db292b",
    ),
    "optout": ("c2fc173c7d7df7894299b132c44b8f85cd477099b8234c7583b8ef03f4f90c80",),
    "orch": ("9edc901b745b7b7e2aa1f2c87e0ad1f3d7860c6825e0e638be9cfb8320c40578",),
    "pidmap": ("0e1b2d77c92fecd822baf15acb7cfdb57db4137867869f1d48f079e89821363e",),
    "recall": ("d9ea5b8161e5241298321b3c464d503bc6801d22e0707c117a79821131474e6e",),
    "refdata": ("abce30a55cd0af022855d67d6dfb60abd2ac6b76b63f4fcf871b48795cc823aa",),
    "sae": (
        "bb78cfbe26204336feb5c26172c27f07ce5acbcdd8a49feaf8bf3bdc1098de32",
        "2ecd64f9564158876a0ebe4c543a3672f5a4f5494c929181bc7e8a654fb47b15",
    ),
    "site": (
        "61b88958f98cc442a6fc3ffd35fe1d4b561b1630ef045b6afe06c16391c4bbb5",
        "462f84721c6f0cc396262d232f3b8b32b3cb48fc09ef6ea8fceb84da47b1f99a",
    ),
    "sitesetup": (
        "a5869c5da66e3335d50e18aaf520637d760ca8dd59a1216d1a2557872c896a3f",
        "eba55b194e0590fe228b7556c30e8409cfec5516f9d42d157c50ee8d8d296398",
    ),
    "study": (
        "5717d9a039883ec8978f59ee201464037183cb8e5f7f0767b679f688ef35d20e",
        "811adda424ba9d77e1176bd42e16c9aa7e7d4dcb0506daf65166f508a6f6a1d2",
        "5c03473c7c1d4842383c7536aa8f47483b2d7023af5b3081c66f2261aac7014d",
    ),
    "team": ("f7e2ed4c4423ffa6e0c1d7c045108868a2eaf39a6ec829bd2b8536a2b9cdd632",),
    "terminology": ("d7d6eb1dd726abc79b148fbd8f650a30606230f71d08d984ffaffdc24ae7a769",),
    "trace": ("bfdb0077229852c4e139292ba57b6b1f79fffdd9610d33071b6478feba109cab",),
    "wf": ("cf4331c1cfebbaf0a6f2cae40abcf355c7d163511232559b8a53c789237a5093",),
}

_TWINS = (re.compile(r"^(omop)_[0-9a-f]{10}$"), re.compile(r"^(orch)_rerun_[0-9a-f]+$"))


def baseline_for(store: str) -> tuple[str, ...] | None:
    """The baseline checksums of ``store`` (a name given to ``Database.connect``), or None for a store without one
    (a test's own schema, the update path's ``release``): its pre-D-204 rows are back-filled from the code, logged."""
    if store in BASELINE:
        return BASELINE[store]
    for pat in _TWINS:
        if m := pat.match(store):
            return BASELINE.get(m.group(1))
    return None
