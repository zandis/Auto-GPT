"""ERASE-D (D-874): a queued mail carrying an opted-out patient's own file is dropped by the opt-out worker.

D-863 dropped a mail the gateway held for an opt-out; a mail still queued (the SMTP server down, not yet asked)
kept its request, whose attachment names carry the pseudonym's prefix. The same clear now drops it (the gateway
would hold it: it asks before each send). A queued mail of lists stays (it names no one in the outbox). Synthetic
data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tb_contracts import SendRequest

from tests.unit.test_the_outbox_asks_before_it_sends import (
    JOB,
    MTA,
    A,
    Register,
    _gw,
    _phi,
    _state,
    _worker_env,
)


def test_a_queued_mail_of_the_patients_own_file_is_dropped(db_url: str, tmp_path: Path) -> None:
    from datacore.optout_worker import clear_held_mail, verify_held_mail

    mta, reg = MTA(), Register()
    gw = _gw(tmp_path, mta, reg)
    own = f"outputs/{JOB}/twpas_GZQO_{A[:12]}.json"
    gw.store.put(own, b'{"synthetic": true}')
    doc: dict[str, Any] = _phi("q1").model_dump()
    doc["attachments"] = [{"filename": f"twpas_GZQO_{A[:12]}.json", "minio_key": own}]
    gw.send(SendRequest.model_validate(doc))  # the SMTP server is down: queued, not yet asked again
    gw.send(_phi("q2"))  # a queued mail of lists
    assert _state(gw, "q1")[0] == "queued" and _state(gw, "q2")[0] == "queued"
    env = _worker_env(db_url, {A})
    gone = frozenset(env.register.effective())
    assert verify_held_mail(gone, env) == {"mail.send_keys": 1}
    assert clear_held_mail(gone, env) == {"mail.send_keys": 1}
    assert verify_held_mail(gone, env) == {"mail.send_keys": 0}
    row = gw.db.db.fetchone("SELECT state, request, recipients FROM send_keys WHERE key = 'q1'")
    assert row is not None and tuple(row) == ("dropped", None, None)
    assert _state(gw, "q2")[0] == "queued"  # the list stays: it names no one in the outbox
    env.register.close()
