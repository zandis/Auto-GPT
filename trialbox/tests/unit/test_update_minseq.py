"""UPDATE-MINSEQ (D-625): a release's tree names the lowest release it can be applied over, and signing holds the
bundle to it. D-620 and D-624 say "a release that adds a step names a release that has the command as its
min_installed_version"; nothing made the person who signs remember."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from tools import sign_bundle
from tools.trialbox import prestart

pytestmark = pytest.mark.nodb

MOD = "tools/trialbox/prestart.py"


def _host_tar(tmp_path: Path, body: str | None, name: str = "trialbox-host.tar") -> Path:
    out = tmp_path / name
    with tarfile.open(out, "w") as tf:
        for member, text in (("HOST-SHA256SUMS", ""), ("tools/__init__.py", ""), (MOD, body)):
            if text is None:
                continue
            data = text.encode()
            ti = tarfile.TarInfo(member)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return out


def _sign(tmp_path: Path, host: Path, floor: int) -> dict[str, object]:
    key, _ = sign_bundle.keygen(tmp_path / "k")
    return sign_bundle.build(key, "B-1", [("host", host, host.name)], tmp_path / "b.tar",
                             release_seq=9, min_installed_version=floor)  # fmt: skip


def test_a_bundle_signed_below_its_trees_floor_is_refused(tmp_path: Path) -> None:
    host = _host_tar(tmp_path, "MIN_INSTALLED_SEQ = 7\n")
    with pytest.raises(SystemExit) as exc:
        _sign(tmp_path, host, 0)  # the default of --min-installed
    said = str(exc.value)
    assert "7" in said and "--min-installed" in said and MOD in said
    assert not (tmp_path / "b.tar").exists()  # nothing is written


def test_the_floor_or_a_higher_one_signs(tmp_path: Path) -> None:
    host = _host_tar(tmp_path, "MIN_INSTALLED_SEQ: int = 7  # the first release with db-up\n")
    assert _sign(tmp_path, host, 7)["min_installed_version"] == 7
    (tmp_path / "b.tar").unlink()
    assert _sign(tmp_path, host, 8)["min_installed_version"] == 8


@pytest.mark.parametrize("body", [None, "STEPS = []\n", "MIN_INSTALLED_SEQ = 0\n"])
def test_a_tree_that_asks_for_nothing_signs_with_the_default(tmp_path: Path, body: str | None) -> None:
    assert _sign(tmp_path, _host_tar(tmp_path, body), 0)["min_installed_version"] == 0


@pytest.mark.parametrize("body", ["MIN_INSTALLED_SEQ = FIRST_WITH_DB_UP\n", "MIN_INSTALLED_SEQ = -1\n"])
def test_a_floor_that_cannot_be_read_is_refused_not_taken_as_none(tmp_path: Path, body: str) -> None:
    with pytest.raises(SystemExit, match="MIN_INSTALLED_SEQ"):
        _sign(tmp_path, _host_tar(tmp_path, body), 99)


@pytest.mark.parametrize(
    "body",
    [
        "MIN_INSTALLED_SEQ = 0\nMIN_INSTALLED_SEQ = 7\n",  # set again further down
        "MIN_INSTALLED_SEQ = 7\nMIN_INSTALLED_SEQ = 0\n",
        "if True:\n    MIN_INSTALLED_SEQ = 7\n",  # not at the margin
    ],
)
def test_the_highest_floor_the_file_names_counts_wherever_it_stands(tmp_path: Path, body: str) -> None:
    with pytest.raises(SystemExit, match="release_seq 7"):
        _sign(tmp_path, _host_tar(tmp_path, body), 6)


def test_a_payload_that_is_no_host_tree_is_not_read(tmp_path: Path) -> None:
    """Only the kind ``host`` carries a tree; a ruleset or a model with the same member name is not asked."""
    other = _host_tar(tmp_path, "MIN_INSTALLED_SEQ = 7\n", name="ruleset.zip")
    key, _ = sign_bundle.keygen(tmp_path / "k")
    m = sign_bundle.build(key, "B-1", [("ruleset", other, other.name)], tmp_path / "b.tar", release_seq=9)
    assert m["min_installed_version"] == 0


def test_this_tree_states_its_floor_where_signing_reads_it() -> None:
    assert isinstance(prestart.MIN_INSTALLED_SEQ, int) and prestart.MIN_INSTALLED_SEQ >= 0
    assert sign_bundle.tree_floor(Path(prestart.__file__).read_text(encoding="utf-8")) == prestart.MIN_INSTALLED_SEQ


#: the steps of this release and the floor they were decided with. A card that changes a list fails here ON PURPOSE.
#: Before you update this pin, decide: could a box in the field be on a release whose updater does not run the
#: command of the step you add (``pre-start``: D-620; ``db-up``: D-624)? If yes, set ``MIN_INSTALLED_SEQ`` in
#: tools/trialbox/prestart.py to the ``release_seq`` of the first release that has the command. If no box has a
#: release yet, 0 stays. Then write the new names and the floor here.
PINNED = {
    # T-717b (D-547) and NEW-TRUST-1 (D-541): two host-side steps and one guard. The floor stays 0: no box has a
    # release yet, so none is on a release without the two commands (lane D's word, 2026-11-13).
    # D-722: one more host-side step, a refusal that makes nothing; the floor stays 0 for the same reason
    # D-1349: one more refusal that makes nothing, first; the floor stays 0 (no box has a release yet)
    "pre-start": [
        "old shared service token",
        "image pins",
        "model key",
        "actor signing key",
        "FHIR store password",
        "hospital directory CA",
    ],
    # D-921: one more database step, in the new tree's own db-up (an updater that has the command runs it); an
    # updater from before db-up leaves the migrations to each service's start, as before. The floor stays 0
    "db-up": ["FHIR store password is set", "database", "service roles", "owned schemas", "service stores"],
    "floor": 0,
}


def test_a_new_step_makes_its_card_decide_the_floor() -> None:
    now = {
        "pre-start": [name for name, _ in prestart.STEPS],
        "db-up": [name for name, _ in prestart.DB_STEPS],
        "floor": prestart.MIN_INSTALLED_SEQ,
    }
    assert now == PINNED, "a step changed: read the note above PINNED in this file, decide the floor, then update it"


def test_the_pages_say_where_the_floor_is_set() -> None:
    doc = " ".join((prestart.__doc__ or "").split())
    assert "MIN_INSTALLED_SEQ" in doc and "sign_bundle" in doc
