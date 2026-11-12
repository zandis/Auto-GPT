"""T-212d (D-450): the vLLM servers and the host tools take the model key from its files, not from deploy/.env."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_doctor_serving import KEY, _inputs, _pins, servers  # noqa: F401 (the fixture)
from tools.trialbox import doctor, noisy_neighbour
from tools.trialbox import svc_secrets as sx
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def deploy(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "deploy"
    d.mkdir()
    (d / "docker-compose.yml").write_text("services:\n  llm-service:\n    image: x\n", encoding="utf-8")
    yield d


def _vllm(deploy: Path) -> str:
    return sx.vllm_env_path(deploy).read_text(encoding="utf-8")


def test_init_and_rotate_write_the_vllm_env_file_with_the_key(deploy: Path) -> None:
    (deploy / ".env").write_text("COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY=\n", encoding="utf-8")
    sx.init(deploy, uid=None)
    key = sx.model_key_path(deploy).read_text(encoding="utf-8").strip()
    assert _vllm(deploy) == f"VLLM_API_KEY={key}\n"
    assert sx.vllm_env_path(deploy).stat().st_mode & 0o777 == 0o600
    sx.rotate(deploy, ["model"], uid=None, runner=lambda argv, stdin: None)
    new = sx.model_key_path(deploy).read_text(encoding="utf-8").strip()
    assert new != key and _vllm(deploy) == f"VLLM_API_KEY={new}\n"


def test_a_box_from_before_gets_the_vllm_env_file_and_a_differing_copy_is_still_refused(deploy: Path) -> None:
    key = "k" * 48
    (deploy / ".env").write_text(f"COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY={key}\n", encoding="utf-8")
    sx.model_key_path(deploy).parent.mkdir(parents=True)
    sx.model_key_path(deploy).write_text(key + "\n", encoding="utf-8")
    assert not sx.ensure_model_key(deploy, uid=None)  # the key file was there: kept
    assert _vllm(deploy) == f"VLLM_API_KEY={key}\n"  # the servers' file made from it
    sx.vllm_env_path(deploy).write_text("VLLM_API_KEY=stale\n", encoding="utf-8")
    sx.ensure_model_key(deploy, uid=None)
    assert _vllm(deploy) == f"VLLM_API_KEY={key}\n"  # always follows llm.key
    (deploy / ".env").write_text("COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY=edited-by-hand\n", encoding="utf-8")
    with pytest.raises(sx.SecretsError, match="differs"):  # T-608 (D-445) kept
        sx.ensure_model_key(deploy, uid=None)


def test_an_update_of_a_gpu_box_without_tokens_makes_both_files(deploy: Path) -> None:
    (deploy / ".env").write_text("COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY=\n", encoding="utf-8")
    box = up.ComposeBox(deploy, run=lambda argv, **_: "")
    box.ensure_model_key()
    key = sx.model_key_path(deploy).read_text(encoding="utf-8").strip()
    assert key == up._env_file(deploy / ".env")["TB_LLM_API_KEY"] and _vllm(deploy) == f"VLLM_API_KEY={key}\n"
    calls: list[list[str]] = []

    def run(argv: Any, **_: Any) -> str:
        calls.append(list(argv))
        return ""

    box2 = up.ComposeBox(deploy, run=run)
    box2.check_serving()
    assert "TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key" in calls[-1]


def test_doctor_reads_the_key_file_first(tmp_path: Path, servers: dict[str, str]) -> None:  # noqa: F811
    key_file = tmp_path / "llm.key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    inp = _inputs(_pins(tmp_path), servers, key="stale-dotenv-copy")
    env: dict[str, Any] = {**inp.env, "TB_LLM_API_KEY_FILE": str(key_file)}
    c = doctor.check_serving(doctor.DoctorInputs(env=env))
    assert c.status == "PASS", c.detail
    key_file.write_text("", encoding="utf-8")  # the rehearsal's drill: the key file emptied
    env["TB_LLM_API_KEY"] = ""
    c = doctor.check_serving(doctor.DoctorInputs(env=env))
    assert c.status == "FAIL" and "refused the key (HTTP 401)" in c.detail


def test_noisy_neighbour_reads_the_key_file_first(tmp_path: Path) -> None:
    f = tmp_path / "llm.key"
    f.write_text("from-the-file\n", encoding="utf-8")
    assert noisy_neighbour.model_key({"TB_LLM_API_KEY_FILE": str(f), "TB_LLM_API_KEY": "x"}) == "from-the-file"
    assert noisy_neighbour.model_key({"TB_LLM_API_KEY_FILE": str(tmp_path / "gone"), "TB_LLM_API_KEY": "x"}) == "x"


def test_the_rehearsal_drill_empties_the_key_file_not_dotenv() -> None:
    sh = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    drill = sh[sh.index("missing-key)") : sh.index(";;", sh.index("missing-key)"))]
    assert 'keyfile="$BOX/deploy/secrets/model/llm.key"' in drill and ': > "$keyfile"' in drill
    assert "envset TB_LLM_API_KEY" not in drill
    assert "TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key" in sh  # its doctor reads what the gateway reads
