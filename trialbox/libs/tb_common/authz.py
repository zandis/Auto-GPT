"""Command authorisation (SPEC §10.1 "Users: none"): sender address + ``settings.permissions``."""

from __future__ import annotations

from tb_contracts import Settings


def norm(addr: str) -> str:
    return addr.strip().strip("<>").lower()


def group_members(settings: Settings, group: str) -> set[str]:
    al = settings.allowlist
    groups: dict[str, list[str]] = {
        "senders": list(al.senders),
        "physicians": list(al.physicians or []),
        "alliance_sites": list(al.alliance_sites or []),
        "reviewers": list(settings.reviewers or []),
    }
    if "@" in group:
        return {norm(group)}
    return {norm(a) for a in groups.get(group, [])}


def known_senders(settings: Settings) -> set[str]:
    out: set[str] = set()
    for g in ("senders", "physicians", "alliance_sites", "reviewers"):
        out |= group_members(settings, g)
    for groups in settings.permissions.values():
        for g in groups:
            if "@" in g:
                out.add(norm(g))
    return out


def allowed(settings: Settings, command: str, sender: str) -> bool:
    """True when ``sender`` may issue ``command``; commands without an entry default to the ``senders`` group."""
    who = norm(sender)
    groups = settings.permissions.get(command) or ["senders"]
    return any(who in group_members(settings, g) for g in groups)
