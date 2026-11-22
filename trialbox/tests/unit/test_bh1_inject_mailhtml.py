"""Bug hunt BH1, area 5: stored text in the HTML part of an outbound mail.

Entry point: a FEAS run (mail subject ``FEAS <study>`` or the console's run button). ``scenarios/feas.py`` builds
the requester's mail body from the funnel's biggest barriers, each one a criterion's label or, without one, the
first 60 characters of the protocol's criterion text (``feas_compute.py``). The orchestrator sends that Markdown
to the mail gateway (``core.py: Orchestrator.send``), which turns it into the HTML alternative with
``markdown.markdown`` (``mail_gateway/outbound.py: render_body``). The converter passes inline HTML through as
written, so markup in a criterion's text reaches the recipient's mail client as markup, where the PDF of the same
run escapes the same label (``feasibility_pdf.answer_text``).

Synthetic values only; nothing is sent.
"""

from __future__ import annotations

from email import message_from_bytes, policy
from typing import cast

import pytest
from mail_gateway.outbound import prepare
from orchestrator.i18n import t
from tb_common.objstore import ObjectStore
from tb_contracts.generated.models import SendRequest

# a criterion text as a protocol could carry it (synthetic); the host is a reserved example name
LABEL = 'Adults <img src="https://tracker.example/p.png"> aged 18 or over'


class _NoStore:
    def get(self, key: str) -> bytes:  # no attachment in this mail
        raise AssertionError(key)


def _html_part(body_md: str) -> str:
    req = SendRequest(job_id="J-BH1", to=["crc@site.example"], subject="FEAS done", body_md=body_md, tag="aggregate")
    prepared = prepare(
        req, store=cast(ObjectStore, _NoStore()), sender="box@site.example", internal_domains=["site.example"], tz="UTC"
    )
    msg = message_from_bytes(prepared.data, policy=policy.default)
    part = msg.get_body(preferencelist=("html",))
    assert part is not None
    return str(part.get_content())


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-07: a criterion's text reaches the HTML part of the FEAS mail as live markup",
)
def test_feas_mail_html_shows_a_criterion_label_as_text() -> None:
    # the line exactly as scenarios/feas.py writes it for the two biggest barriers
    body_md = "\n".join(
        [
            t("en", "feas.intro", trial="BH1", rs="BH1", ver="1", snapshot="2026-11-01"),
            "",
            t("en", "feas.barriers", items="; ".join(f"{lbl} (−{d})" for lbl, d in [(LABEL, 40), ("eGFR", 10)])),
        ]
    )
    html = _html_part(body_md)
    assert "tracker.example" in html  # the label is in the mail
    assert "<img" not in html  # ...as text, not as an element the client loads
    assert "&lt;img" in html
