"""`can(user, action, resource)` — the single authority on who may do what.

§11 lists leaking identity across sides as a project killer, so three rules are structural
here rather than conventional:

1. A brand user and a supplier user can never resolve each other's organization unless a
   BrandSupplierReveal row explicitly says so. Absence of a reveal is a denial, not a gap.
2. Anything marked `is_internal_only` is invisible outside internal staff, full stop.
3. An org user is confined to their own org_id. There is no "and also..." clause.

Deny is the default: an unknown (role, resource, action) triple returns False rather than
falling through to permissive behaviour.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.enums import OrgStatus, OrgType, Role, Side, UserStatus


class Action(StrEnum):
    VIEW = "VIEW"
    # Identity-bearing fields (legal name, address, contacts, documents). Separated from VIEW
    # because the whole business model is that you can see a capability without seeing a name.
    VIEW_IDENTITY = "VIEW_IDENTITY"
    VIEW_INTERNAL = "VIEW_INTERNAL"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SUBMIT = "SUBMIT"
    VERIFY = "VERIFY"
    INVITE = "INVITE"
    REVEAL_IDENTITY = "REVEAL_IDENTITY"
    MANAGE_MASTER_DATA = "MANAGE_MASTER_DATA"
    MANAGE_USERS = "MANAGE_USERS"
    BULK_IMPORT = "BULK_IMPORT"
    EXPORT = "EXPORT"


class AccessDenied(Exception):
    """Raised by require(). The API layer maps this to 403."""

    def __init__(self, action: Action, resource_type: str, detail: str | None = None):
        self.action, self.resource_type, self.detail = action, resource_type, detail
        super().__init__(detail or f"Not permitted to {action} {resource_type}")


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, reduced to what authorization actually needs.

    Deliberately not the ORM User: a detached, immutable value cannot be mutated mid-request
    into granting something, and it keeps policy tests free of database fixtures.
    """

    user_id: uuid.UUID
    role: Role
    org_id: uuid.UUID | None
    org_type: OrgType | None = None
    status: UserStatus = UserStatus.ACTIVE
    # Supplier orgs that this brand principal may identify, and vice versa. Loaded once per
    # request from BrandSupplierReveal; empty for internal users, who see everything.
    revealed_org_ids: frozenset[uuid.UUID] = frozenset()

    @property
    def is_internal(self) -> bool:
        return self.role.is_internal

    @property
    def side(self) -> Side:
        return self.role.side

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @classmethod
    def from_user(cls, user, revealed_org_ids: frozenset[uuid.UUID] = frozenset()) -> Principal:
        return cls(
            user_id=user.id,
            role=Role(user.role),
            org_id=user.org_id,
            org_type=OrgType(user.organization.type) if user.organization else None,
            status=UserStatus(user.status),
            revealed_org_ids=revealed_org_ids,
        )


# --------------------------------------------------------------------------- role grants
#
# Internal capability sets. Anything not listed is denied.

_INTERNAL_GRANTS: dict[Role, set[Action]] = {
    Role.INTERNAL_SUPER_ADMIN: set(Action),
    Role.INTERNAL_SOURCING_HEAD: {
        Action.VIEW, Action.VIEW_IDENTITY, Action.VIEW_INTERNAL, Action.CREATE, Action.UPDATE,
        Action.SUBMIT, Action.VERIFY, Action.INVITE, Action.REVEAL_IDENTITY,
        Action.BULK_IMPORT, Action.EXPORT,
    },
    Role.INTERNAL_MERCHANDISER: {
        Action.VIEW, Action.VIEW_IDENTITY, Action.VIEW_INTERNAL, Action.CREATE, Action.UPDATE,
        Action.SUBMIT, Action.INVITE, Action.BULK_IMPORT, Action.EXPORT,
    },
    Role.INTERNAL_QA: {
        Action.VIEW, Action.VIEW_IDENTITY, Action.VIEW_INTERNAL, Action.CREATE, Action.UPDATE,
        Action.VERIFY, Action.EXPORT,
    },
    # Management reads the business; it does not edit records. Keeping it read-only means a
    # dashboard login is never a path to silently changing a price.
    Role.INTERNAL_MANAGEMENT: {
        Action.VIEW, Action.VIEW_IDENTITY, Action.VIEW_INTERNAL, Action.EXPORT,
    },
}

# Org-side grants, applied only ever to the principal's OWN organization.
_OWN_ORG_GRANTS: dict[Role, set[Action]] = {
    Role.BRAND_ADMIN: {
        Action.VIEW, Action.VIEW_IDENTITY, Action.CREATE, Action.UPDATE, Action.DELETE,
        Action.SUBMIT, Action.INVITE, Action.MANAGE_USERS, Action.EXPORT,
    },
    Role.BRAND_USER: {Action.VIEW, Action.VIEW_IDENTITY, Action.CREATE, Action.UPDATE},
    Role.SUPPLIER_ADMIN: {
        Action.VIEW, Action.VIEW_IDENTITY, Action.CREATE, Action.UPDATE, Action.DELETE,
        Action.SUBMIT, Action.INVITE, Action.MANAGE_USERS,
    },
    Role.SUPPLIER_USER: {Action.VIEW, Action.VIEW_IDENTITY, Action.CREATE, Action.UPDATE},
}

