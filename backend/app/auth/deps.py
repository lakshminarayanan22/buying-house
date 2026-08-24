"""FastAPI dependencies. Resolving the caller and building their Principal happens here only."""
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.tokens import TokenError, verify_session_token
from app.db import get_db
from app.enums import Role, UserStatus
from app.models import BrandSupplierReveal, User
from app.rbac import Action, Principal
from app.rbac.policy import AccessDenied


def _load_revealed_org_ids(db: Session, user: User) -> frozenset[uuid.UUID]:
    """The counterparties this user's org is allowed to identify.

    Loaded once per request and frozen into the Principal, so no later code path can widen it,
    and the policy layer never has to touch the database to answer a question.
    """
    if user.org_id is None:
        return frozenset()

    rows = db.execute(
        select(
            BrandSupplierReveal.brand_org_id,
            BrandSupplierReveal.supplier_org_id,
            BrandSupplierReveal.brand_sees_supplier,
            BrandSupplierReveal.supplier_sees_brand,
        ).where(
            BrandSupplierReveal.revoked_at.is_(None),
            or_(
                BrandSupplierReveal.brand_org_id == user.org_id,
                BrandSupplierReveal.supplier_org_id == user.org_id,
            ),
        )
    ).all()

    revealed: set[uuid.UUID] = set()
    for brand_id, supplier_id, brand_sees, supplier_sees in rows:
        # Each direction is granted independently: being visible to a brand does not entitle a
        # supplier to see the brand.
        if brand_id == user.org_id and brand_sees:
            revealed.add(supplier_id)
        elif supplier_id == user.org_id and supplier_sees:
            revealed.add(brand_id)
    return frozenset(revealed)


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    try:
        user_id, token_version = verify_session_token(token)
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    # A stale token_version means the account was disabled or its password changed after this
    # token was issued.
    if token_version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session no longer valid")

    return user


def get_principal(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Principal:
    return Principal.from_user(user, _load_revealed_org_ids(db, user))


def require_internal(principal: Principal = Depends(get_principal)) -> Principal:
    """Gate for the internal console. Brand and supplier tokens are rejected outright."""
    if not principal.is_internal:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Internal access only")
    return principal


def require_role(*roles: Role):
    """Dependency factory for endpoints restricted to specific roles."""

    allowed = set(roles)

    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not permitted for your role")
        return principal

    return _dep


def access_denied_handler(_request, exc: AccessDenied):
    """Maps the policy layer's exception to 403 without leaking whether the row exists."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=403, content={"detail": str(exc)})
