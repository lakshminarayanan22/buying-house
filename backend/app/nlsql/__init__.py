"""Natural-language record editing.

You describe a change in English; the system generates SQL, runs it inside a transaction,
shows you the real before/after rows it touched, and rolls back. Nothing is committed until
you confirm.

The order matters. "Apply it, then let me undo" leaves wrong data live and readable by other
users in the meantime — and possibly already read, already notified on. Previewing inside a
transaction gives the same "here is what changed, confirm?" experience with a real diff of
real rows, and no window where the database is wrong.

Three guarantees, enforced in guard.py rather than in the prompt, because a prompt is not a
security boundary:

  * DML only, one statement, against an explicit table allowlist
  * UPDATE and DELETE must carry a WHERE clause
  * the audit trail, credentials, and the identity-reveal table are not writable here
"""
from app.nlsql.guard import SqlRejected, ValidatedStatement, validate
from app.nlsql.preview import ChangeConflict, apply_change, preview_sql

__all__ = [
    "ChangeConflict",
    "SqlRejected",
    "ValidatedStatement",
    "apply_change",
    "preview_sql",
    "validate",
]
