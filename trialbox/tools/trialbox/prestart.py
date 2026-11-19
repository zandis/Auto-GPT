"""The steps a release runs on the host before its stack starts (UPDATE-PRESTART).

    python3 -m tools.trialbox pre-start --deploy deploy      # run by the update path, from the install folder

An update switches the box to the new release's tree and then starts the stack with the new compose files. What
the new stack needs on the host before it starts (a secret file a new service reads, a pin the image store lost)
has to be made by the NEW release's code: the updater that is running is the installed, older one, and it cannot
know a step that did not exist when it was written. So the restart of an update runs this command as a process of
its own, in the install folder, where ``tools/`` is already the new tree (``tools/trialbox/update.py``
``ComposeBox.pre_start``).

**A release that adds a step adds it to** :data:`STEPS`. A step takes the box (``ComposeBox``: its ``deploy``
folder, its ``.env``) and returns one line for the log. The contract:

* safe to run again, and it works with the stack down;
* it fails by raising ``UpdateFailed``: the update then stops before the stack starts and is rolled back;
* what it leaves on the host must be harmless to the previous release: a rollback puts back the databases, the
  images, the models and the host tree, not ``deploy/.env`` and not ``deploy/secrets``.

A fresh install runs the same command: ``deploy/install.sh`` calls it before it starts the stack. The installer
still has shell copies of some of this for a host without python3 (the service passwords in ``deploy/.env``, the
role script, the migrate step); a step added here is not run on such a host, and the installer says so.

The first release with this command cannot be helped by it: the release installed before it restarts the stack
the old way. A release that adds a step therefore names, as its ``min_installed_version``, a release that has
this command; the verifier refuses the bundle on an older box before anything is changed.

**After the database is up** (UPDATE-DBUP, D-624) there is a second list, :data:`DB_STEPS`, and a second command:

    python3 -m tools.trialbox db-up --deploy deploy        # after pre-start, before the services start

It is for what needs the database and must be done before a service connects: the services' roles, the schemas
no service owns, a grant a later release adds. The contract is the one above with one difference: the database is
up (the ``db`` service, healthy) and no other service of the stack is; a step must not wait for one. A step that
only needs the host belongs in :data:`STEPS`. ``ComposeBox.db_up`` runs the command on an update and
``deploy/install.sh`` on an install; a release that adds a step here names a release that has ``db-up`` as its
``min_installed_version``.

**The floor.** :data:`MIN_INSTALLED_SEQ` is the lowest ``release_seq`` a box may be at to take this tree by update
(D-625). ``tools/sign_bundle.py`` reads it from the bundle's host payload and refuses to sign a bundle whose
``min_installed_version`` is below it, so the sentence above about ``min_installed_version`` cannot be forgotten.
A card that adds a step decides the number; ``tests/unit/test_update_minseq.py`` says how.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.trialbox.update import ComposeBox


#: the lowest release_seq a box may be at to take this tree by update; 0 while no release has reached a box.
#: Written as a plain whole number on this line: tools/sign_bundle.py reads the line, it does not import this file.
MIN_INSTALLED_SEQ = 0


def _image_pins(box: ComposeBox) -> str:
    box.resolve_pins()
    return "compose is pointed at the bundle's images where the image store kept no digest"


def _model_key(box: ComposeBox) -> str:
    return "made now" if box.ensure_model_key() else "in place, or not a GPU box"


def _actor_key(box: ComposeBox) -> str:
    """T-717 (D-485), T-717b (D-547): the console's signing key and the orchestrator's keys file. Harmless to the
    release before, which makes the same two files; a release from before T-717 is excluded by
    ``min_installed_version``."""
    made = box.ensure_actor_key()
    return "no per-service tokens on this box" if made is None else ("made now" if made else "in place")


def _fhir_password(box: ComposeBox) -> str:
    """D-541 (NEW-TRUST-1): the FHIR store's own database role needs a password in ``.env`` before the database
    container is put on this release's settings (``DB_STEPS``: the role script reads it from the container's
    environment). Harmless to the release before: it does not read the setting."""
    return "made now" if box.ensure_fhir_password() else "in place"


def _ldap_ca(box: ComposeBox) -> str:
    """D-722: this release gives Authelia the hospital's directory CA as its whole root list. A box whose hospital
    sign-in is on and that has no usable ``TB_LDAP_CA`` would start an Authelia that can check no certificate:
    every hospital sign-in would fail, with no word before. Doctor's own check, before anything is made or started;
    an update that meets it puts the box back as it was. Harmless to the release before: it reads nothing new."""
    from tools.trialbox import doctor
    from tools.trialbox.update import UpdateFailed

    check = doctor.check_ldap_ca(doctor.DoctorInputs(env=dict(box.env), deploy=box.deploy))
    if check.status == "FAIL":
        raise UpdateFailed(f"{check.detail}. This release needs it before Authelia starts; nothing was started")
    return check.detail


#: where the host's cron files are (deploy/install.sh writes trialbox-retention there); a test points it elsewhere
CRON_DIR = Path("/etc/cron.d")


def _hourly_audit_head(box: ComposeBox) -> str:
    """10G-2 (D-1345): this release's doctor FAILs a signed audit head older than 2 h, so a box whose cron file still
    signs once a night is moved to the hourly line before its stack starts. Never fails the update (an absent or
    unreadable file is said). Harmless to the release before: its ``audit-sign`` run every hour signs every hour."""
    from tools.trialbox import audit_heads

    return audit_heads.hourly_cron(CRON_DIR)


#: name, step; in the order they run. The first two are what every release before this one ran in the updater itself.
STEPS: list[tuple[str, Callable[[ComposeBox], str]]] = [
    ("image pins", _image_pins),
    ("model key", _model_key),
    ("actor signing key", _actor_key),
    ("FHIR store password", _fhir_password),
    ("hourly audit head", _hourly_audit_head),  # 10G-2 (D-1345): before the refusal, so that step stays last
    ("hospital directory CA", _ldap_ca),  # D-722: a refusal, not a making; last, so the order before it stands
]


def _fhir_password_set(box: ComposeBox) -> str:
    """D-541: the role script gives the FHIR store's role the password the database container holds. Without one
    the role would be made with no password and the step would still say it was set: refuse before the database
    is touched. The update and ``install.sh`` run ``pre-start`` first, which makes it; this is for ``db-up`` run
    by hand."""
    from tools.trialbox.update import UpdateFailed

    if not box.env.get("TB_DB_URL", ""):
        return "no database step on this box"
    if not box.fhir_password_set():
        raise UpdateFailed(
            "TB_DB_PW_FHIR_STORE is not set in deploy/.env: run `python3 -m tools.trialbox pre-start` first"
        )
    return "yes"


def _database(box: ComposeBox) -> str:
    return box.db_on_new_settings()


def _service_roles(box: ComposeBox) -> str:
    return "set by the role script" if box.set_roles() else "no database step on this box"


def _owned_schemas(box: ComposeBox) -> str:
    return "made by the box's admin" if box.migrate_owned() else "no database step on this box"


def _service_stores(box: ComposeBox) -> str:
    done = box.migrate_stores()
    return ("migrated in a one-off container each: " + ", ".join(done)) if done else "no database step on this box"


#: name, step; in the order they run, once the database is up and before any other service starts (D-624). The
#: database comes first: the role script reads each service's password from the database container's environment,
#: so a release that adds a role needs the container on its own settings before the script runs.
DB_STEPS: list[tuple[str, Callable[[ComposeBox], str]]] = [
    ("FHIR store password is set", _fhir_password_set),  # D-541: before the container takes its settings
    ("database", _database),
    ("service roles", _service_roles),
    ("owned schemas", _owned_schemas),
    ("service stores", _service_stores),  # D-921: each service's start-time migrations, never under a health wait
]

#: command -> its steps
PHASES = {"pre-start": STEPS, "db-up": DB_STEPS}


def _run(deploy: Path, phase: str, box: ComposeBox | None) -> list[str]:
    from tools.trialbox.update import ComposeBox, UpdateFailed

    if not deploy.is_dir():
        raise UpdateFailed(f"no deploy folder {deploy}")
    box = box or ComposeBox(deploy)
    lines = []
    for name, step in PHASES[phase]:
        try:
            lines.append(f"{phase}: {name}: {step(box)}")
        except UpdateFailed as exc:  # the step's name first: the runner's message shows a command's first words only
            raise UpdateFailed(f"{name}: {exc}") from exc
    return lines


def run(deploy: Path, box: ComposeBox | None = None) -> list[str]:
    """Every step, in order; the lines for the log. Raises ``UpdateFailed`` at the first step that fails."""
    return _run(deploy, "pre-start", box)


def run_db(deploy: Path, box: ComposeBox | None = None) -> list[str]:
    """Every step of :data:`DB_STEPS`, in order; as :func:`run`."""
    return _run(deploy, "db-up", box)


def main(deploy: Path, phase: str = "pre-start") -> int:
    from tools.trialbox.update import UpdateFailed

    try:
        for line in _run(deploy, phase, None):
            print(line)
    except UpdateFailed as exc:
        print(f"{phase}: failed: {exc}", file=sys.stderr)
        return 1
    return 0
