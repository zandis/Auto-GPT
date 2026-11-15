# D-777 The mark bar stays in view on the desktop; an ended session says why, returns and keeps the note

- **Task:** NEW-UX-1 and NEW-UX-6 (the deep review's UX-001, UX-007); the code-complete sprint, item 1 · **Date:** 2026-11-15
- **UX-001:** the desktop week panel's mark bar is sticky at the bottom of the screen (`.chartp` clips instead of hiding its overflow).
- **UX-007:** a session cookie naming no live session sends the person to `/login?why=idle`, which says why; the page they were on (a GET's own path, a POST's same-origin Referer) is kept in a 15-minute cookie and is where both sign-in paths land (`console.next_page`; only this console's paths, never sign-in or API routes).
- **The note:** the console's script keeps a mark's note in the tab's session storage while it is typed, restores it on that patient's page, never over a newer note, and drops it once the mark is saved.
- **Held by:** `tests/console/test_mark_bar_in_view_and_expiry_keeps_the_note.py`; `test_identity.py`'s pinned idle redirect is now `/login?why=idle` (a deliberate change).
