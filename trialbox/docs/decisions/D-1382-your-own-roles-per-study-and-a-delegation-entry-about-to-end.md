# D-1382 Your own roles per study on the account page, and a warning before a delegation entry ends (9f-1, 9f-4 a)

- **Task:** plan 9 cards 9f-1 and 9f-4 part (a), from review 02 (`docs/reviews/2026-11-root/02-journeys.md` §1.3, J-1
  and J-4). Lane K. · **Date:** 2026-11-19
- **Decision:**
  - **9f-1: the account page lists the signed-in person's own roles per study.** One line per delegation-log entry that
    is in force today, in a study the account sees: the study, the role (PI, sub-investigator, CRC, other, monitor), the
    ticked tasks of a sub-investigator (a PI line says "all study tasks"), and the entry's dates. It is read with
    `TeamStore.entries_for(username)`, which selects the person's own rows only; no other person's entry, no patient
    data, no new right. A person named in no log, or who sees no study, gets one sentence saying so. The home page is
    not changed in this card.
  - **9f-4 (a): an entry that ends within 14 days is warned about.** `Entry.days_left(day)` is the days from the site's
    day to the entry's last day when that is 0 to 14 and the entry is in force, else none: the warning shows at 14 days
    and not at 15, on the last day itself ("ends today"), and never for an entry already over or with no end. The day
    is the site's day (`Helpers.today`, D-270), not the server's or UTC's.
  - **Who sees it, and where:** on the study's delegation log page, to everyone that page already admits (it already
    shows every entry, with its end date, to them), naming the person, the role and the last day; and on the account
    page, to the person the entry names, on their own line. Nobody is told who could not already see the entry: no mail
    and no other page is added.
  - **Not here:** part (b), the SAE unacknowledged after N days also going to the sub-investigators and the
    coordinator. It widens who is mailed about a serious event and waits for the owner.
- **The proof:** `tests/console/test_own_roles_and_ending_entries.py`: each role sees only its own roles, a person with
  no study, the warning at 14 days and not 15 and on the last day, the site's day in Tokyo and Taipei, and no warning
  to an account that cannot open the log page; the three catalogues carry the same keys.
- **Not verified:** a native reader has not read the ja and zh-TW lines.
- **Held by:** `tests/console/test_own_roles_and_ending_entries.py`.
