"""R1+1 walk: a power cut during the update's image load left images whose layers were half written. After
``rollback <bundle>`` the same update failed twice in its one-off migration container ("exec python failed:
Input/output error"); with the dangling images removed it passed. ``docker load`` keeps an image the store already
holds under the archive's id, so the tag and the id were right and the layers under them were not.

Now a rollback leaves ``deploy/updates/IMAGES_SUSPECT``. The next apply removes the dangling images before the load,
checks every tag of the bundle against its pinned id after it, loads again when a tag is wrong or an image is left
dangling, and drops the mark once the apply ended well. The stand-in engine below keeps a broken image as the walk's
engine did. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_update_safety import CONFIG, Recorder, _image_plan, _plan
from tools import update_status as us
from tools.trialbox import update as up

TAG = "trialbox-py:1.0.0"
HALF = "sha256:" + "b" * 64  # another image the cut load left behind, untagged


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_DOCKER", "true")


class Engine:
    """An image store after a power cut. ``docker load`` of an archive whose image id the store already holds keeps
    that image as it is (its layers are reused, broken or not) and moves the archive's tag to it."""

    def __init__(self, images: dict[str, dict[str, Any]], in_use: frozenset[str] = frozenset()) -> None:
        self.images = images  # id -> {"tags": set, "broken": bool}
        self.in_use = in_use  # ids a running container uses: never removed
        self.calls: list[str] = []

    def run(self, argv: list[str], *_a: Any, **_kw: Any) -> str:
        self.calls.append(" ".join(argv))
        if argv[:3] == ["docker", "load", "-i"]:
            for img in self.images.values():
                img["tags"].discard(TAG)
            self.images.setdefault(CONFIG, {"tags": set(), "broken": False})["tags"].add(TAG)
            return f"Loaded image: {TAG}\n"
        if argv[:3] == ["docker", "image", "inspect"]:
            for iid, img in self.images.items():
                if argv[-1] in (iid, *img["tags"]):
                    return iid + "\n"
            raise up.UpdateFailed(f"Error: No such image: {argv[-1]}")
        if argv == up.DANGLING:
            return "".join(f"{iid}\n" for iid, img in self.images.items() if not img["tags"])
        if argv[:4] == ["docker", "image", "rm", "-f"]:
            if argv[4] in self.in_use:
                raise up.UpdateFailed("conflict: image is being used by running container")
            del self.images[argv[4]]
            return f"Deleted: {argv[4]}\n"
        return ""


def _cut() -> dict[str, dict[str, Any]]:
    """As the rollback left it: the bundle's image (its pinned id, layers half written) and another, both untagged."""
    return {CONFIG: {"tags": set(), "broken": True}, HALF: {"tags": set(), "broken": True}}


def test_without_the_mark_the_half_written_image_is_kept_under_its_tag(tmp_path: Path) -> None:
    """The stand-in shows the walk's failure: the tag and the id check out, the layers do not."""
    eng = Engine(_cut())
    assert up.ComposeBox(tmp_path, run=eng.run).load_images(_image_plan(tmp_path, True)) == ["image py.tar"]
    assert eng.images[CONFIG] == {"tags": {TAG}, "broken": True}


def test_after_a_rollback_the_cut_images_go_and_the_bundle_image_is_loaded_whole(tmp_path: Path) -> None:
    eng = Engine(_cut())
    plan = _image_plan(tmp_path, True)
    plan.reverify = True
    done = up.ComposeBox(tmp_path, run=eng.run).load_images(plan)
    assert eng.images == {CONFIG: {"tags": {TAG}, "broken": False}}  # loaded from the archive, nothing reused
    assert f"dangling image {CONFIG} removed" in done and f"dangling image {HALF} removed" in done
    rm = [i for i, c in enumerate(eng.calls) if c.startswith("docker image rm -f")]
    assert rm and max(rm) < eng.calls.index(f"docker load -i {plan.stage / 'image/py.tar'}")  # before the load


