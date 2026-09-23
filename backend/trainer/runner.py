"""Drafting SQL with XiYanSQL and running it — always against ecolink_eval, never the app's data.

Everything here goes through the production pieces rather than reimplementing them: the same
prompt (`_sql_prompt`), the same cleanup (`_clean_sql`), the same guard, and for writes the same
preview-inside-a-rolled-back-transaction the app uses. A correction that works here therefore
works in the Ask box, which is the entire point of collecting them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.chat import guard
from app.chat.branches import _clean_sql, _sql_prompt, preview_write
from app.chat.llm import sql_model
from app.config import settings

EVAL_DB = "ecolink_eval"

_factory = None


def eval_sessionmaker():
    """Sessions on the evaluation database. Refuses to point anywhere else — a trainer that can
    write to the real database is one misconfiguration away from editing live deals."""
    global _factory
    if _factory is None:
        url = make_url(settings.database_url).set(database=EVAL_DB)
        if url.database != EVAL_DB:
            raise RuntimeError(f"the trainer only runs against {EVAL_DB}")
        _factory = sessionmaker(bind=create_engine(url.render_as_string(hide_password=False)))
    return _factory


@dataclass
class Result:
    """What running one statement produced — rows for a read, a diff for a write."""
    ok: bool
    kind: str = ""
    error: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    affected: int = 0
    diff: list[dict] = field(default_factory=list)
    truncated: bool = False


def draft(question: str, *, is_admin: bool) -> tuple[str, str]:
    """Ask the configured SQL model for a query. Returns (sql, prompt-was-XiYan's-layout?)."""
    model = sql_model(max_tokens=1200)
    prompt = _sql_prompt(question, is_admin=is_admin)
    return _clean_sql(model.invoke(prompt).content), prompt


def run(sql: str, *, allow_write: bool) -> Result:
    """Run a statement against the evaluation database and describe what it did.

    Reads return their rows. Writes are executed and rolled back, so the trainer can show the
    real before-and-after without ever changing the data a later question depends on.
    """
    try:
        checked = guard.check(sql, allow_write=allow_write)
    except guard.SqlRejected as exc:
        return Result(ok=False, error=f"The guard refused this: {exc}")

    if checked.kind is guard.Kind.SELECT:
        db = eval_sessionmaker()()
        try:
            db.execute(text(f"SET LOCAL statement_timeout = {settings.sql_statement_timeout_ms}"))
            result = db.execute(text(checked.sql))
            columns = list(result.keys())
            rows = result.fetchmany(201)
            return Result(ok=True, kind="SELECT", columns=columns,
                          rows=[dict(zip(columns, (_readable(v) for v in r))) for r in rows[:200]],
                          truncated=len(rows) > 200)
        except Exception as exc:                        # noqa: BLE001 — the error is the finding
            return Result(ok=False, kind="SELECT", error=str(exc).strip().split("\n")[0])
        finally:
            db.rollback()
            db.close()

    try:
        preview = preview_write(checked, session_factory=eval_sessionmaker())
    except Exception as exc:                            # noqa: BLE001
        return Result(ok=False, kind=checked.kind.value, error=str(exc).strip().split("\n")[0])
    return Result(ok=True, kind=preview["kind"], affected=preview["affected"],
                  diff=preview["diff"], rows=preview["after"] or preview["before"])


def _readable(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, UUID)):
        return str(value)
    return value
