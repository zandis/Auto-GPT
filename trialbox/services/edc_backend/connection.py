"""One project on the external REDCap or on the internal service, behind the same calls.

The client paces itself and, on export, blanks fields the dictionary tags as identifiers. It does not log the
token, the file bytes or a record's values. Nothing constructs a connection unless :func:`connect` is called, and
that returns ``None`` while ``TB_EDC_BACKEND`` is unset.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from rc_bridge.client import (
    INPROC_PREFIX,
    SUPPORTED_MAJORS,
    RcError,
    RedcapClient,
    major_of,
)

from edc_backend.config import EdcConfigError, load_config
from edc_backend.mapping import blank_identifiers, map_project

# The study-link page still uses SUPPORTED_MAJORS (14-17). This backend also accepts 13: the methods it calls are
# the same documented /api/ surface on 13.7. 12 and 18 stay refused.
ACCEPTED_MAJORS = (13, *SUPPORTED_MAJORS)


class Pace:
    """A per-connection cap. At the cap the call is refused; it does not sleep for the rest of the minute."""

    def __init__(
        self,
        min_interval_ms: int,
        max_per_minute: int,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.min_interval = max(0, min_interval_ms) / 1000.0
        self.max_per_minute = max(0, max_per_minute)
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._times: list[float] = []
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self.min_interval <= 0 and self.max_per_minute <= 0:
            return
        delay = 0.0
        with self._lock:
            now = self._clock()
            self._times = [t for t in self._times if now - t < 60.0]
            if self.max_per_minute and len(self._times) >= self.max_per_minute:
                raise RcError("RC-RATE", "the connector's own per-minute cap was reached")
            if self._times and self.min_interval > 0:
                delay = self.min_interval - (now - self._times[-1])
            if delay <= 0:
                self._times.append(now)
                return
        self._sleep(delay)
        with self._lock:
            now = self._clock()
            self._times = [t for t in self._times if now - t < 60.0]
            if self.max_per_minute and len(self._times) >= self.max_per_minute:
                raise RcError("RC-RATE", "the connector's own per-minute cap was reached")
            self._times.append(now)


class EdcConnection:
    """The calls both backends share. ``kind`` is ``redcap`` or ``internal``."""

    def __init__(
        self, kind: str, client: RedcapClient, *, pace: Pace | None = None, file_max_bytes: int = 26_214_400
    ) -> None:
        self.kind = kind
        self.client = client
        self.pace = pace or Pace(0, 0)
        self.file_max_bytes = file_max_bytes

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> EdcConnection:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"EdcConnection(kind={self.kind!r})"

    def _go(self) -> None:
        self.pace.wait()

    def ensure_version(self) -> str:
        """The server's version when it is 13 through 17. This is not :meth:`RedcapClient.check_version`."""
        self._go()
        version = self.client.version()
        if major_of(version) not in ACCEPTED_MAJORS:
            raise RcError("RC-VERSION", f"REDCap {version} is outside the majors this backend accepts (13 through 17)")
        return version

    def project(self) -> dict[str, Any]:
        self._go()
        return self.client.project()

    def metadata(self) -> list[dict[str, Any]]:
        self._go()
        return self.client.metadata()

    def instruments(self) -> list[dict[str, Any]]:
        self._go()
        return self.client.instruments()

    def events(self) -> list[dict[str, Any]]:
        """An empty list when the project is classic (REDCap refuses the export)."""
        return self._or_classic(self.client.events)

    def arms(self) -> list[dict[str, Any]]:
        return self._or_classic(self.client.arms)

    def repeating(self) -> list[dict[str, Any]]:
        self._go()
        try:
            return self.client.repeating_forms_events()
        except RcError as exc:
            if exc.refused and exc.kind == "repeat":
                return []
            raise

    def form_event_mapping(self) -> list[dict[str, Any]]:
        return self._or_classic(self.client.form_event_mapping)

    def _or_classic(self, call: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        self._go()
        try:
            return call()
        except RcError as exc:
            if exc.refused and exc.kind == "classic":
                return []
            raise

    def export_records(
        self,
        *,
        fields: list[str] | None = None,
        events: list[str] | None = None,
        records: list[str] | None = None,
        since: str | None = None,
        drop_identifiers: bool = True,
    ) -> list[dict[str, Any]]:
        """Flat rows, longitudinal and repeating columns included. Identifier fields are blanked by default."""
        self._go()
        rows = self.client.records(fields=fields, events=events, records=records, since=since)
        if not drop_identifiers:
            return rows
        self._go()
        return blank_identifiers(rows, self.client.metadata())

    def import_records(self, rows: list[dict[str, str]], *, auto_number: bool = False) -> list[str]:
        """``overwriteBehavior=normal``: a blank does not erase. Returns the record ids written."""
        self._go()
        return self.client.import_records(rows, auto_number=auto_number)

    def ensure_schedule(
        self,
        *,
        arms: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        mapping: list[dict[str, Any]] | None = None,
        repeating: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create arms, events, the form-event map and repeating instruments on an empty project."""
        out: dict[str, Any] = {}
        for key, rows, call in (
            ("arms", arms, self.client.import_arms),
            ("events", events, self.client.import_events),
            ("mapping", mapping, self.client.import_form_event_mapping),
            ("repeating", repeating, self.client.import_repeating),
        ):
            if not rows:
                continue
            self._go()
            out[key] = call(rows)
        return out

    def import_dictionary(self, csv_text: str) -> Any:
        """Send a data-dictionary CSV. Use this against an empty internal project, not a live REDCap, by default."""
        self._go()
        return self.client.import_metadata(csv_text)

    def mapped(self, study: str) -> dict[str, Any]:
        """The dictionary and the visit schedule as TrialBox's forms. Two or three reads, then no PHI kept here."""
        meta = self.metadata()
        info = self.project()
        events = self.events()
        return map_project(
            study,
            meta,
            project=info,
            events=events,
            arms=self.arms(),
            form_event_mapping=self.form_event_mapping(),
            repeating=self.repeating(),
        )

    def survey_link(self, record: str, instrument: str, event: str = "", repeat_instance: str = "") -> str:
        self._go()
        link = self.client.survey_link(record, instrument, event, repeat_instance)
        if self.client.token and self.client.token in link:
            raise RcError("RC-UPSTREAM", "the survey link carried the API token and was dropped")
        return link

    def project_log(self, logtype: str = "") -> list[dict[str, Any]]:
        self._go()
        return self.client.project_log(logtype=logtype)

    def export_file(self, record: str, field: str, event: str = "", repeat_instance: str = "") -> tuple[bytes, str]:
        self._go()
        body, name = self.client.export_file(record, field, event, repeat_instance)
        if len(body) > self.file_max_bytes:
            raise RcError("RC-UPSTREAM", "the file is larger than the connector accepts")
        return body, name

    def import_file(
        self, record: str, field: str, filename: str, body: bytes, event: str = "", repeat_instance: str = ""
    ) -> None:
        if len(body) > self.file_max_bytes:
            raise RcError("RC-UPSTREAM", "the file is larger than the connector accepts")
        self._go()
        self.client.import_file(record, field, filename, body, event, repeat_instance)

    def delete_file(self, record: str, field: str, event: str = "", repeat_instance: str = "") -> None:
        self._go()
        self.client.delete_file(record, field, event, repeat_instance)


def connect(
    environ: Mapping[str, str] | None = None, project: str | None = None, http: httpx.Client | None = None
) -> EdcConnection | None:
    """The selected backend, or ``None`` when ``TB_EDC_BACKEND`` is unset (the box keeps today's behaviour)."""
    env = os.environ if environ is None else environ
    cfg = load_config(env)
    if not cfg.kind:
        return None
    if not cfg.url:
        which = "TB_EDC_INTERNAL_URL" if cfg.kind == "internal" else "TB_REDCAP_API_URL"
        raise EdcConfigError(f"{which} is not set")
    token = cfg.token_for(project)
    if cfg.url.startswith(INPROC_PREFIX):
        client = RedcapClient(cfg.url, token, http=http)
        return EdcConnection(
            cfg.kind, client, pace=Pace(cfg.min_interval_ms, cfg.max_per_minute), file_max_bytes=cfg.file_max_bytes
        )
    client = RedcapClient(
        cfg.url,
        token,
        http=http,
        loopback_http=cfg.loopback_http,
        declare_host=http is None,
    )
    return EdcConnection(
        cfg.kind,
        client,
        pace=Pace(cfg.min_interval_ms, cfg.max_per_minute),
        file_max_bytes=cfg.file_max_bytes,
    )


def copy_records(src: EdcConnection, dst: EdcConnection, *, keep_identifiers: bool = False) -> dict[str, int]:
    """Copy flat rows from one backend to the other. Identifier fields are blanked unless the site asks to keep them.

    The destination's dictionary is not replaced. Import it first with :meth:`EdcConnection.import_dictionary`
    when the internal project is empty. A blank does not erase a value already on the destination.
    """
    rows = src.export_records(drop_identifiers=not keep_identifiers)
    if not rows:
        return {"rows": 0, "records": 0}
    written = dst.import_records([{k: "" if v is None else str(v) for k, v in row.items()} for row in rows])
    return {"rows": len(rows), "records": len(written)}
