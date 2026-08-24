"""Organization shells, invitations, and the §5.3 verification workflow."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import get_principal, require_internal
from app.auth.tokens import create_invite_token, create_resume_token
from app.config import settings
from app.db import get_db
from app.enums import (
    ActivityAction,
    NotificationChannel,
    OrgStatus,
    OrgType,
    ReferenceDomain,
    Role,
)
from app.models import Contact, Organization, OrgInvite, SupplierProfile, User
from app.rbac import Action, Principal, require
from app.rbac.scope import apply_scope
from app.schemas.common import Message, Page
from app.schemas.organization import (
    ContactIn,
    ContactOut,
    InviteCreate,
    InviteOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    VerificationDecision,
)
from app.services import activity, completeness
from app.services.notifications import EventKey, enqueue
from app.services.taxonomy import resolve

router = APIRouter(prefix="/organizations", tags=["organizations"])

# The states a reviewer may move an organization into. Anything else is a workflow bug.
_DECISION_STATES = {
    OrgStatus.VERIFIED, OrgStatus.NEEDS_INFO, OrgStatus.REJECTED,
    OrgStatus.UNDER_REVIEW, OrgStatus.SUSPENDED,
}


def _get_org_or_404(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return org


def _apply_country(db: Session, org: Organization, country_code: str | None) -> None:
    if country_code is None:
        return
    country = resolve(db, ReferenceDomain.COUNTRY, country_code)
    if country is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Unknown country '{country_code}'"
        )
    org.country_id = country.id


@router.get("", response_model=Page[OrganizationOut])
def list_organizations(
    type: OrgType | None = None,
    org_status: OrgStatus | None = None,
    search: str | None = Query(None, max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[OrganizationOut]:
    """Scoped list. An org user sees only their own row; internal staff see everything."""
    stmt = apply_scope(select(Organization), Organization, principal)
    if type is not None:
        stmt = stmt.where(Organization.type == type)
    if org_status is not None:
        stmt = stmt.where(Organization.status == org_status)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Organization.legal_name).like(pattern),
                func.lower(Organization.trade_name).like(pattern),
                func.lower(Organization.city).like(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Organization.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[OrganizationOut](
        items=[OrganizationOut.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(
    body: OrganizationCreate,
    principal: Principal = Depends(require_internal),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """Create a brand or supplier shell (§5.1 step 1, §5.2 assisted onboarding).

    Flagged `created_by_internal` because a profile our team keyed in is weaker evidence than
    one the factory filled themselves — a distinction that matters when scoring later.
    """
    require(principal, Action.CREATE, "Organization")

    if body.gst_no:
        clash = db.scalars(
            select(Organization).where(Organization.gst_no == body.gst_no)
        ).first()
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"GST {body.gst_no} is already registered to {clash.display_name}",
            )

    org = Organization(
        type=body.type,
        legal_name=body.legal_name,
        trade_name=body.trade_name,
        state=body.state,
        city=body.city,
        address=body.address,
        pincode=body.pincode,
        gst_no=body.gst_no or None,
        pan=body.pan,
        website=body.website,
        status=OrgStatus.DRAFT,
        created_by_internal=True,
        created_by_user_id=principal.user_id,
    )
    _apply_country(db, org, body.country_code)
    db.add(org)
    db.flush()

    if body.primary_contact is not None:
        db.add(Contact(org_id=org.id, is_primary=True, **body.primary_contact.model_dump()))

    if org.type == OrgType.SUPPLIER:
        db.add(SupplierProfile(org_id=org.id))

    activity.record(
        db, entity_type="Organization", entity_id=org.id, action=ActivityAction.CREATE,
        actor=principal, org_id=org.id, summary=f"Created {body.type} shell '{org.display_name}'",
    )
    db.commit()
    db.refresh(org)
    return OrganizationOut.model_validate(org)


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    org = _get_org_or_404(db, org_id)
    require(principal, Action.VIEW, org)
    return OrganizationOut.model_validate(org)


@router.patch("/{org_id}", response_model=OrganizationOut)
def update_organization(
    org_id: uuid.UUID,
    body: OrganizationUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    org = _get_org_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    payload = body.model_dump(exclude_unset=True)
    _apply_country(db, org, payload.pop("country_code", None))
    for field, value in payload.items():
        setattr(org, field, value)

    activity.record_changes(db, org, actor=principal, summary="Updated organization")

    if org.type == OrgType.SUPPLIER:
        completeness.refresh_supplier(db, org)

    db.commit()
    db.refresh(org)
    return OrganizationOut.model_validate(org)


# --------------------------------------------------------------------------- contacts
@router.get("/{org_id}/contacts", response_model=list[ContactOut])
def list_contacts(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[ContactOut]:
    org = _get_org_or_404(db, org_id)
    # Contact details are identity: a brand that has not been shown this supplier does not
    # get their phone number, however they reached this endpoint.
    require(principal, Action.VIEW_IDENTITY, org)

    rows = db.scalars(
        select(Contact).where(Contact.org_id == org_id).order_by(
            Contact.is_primary.desc(), Contact.name
        )
    ).all()
    return [ContactOut.model_validate(r) for r in rows]


@router.post("/{org_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(
    org_id: uuid.UUID,
    body: ContactIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ContactOut:
    org = _get_org_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    if body.is_primary:
        for existing in db.scalars(
            select(Contact).where(Contact.org_id == org_id, Contact.is_primary.is_(True))
        ).all():
            existing.is_primary = False

    contact = Contact(org_id=org_id, **body.model_dump())
    db.add(contact)
    if org.type == OrgType.SUPPLIER:
        db.flush()
        completeness.refresh_supplier(db, org)
    db.commit()
    db.refresh(contact)
    return ContactOut.model_validate(contact)


# --------------------------------------------------------------------------- invites
@router.post("/{org_id}/invites", response_model=InviteOut, status_code=201)
def create_invite(
    org_id: uuid.UUID,
    body: InviteCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> InviteOut:
    """Send a token-based, expiring invitation (§5.1 step 1).

    Only the token's hash is stored, so a database dump cannot be replayed as a login.
    """
    org = _get_org_or_404(db, org_id)
    require(principal, Action.INVITE, org)

    role = Role(body.role)
    if role.is_internal:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot invite an internal role")
    if role.side.value != org.type:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Role {role} does not belong to a {org.type} organization",
        )
    if not body.email and not body.phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="email or phone is required")

    invite = OrgInvite(
        org_id=org_id,
        email=body.email,
        phone=body.phone,
        role=role.value,
        token_hash="",
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invite_token_ttl_days),
        sent_by_user_id=principal.user_id,
        last_sent_at=datetime.now(timezone.utc),
        send_count=1,
    )
    db.add(invite)
    db.flush()

    token = create_invite_token(invite.id, org_id, role.value)
    from app.auth import hash_secret

    invite.token_hash = hash_secret(token)

    invite_url = f"{settings.app_base_url}/invite?token={token}"
    channels = [NotificationChannel.EMAIL] if body.email else []
    if body.phone:
        channels.append(NotificationChannel.WHATSAPP)

    payload = {
        "name": body.name or "there",
        "app_name": "Buying House",
        "inviter_org": "our sourcing team",
        "role": role.value.replace("_", " ").title(),
        "invite_url": invite_url,
        "expires_on": invite.expires_at.date().isoformat(),
    }
    # No User row exists yet, so the outbox is addressed literally.
    for channel in channels:
        enqueue(
            db, event_key=EventKey.INVITE_SENT, user=None, channels=[channel], payload=payload,
            entity_type="OrgInvite", entity_id=invite.id,
            address_override=body.email if channel == NotificationChannel.EMAIL else body.phone,
        )

    if org.status == OrgStatus.DRAFT:
        org.status = OrgStatus.INVITED

    activity.record(
        db, entity_type="Organization", entity_id=org_id, action=ActivityAction.INVITE_SENT,
        actor=principal, org_id=org_id,
        summary=f"Invited {body.email or body.phone} as {role.value}",
    )
    db.commit()
    db.refresh(invite)
    return InviteOut.model_validate(invite)


@router.get("/{org_id}/resume-link", response_model=Message)
def resume_link(
    org_id: uuid.UUID,
    principal: Principal = Depends(require_internal),
    db: Session = Depends(get_db),
) -> Message:
    """§5.2 save-and-resume: a long-lived, low-privilege link to a half-filled profile.

    Sent over WhatsApp, where it can sit in a thread for three weeks and still work.
    """
    org = _get_org_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    url = f"{settings.app_base_url}/supplier/continue?token={create_resume_token(org.id)}"
    profile = db.get(SupplierProfile, org.id)
    contact = db.scalars(
        select(Contact).where(Contact.org_id == org_id, Contact.is_primary.is_(True))
    ).first()

    if contact and (contact.whatsapp or contact.phone):
        enqueue(
            db, event_key=EventKey.RESUME_LINK, user=None,
            channels=[NotificationChannel.WHATSAPP],
            payload={
                "app_name": "Buying House",
                "resume_url": url,
                "completeness_pct": profile.completeness_pct if profile else 0,
            },
            entity_type="Organization", entity_id=org_id,
            address_override=contact.whatsapp or contact.phone,
        )
        db.commit()

    return Message(detail=url)


# --------------------------------------------------------------------- verification
@router.post("/{org_id}/verification", response_model=OrganizationOut)
def decide_verification(
    org_id: uuid.UUID,
    body: VerificationDecision,
    principal: Principal = Depends(require_internal),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """§5.3. Verification is a deliberate, audited decision, not a side effect of a form save.

    Requires Action.VERIFY, which merchandisers deliberately do not hold — a supplier becoming
    brand-facing is the moment our reputation is on the line.
    """
    org = _get_org_or_404(db, org_id)
    require(principal, Action.VERIFY, org)

    if body.decision not in _DECISION_STATES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{body.decision} is not a review decision"
        )
    if body.decision == OrgStatus.NEEDS_INFO and not body.requested_items:
        # "Incomplete" is not actionable. Name what is missing or the supplier cannot respond.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="requested_items is required when asking for more information",
        )

    previous = org.status
    org.status = body.decision
    org.verification_notes = body.notes
    if body.decision == OrgStatus.VERIFIED:
        org.verified_at = datetime.now(timezone.utc)
        org.verified_by_user_id = principal.user_id
    else:
        org.verified_at = None

    if org.type == OrgType.SUPPLIER:
        db.flush()
        completeness.refresh_supplier(db, org)

    owner = db.get(User, org.owner_user_id) if org.owner_user_id else None
    event = {
        OrgStatus.VERIFIED: EventKey.VERIFICATION_APPROVED,
        OrgStatus.NEEDS_INFO: EventKey.VERIFICATION_NEEDS_INFO,
        OrgStatus.REJECTED: EventKey.VERIFICATION_REJECTED,
    }.get(body.decision)

    if event and owner is not None:
        enqueue(
            db, event_key=event, user=owner,
            channels=[NotificationChannel.EMAIL, NotificationChannel.WHATSAPP,
                      NotificationChannel.IN_APP],
            payload={
                "app_name": "Buying House",
                "name": owner.name,
                "org_name": org.display_name,
                "reason": body.notes or "",
                "requested_items": "\n".join(f"- {i}" for i in body.requested_items),
                "resume_url": f"{settings.app_base_url}/supplier/continue"
                              f"?token={create_resume_token(org.id)}",
            },
            entity_type="Organization", entity_id=org.id,
        )

    activity.record(
        db, entity_type="Organization", entity_id=org.id,
        action=ActivityAction.VERIFICATION_DECISION, actor=principal, org_id=org.id,
        summary=f"{previous} -> {body.decision}",
        before={"status": previous}, after={"status": body.decision, "notes": body.notes},
    )
    db.commit()
    db.refresh(org)
    return OrganizationOut.model_validate(org)
