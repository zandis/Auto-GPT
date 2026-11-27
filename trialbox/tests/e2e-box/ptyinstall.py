"""Run the one-command install in a pseudo-terminal and answer its questions like a person at the keyboard.

    ptyinstall.py BUNDLE PASSPHRASE_FILE PATIENTS        (root, in the VM; the media mounted at /media/usb)

The site's size is declared the documented way (``TB_SITE_PATIENTS``, read by the installer's memory sizing) and
given to any question about the number of patients. The transcript goes to /var/tmp/install.log and the prompts to
/var/tmp/prompts.txt, both 0600. The installer shows the first administrator's password and enrolment code once on
the terminal: they are cut out of every line written (``<redacted>``) and kept only in /root/e2e-first-admin.json
(0600), which the harness takes and removes. The exit status is the installer's.
"""

import json
import os
import pty
import re
import select
import sys
import time

# console.cli's two one-time lines: "password (shown once): X" and "enrolment code ... (shown once, valid 24 hours): X"
SECRET = re.compile(r"(?P<label>(?P<kind>password|enrolment code)[^\n:]*\(shown once[^)\n]*\): )(?P<value>\S+)")
LABEL_ONLY = re.compile(r"\(shown once[^)\n]*\):\s*$")  # the value has not arrived yet: never a question
PROMPT_END = (":", "]:", "?", "]")
BUNDLE = re.compile(r"^trialbox-[A-Za-z0-9._-]+\.tar$")


def is_prompt(pending: str, quiet_s: float) -> bool:
    """A partial line the installer has stopped at for 1.5 s and that ends like a question; a one-time value's label
    waiting for its value is not one (answering it would write the value, on the next read, without its label)."""
    line = pending.strip()
    return bool(line) and line.endswith(PROMPT_END) and quiet_s >= 1.5 and not LABEL_ONLY.search(pending)


def redact(line: str) -> tuple[str, dict[str, str]]:
    """The line with every one-time value replaced, and the values found ({"password": ..., "enrol": ...})."""
    found: dict[str, str] = {}

    def cut(m: re.Match[str]) -> str:
        found["password" if m["kind"] == "password" else "enrol"] = m["value"]
        return m["label"] + "<redacted>"

    return SECRET.sub(cut, line), found


def answer(prompt: str, passphrase: str, patients: str, after_passphrase: bool = False) -> tuple[str, bool]:
    """What a person types at this prompt, and whether it may be shown in the prompts file. The passphrase goes only to a
    prompt that names it, or to the repeat asked straight after one; any other confirm-type question gets Enter."""
    low = prompt.lower()
    if "passphrase" in low or (after_passphrase and any(w in low for w in ("again", "repeat", "twice", "confirm"))):
        return passphrase, False
    if "language" in low:
        return "en", True
    if "time zone" in low or "timezone" in low or " tz" in low:
        return "", True
    if "patients" in low:
        return patients, True
    if "mail" in low:
        return "admin@hospa.test", True
    if "name" in low:
        return "Admin Synthetic", True
    return "", True


def private(path: str) -> int:
    """A new root-only file at path (an old file or a link there is removed first, never followed)."""
    if os.path.lexists(path):
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    return fd


def main(bundle: str, passphrase_file: str, patients: str) -> int:
    if not BUNDLE.match(bundle):
        raise SystemExit(f"not a bundle file name: {bundle!r}")
    with open(passphrase_file, encoding="utf-8") as fh:
        passphrase = fh.read().strip()
    env = {**os.environ, "TB_HOST_PROFILE": "poc", "TB_INSTALL_UP_TIMEOUT": "900", "TB_SITE_PATIENTS": str(int(patients)),
           "TB_COMPOSE_OVERRIDE": "/opt/trialbox/tools/rehearse_box/standins.yml"}  # fmt: skip
    argv = ["bash", "trialbox-bootstrap.sh", bundle, "--pub", "/root/vendor_ed25519.pub", "--", "--tier", "large", "--ctgov",
            "offline", "--rehearsal"]  # fmt: skip
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir("/media/usb")
        os.execvpe("bash", argv, env)
    log, prompts = private("/var/tmp/install.log"), private("/var/tmp/prompts.txt")
    secrets: dict[str, str] = {}
    pending, last, asked, after = "", time.time(), 0, False

    def write(out: int, text: str) -> None:
        clean, found = redact(text)
        secrets.update(found)
        os.write(out, (clean.replace(passphrase, "<redacted>") if passphrase else clean).encode())

    while True:
        r, _, _ = select.select([fd], [], [], 2.0)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            pending += data.decode(errors="replace")
            last = time.time()
            *done, pending = pending.split("\n")
            for line in done:  # only whole lines are written: a value split across two reads is still cut
                write(log, line + "\n")
            continue
        if is_prompt(pending, time.time() - last):
            line = redact(pending.strip())[0]  # redacted before it is cut to length, so no value loses its label
            write(log, pending)
            write(prompts, f"PROMPT: {line[-160:]}\n")
            text, shown = answer(line, passphrase, patients, after)
            after = not shown
            os.write(fd, (text + "\n").encode())
            write(prompts, f"-> answered: {text if shown else '<hidden>'!r}\n")
            asked += not shown
            pending = ""
    write(log, pending)
    _, status = os.waitpid(pid, 0)
    rc = os.waitstatus_to_exitcode(status)
    os.write(log, f"\nrc={rc}\n".encode())
    os.write(prompts, f"passphrase prompts answered: {asked}\nrc={rc}\n".encode())
    os.close(log)
    os.close(prompts)
    if secrets:
        out = private("/root/e2e-first-admin.json")
        os.write(out, json.dumps(secrets).encode())
        os.close(out)
    return rc


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
