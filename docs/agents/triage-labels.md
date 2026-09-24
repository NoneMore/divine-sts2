# Triage labels

`issue-tracker.md` records triage state as a `Status:` line near the top of each issue file, and
points here for the role strings that line takes. These are them.

| Role | `Status:` string | Meaning |
| --- | --- | --- |
| Needs evaluation | `needs-triage` | No one has yet decided what to do with this issue |
| Waiting on the reporter | `needs-info` | Cannot proceed without more information |
| Fully specified, agent-ready | `ready-for-agent` | Specified well enough for an unattended agent to implement |
| Needs a human | `ready-for-human` | Requires human implementation |
| Will not be actioned | `wontfix` | Deliberately not done |
| Implemented | `done` | Every checklist item in the file is satisfied |

`claimed` and `resolved` are the two further strings `/wayfinder`'s map-and-child-ticket flow uses,
and they mean what `issue-tracker.md` says there: taken, and answered with an `## Answer` heading.

`done` is the string this repository's tickets actually use in practice, so it is listed here rather
than left to be invented per file. A status line records where an issue stands, not what happened:
a ticket that reached `done` still owes the reader a `## Comments` entry naming what changed, and a
ticket whose checklist is satisfied but whose status line still reads `ready-for-agent` is a defect
in the ticket, not a ticket that is still open.
