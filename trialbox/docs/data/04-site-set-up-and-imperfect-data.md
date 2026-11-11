# 4. Site set-up and imperfect data

The readiness page shows trial, patients and trial records as green, amber or red, with what is missing (D-131,
D-135). A site can start with a protocol and pasted charts only.

- **Proposed facts.** A fact a model reads from a chart is *proposed*, shown beside its quote, and goes only to the
  lake's `site_fact` table. The compiled SQL never reads it, so it can never count as met or exclude; a decided answer
  it could change becomes unknown (reason `proposed_fact`) until a coordinator confirms it with one tap.
- **Safe fixes** made automatically and listed: era and 民國 dates, full-width characters, units, merged cells.
  Everything else goes to a "please check" list.
- **Code mapping** once per site; patients from several inputs joined by pseudonym.
