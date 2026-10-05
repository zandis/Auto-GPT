"""Send a request mail to the test intake (GreenMail, compose test profile) — the 10-minute quickstart helper.

    python tools/send_test_mail.py "FEAS GZQO"
    python tools/send_test_mail.py "FEAS GZQO-DEMO" --attach tests/fixtures/protocols/GZQO_protocol_v3.pdf
    python tools/send_test_mail.py "APPROVE GZQO-DEMO version=1.0.0" --attach review.xlsx

Replies arrive in MailHog: http://127.0.0.1:8025 . The Authentication-Results header stands in for the hospital MTA.
"""

from __future__ import annotations

import argparse
import mimetypes
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject")
    ap.add_argument("--attach", type=Path, action="append", default=[])
    ap.add_argument("--sender", default="crc1@hospa.test")
    ap.add_argument("--to", default="trialbox@hospa.test")
    ap.add_argument("--in-reply-to", default="")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3025)
    args = ap.parse_args(argv)
    m = EmailMessage()
    m["From"] = args.sender
    m["To"] = args.to
    m["Subject"] = args.subject
    m["Message-ID"] = make_msgid(domain=args.sender.rsplit("@", 1)[-1])
    domain = args.sender.rsplit("@", 1)[-1]
    mta = "mx." + args.to.rsplit("@", 1)[-1]  # the receiving hospital's MTA writes it (TB_MAIL_AUTHSERV_ID)
    m["Authentication-Results"] = f"{mta}; spf=pass smtp.mailfrom={domain}; dkim=pass header.d={domain}"
    if args.in_reply_to:
        m["In-Reply-To"] = args.in_reply_to
    m.set_content("Sent by tools/send_test_mail.py")
    for path in args.attach:
        maintype, _, subtype = (mimetypes.guess_type(path.name)[0] or "application/octet-stream").partition("/")
        m.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    with smtplib.SMTP(args.host, args.port, timeout=30) as s:
        s.send_message(m)
    print(f"sent {m['Message-ID']}: {args.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
