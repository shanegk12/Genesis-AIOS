# Decision log entry template

Paste at the **top** of `decisions/log.md`, directly under the `---` separator.
The log is newest-first; appending to the bottom puts a new decision in the
oldest position, which is a mistake this AIOS has already made once.

Keep it terse. The `why` is the part future-you needs; the `what` is usually
recoverable from git.

---

## YYYY-MM-DD - Short title in plain language

**Decision:** What was decided, stated so someone who was not in the room can act on it.

**Why:** The reasoning and the constraints. Include what would change your mind, because
that is what makes the entry useful when circumstances shift.

**Alternatives considered:** What else was on the table and why it lost. An entry with no
alternatives usually means the decision was not actually a decision.

**Verified / not verified:** What you confirmed and how. Anything you assumed rather than
checked belongs here, explicitly. A decision recorded as settled when it was only assumed
becomes a false fact the whole system trusts later.

**Owner:** Who is accountable, and for which part.