def test_an_image_left_dangling_or_a_wrong_tag_after_the_load_is_loaded_again(tmp_path: Path) -> None:
    eng = Engine({})
    plan = _image_plan(tmp_path, True)
    plan.reverify = True

    class Box(up.ComposeBox):
        loads = 0

        def load_one(self, *a: Any) -> None:
            self.loads += 1
            super().load_one(*a)
            if self.loads == 1:  # the first load leaves an untagged image and the tag on another image
                eng.images[HALF] = {"tags": set(), "broken": True}
                eng.images[CONFIG]["tags"].discard(TAG)
                eng.images["sha256:" + "d" * 64] = {"tags": {TAG}, "broken": False}

    box = Box(tmp_path, run=eng.run)
    done = box.load_images(plan)
    assert box.loads == 2 and "image py.tar loaded again" in done and f"{TAG}: not the pinned image" in done
    assert HALF not in eng.images and eng.images[CONFIG]["tags"] == {TAG}


def test_a_dangling_image_a_running_container_uses_is_kept_and_said(tmp_path: Path) -> None:
    eng = Engine({HALF: {"tags": set(), "broken": False}}, in_use=frozenset({HALF}))
    plan = _image_plan(tmp_path, True)
    plan.reverify = True
    done = up.ComposeBox(tmp_path, run=eng.run).load_images(plan)
    assert HALF in eng.images and any(d.startswith(f"dangling image {HALF} kept") for d in done)


def test_still_not_the_pinned_image_after_the_second_load_fails_the_apply(tmp_path: Path) -> None:
    eng = Engine({"sha256:" + "d" * 64: {"tags": {TAG}, "broken": False}})
    plan = _image_plan(tmp_path, True)
    plan.reverify = True
    box = up.ComposeBox(tmp_path, run=lambda argv, *a, **k: "" if argv[:2] == ["docker", "load"] else eng.run(argv))
    with pytest.raises(up.UpdateFailed, match="is not the bundle's image"):
        box.load_images(plan)


class Seen(Recorder):
    def __init__(self, fail: str | None = None) -> None:
        super().__init__(fail)
        self.reverify: list[bool] = []

    def apply(self, plan: up.Plan, rb: Path, point: up.Point) -> list[str]:
        self.reverify.append(plan.reverify)
        return super().apply(plan, rb, point)


def test_rollback_bundle_after_a_cut_apply_marks_the_images_and_a_good_apply_clears_it(tmp_path: Path) -> None:
    updates = tmp_path / "updates"

    class Cut(BaseException):  # the power cut: nothing in the updater catches it
        pass

    def cut(step: str) -> None:
        if step == "apply":
            raise Cut

    first = Seen()
    with pytest.raises(Cut):
        up.Updater(first, updates, say=lambda _m: None, on_step=cut).run(_plan(tmp_path))
    assert first.reverify == [] and not (updates / up.IMAGES_SUSPECT).exists()  # a first update trusts the store
    assert up.Updater(Seen(), updates, say=lambda _m: None).recover("B1")["from_step"] == "apply"
    assert (us.read_json(updates / up.IMAGES_SUSPECT) or {}).get("bundle_id") == "B1"
    again = Seen()
    assert up.Updater(again, updates, say=lambda _m: None).run(_plan(tmp_path))["ok"]
    assert again.reverify == [True] and not (updates / up.IMAGES_SUSPECT).exists()


def test_an_automatic_rollback_marks_the_images_for_the_next_run(tmp_path: Path) -> None:
    """The walk's rerun: the apply went on and the migration failed; the next run checks the images again too."""
    updates = tmp_path / "updates"
    with pytest.raises(up.UpdateFailed, match="rolled back"):
        up.Updater(Seen(fail="restart"), updates, say=lambda _m: None).run(_plan(tmp_path))
    assert (updates / up.IMAGES_SUSPECT).is_file()
    again = Seen()
    assert up.Updater(again, updates, say=lambda _m: None).run(_plan(tmp_path))["ok"]
    assert again.reverify == [True] and not (updates / up.IMAGES_SUSPECT).exists()