# Master data is read by everyone (the taxonomy is not secret) and written only by internal
# staff who hold MANAGE_MASTER_DATA.
_PUBLIC_READ_TYPES = {"ReferenceItem", "ReferenceAlias"}

# Resources an org user must never touch even for their own org, because the value of the
# field is a judgment we make *about* them.
_INTERNAL_ONLY_TYPES = {
    "ActivityLog",
    "BrandSupplierReveal",
    "ImportBatch",
    "SupplierPerformance",
    "UnmappedTerm",
}

# Fields on a supplier/brand record that constitute identity, withheld until a reveal.
IDENTITY_FIELDS = frozenset(
    {
        "legal_name", "trade_name", "address", "website", "gst_no", "pan", "iec_code",
        "email", "phone", "whatsapp", "owner_user_id",
    }
)


@dataclass(frozen=True)
class ResourceRef:
    """What the policy needs to know about the thing being acted on.

    Built by `describe()` from an ORM object, or constructed directly for a not-yet-created
    row (CREATE has no instance to inspect).
    """

    type: str
    org_id: uuid.UUID | None = None
    org_type: OrgType | None = None
    is_internal_only: bool = False
    owner_user_id: uuid.UUID | None = None
    status: str | None = None


def describe(obj: Any) -> ResourceRef:
    """Reduce an ORM instance (or a ResourceRef, or a bare type name) to a ResourceRef."""
    if isinstance(obj, ResourceRef):
        return obj
    if isinstance(obj, str):
        return ResourceRef(type=obj)

    type_name = type(obj).__name__
    org_id = getattr(obj, "org_id", None)
    org_type = None

    # An Organization is its own tenant: its PK is the org_id every other table points at.
    if type_name == "Organization":
        org_id = obj.id
        org_type = OrgType(obj.type)

    raw_type = getattr(obj, "org_type", None)
    if org_type is None and raw_type is not None:
        org_type = OrgType(raw_type)

    return ResourceRef(
        type=type_name,
        org_id=org_id,
        org_type=org_type,
        is_internal_only=bool(getattr(obj, "is_internal_only", False)),
        owner_user_id=getattr(obj, "owner_user_id", None),
        status=str(getattr(obj, "status", "") or "") or None,
    )


def can(actor: Principal, action: Action, resource: Any) -> bool:
    """Return whether `actor` may perform `action` on `resource`. Deny by default."""
    ref = describe(resource)

    if not actor.is_active:
        return False

    # --- internal staff -----------------------------------------------------
    if actor.is_internal:
        grants = _INTERNAL_GRANTS.get(actor.role, set())
        if action not in grants:
            return False
        if ref.type in _PUBLIC_READ_TYPES and action in {
            Action.CREATE, Action.UPDATE, Action.DELETE, Action.MANAGE_MASTER_DATA
        }:
            return Action.MANAGE_MASTER_DATA in grants
        return True

    # --- brand / supplier users --------------------------------------------
    if actor.org_id is None:
        # A non-internal role with no organization violates the app_user check constraint;
        # treat it as a corrupt principal rather than guessing what it should see.
        return False

    if action in {Action.VIEW_INTERNAL, Action.VERIFY, Action.REVEAL_IDENTITY,
                  Action.MANAGE_MASTER_DATA, Action.BULK_IMPORT}:
        return False

    if ref.is_internal_only:
        return False

    if ref.type in _INTERNAL_ONLY_TYPES:
        return False

    # Taxonomy is readable by everyone; a supplier must be able to pick "Single Jersey".
    if ref.type in _PUBLIC_READ_TYPES:
        return action == Action.VIEW

    grants = _OWN_ORG_GRANTS.get(actor.role, set())
    if action not in grants:
        return False

    if ref.org_id is None:
        # Unscoped rows (master data aside) are internal by construction.
        return False

    if ref.org_id == actor.org_id:
        return True

    # --- the cross-side rule ------------------------------------------------
    # Another organization. The only way this is ever visible is an explicit reveal, and even
    # then it is read-only and limited to the counterparty side.
    if action not in {Action.VIEW, Action.VIEW_IDENTITY}:
        return False
    if ref.org_type is not None and ref.org_type == actor.org_type:
        # A brand may never see another brand, nor a supplier another supplier — there is no
        # business reason, and it is the likeliest accidental leak.
        return False
    return ref.org_id in actor.revealed_org_ids


def require(actor: Principal, action: Action, resource: Any) -> None:
    """`can`, but raises AccessDenied. Use this at the call site; the API maps it to 403."""
    if not can(actor, action, resource):
        ref = describe(resource)
        raise AccessDenied(action, ref.type)


def redact_identity(actor: Principal, resource: Any, payload: dict) -> dict:
    """Strip identity fields the actor may see the *record* but not the *identity* of.

    Used when a brand browses matched capabilities: they get the capability row and a masked
    label, and only a reveal turns it into a factory with a name and a phone number.
    """
    if can(actor, Action.VIEW_IDENTITY, resource):
        return payload
    return {k: v for k, v in payload.items() if k not in IDENTITY_FIELDS}


def is_directory_visible(org_status: OrgStatus) -> bool:
    """Whether an org may appear to the other side at all, regardless of who is asking."""
    return org_status == OrgStatus.VERIFIED
