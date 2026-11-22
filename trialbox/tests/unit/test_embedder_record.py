"""The e-embed-1 row names its per-file record (F-35): the plan takes the embedder's files from it, and a record whose
file list no longer gives the row's manifest digest is refused, never fetched."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from tools import fetch_weights as fw
from tools.pin_model import EMBED_BUILD, manifest_sha256_of_files

ROOT = Path(__file__).resolve().parents[2]


def _row() -> dict[str, object]:
    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    return next(b for b in doc["builds"] if b["build_id"] == EMBED_BUILD)


def test_the_embedder_row_plans_its_files_from_its_record() -> None:
    exp = _row()["expected"]
    assert isinstance(exp, dict)
    targets = fw.plan("rtxpro6000", fw.resolve_env("rtxpro6000", {}), embedder=True)
    emb = [t for t in targets if t.dest == "embedder"]
    assert len(emb) == 1 and emb[0].builds == [EMBED_BUILD]
    files = [{"path": f.path, "sha256": f.sha256} for f in emb[0].files]
    assert manifest_sha256_of_files(files) == exp["manifest_sha256"] == emb[0].manifest_sha256
    assert not any(f.path.endswith((".bin", ".pt")) for f in emb[0].files)  # the pickle files stay out


def test_a_record_with_one_wrong_sha256_is_refused(tmp_path: Path) -> None:
    exp = _row()["expected"]
    assert isinstance(exp, dict)
    root = tmp_path / "checkout"
    (root / "models").mkdir(parents=True)
    shutil.copy(ROOT / "models" / "registry.yaml", root / "models" / "registry.yaml")
    shutil.copytree(ROOT / "deploy" / "measured", root / "deploy" / "measured")  # every row's record, as in a checkout
    rec_path = root / str(exp["source"])
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    first = rec["servers"][0]["model_files"][0]
    first["sha256"] = ("0" if first["sha256"][0] != "0" else "1") + first["sha256"][1:]
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(fw.RecordError, match=f"{EMBED_BUILD}:.*does not give the expected manifest"):
        fw.plan(
            "rtxpro6000",
            fw.resolve_env("rtxpro6000", {}),
            registry=root / "models" / "registry.yaml",
            root=root,
            embedder=True,
        )
