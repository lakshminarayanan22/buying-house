"""Query-layer tenancy. Written once so no individual endpoint has to remember it.

§8: "single database, org_id on every tenant-scoped table, enforced at the query layer. Write
the access-control helper once and route every query through it. This is where two-sided
marketplaces leak data."

`can()` guards a row you already hold. This module guards the rows you are allowed to *find* —
the leak that actually happens in practice is a list endpoint with a forgotten WHERE clause,
not a detail endpoint with a missing check.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Select, false, true
from sqlalchemy.sql.elements import ColumnElement

from app.enums import OrgStatus, OrgType
from app.rbac.policy import Principal


def visible_org_ids(actor: Principal) -> frozenset[uuid.UUID] | None:
    """Org ids this principal may read. None means "unrestricted" (internal staff)."""
    if actor.is_internal:
        return None
    if actor.org_id is None:
        return frozenset()
    return frozenset({actor.org_id}) | actor.revealed_org_ids


def scope_filter(model, actor: Principal) -> ColumnElement[bool]:
    """A boolean clause restricting `model` to what `actor` may see.

    Returns `false()` rather than raising when a principal may see nothing, so a list endpoint
    degrades to an empty result instead of an error — and never to an unfiltered one.
    """
    if actor.is_internal:
        return true()

    allowed = visible_org_ids(actor)
    if not allowed:
        return false()

    clauses: list[ColumnElement[bool]] = []

    # The Organization table keys tenancy on its own primary key.
    if model.__name__ == "Organization":
        clauses.append(model.id.in_(allowed))
        # Another org is only ever visible once VERIFIED, even after a reveal: an unverified
        # record is our working draft about them, not a published profile.
        clauses.append(
            (model.id == actor.org_id) | (model.status == OrgStatus.VERIFIED.value)
        )
    elif hasattr(model, "org_id"):
        clauses.append(model.org_id.in_(allowed))
    else:
        # No tenant column and not explicitly public: deny rather than assume it is shared.
        return false()

    # Internal-only rows never cross the boundary, whatever the org scoping says.
    if hasattr(model, "is_internal_only"):
        clauses.append(model.is_internal_only.is_(False))

    clause = clauses[0]
    for extra in clauses[1:]:
        clause = clause & extra
    return clause


def apply_scope(stmt: Select, model, actor: Principal) -> Select:
    """Convenience wrapper: `select(Model)` -> the same select, tenancy-filtered."""
    return stmt.where(scope_filter(model, actor))


def directory_filter(model, actor: Principal) -> ColumnElement[bool]:
    """Scoping for the cross-side supplier/brand directory.

    Unlike `scope_filter`, this deliberately admits organizations the actor has NOT been
    revealed — that is the point of a directory. What it withholds is identity: rows come back
    for filtering and comparison, and `redact_identity` removes the name and contact details
    until a reveal exists. Internal staff see everything, unfiltered.
    """
    if actor.is_internal:
        return true()
    if actor.org_id is None:
        return false()

    counterparty = OrgType.SUPPLIER if actor.org_type == OrgType.BRAND else OrgType.BRAND
    if model.__name__ == "Organization":
        return (model.type == counterparty.value) & (model.status == OrgStatus.VERIFIED.value)
    return false()
