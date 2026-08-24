"""Access-control tests, written before the endpoints they guard (§11).

The cases that matter are the denials. A permissive bug here is invisible in the UI and fatal
to the business model, so each rule from §2 gets an explicit negative test.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

import app.models as m
from app.enums import OrgStatus, OrgType, Role, UserStatus
from app.rbac import Action, Principal, can, require
from app.rbac.policy import AccessDenied, redact_identity
from app.rbac.scope import apply_scope, directory_filter, scope_filter
from tests.conftest import make_org, make_user, principal_for


# --------------------------------------------------------------- the cross-side rule
def test_brand_cannot_see_supplier_without_a_reveal(db, brand, supplier, brand_principal):
    assert not can(brand_principal, Action.VIEW, supplier)
    assert not can(brand_principal, Action.VIEW_IDENTITY, supplier)


def test_brand_can_see_supplier_once_revealed(db, brand, supplier):
    user = make_user(db, brand, Role.BRAND_ADMIN)
    revealed = principal_for(user, brand, revealed={supplier.id})
    assert can(revealed, Action.VIEW, supplier)
    assert can(revealed, Action.VIEW_IDENTITY, supplier)


def test_reveal_does_not_grant_write(db, brand, supplier):
    """Seeing a factory is not managing it — a reveal is read-only, in both directions."""
    user = make_user(db, brand, Role.BRAND_ADMIN)
    revealed = principal_for(user, brand, revealed={supplier.id})
    for action in (Action.UPDATE, Action.DELETE, Action.SUBMIT, Action.INVITE):
        assert not can(revealed, action, supplier), action


def test_supplier_cannot_see_another_supplier_even_if_revealed(db, supplier, other_supplier):
    """A reveal id must never be usable to peer sideways at a competitor."""
    user = make_user(db, supplier, Role.SUPPLIER_ADMIN)
    actor = principal_for(user, supplier, revealed={other_supplier.id})
    assert not can(actor, Action.VIEW, other_supplier)


def test_brand_cannot_see_another_brand(db, brand):
    other_brand = make_org(db, OrgType.BRAND, "Southgate Retail Ltd")
    user = make_user(db, brand, Role.BRAND_ADMIN)
    actor = principal_for(user, brand, revealed={other_brand.id})
    assert not can(actor, Action.VIEW, other_brand)


# --------------------------------------------------------------- internal-only data
def test_internal_notes_are_invisible_to_the_org_they_describe(db, supplier, supplier_principal):
    note = m.Note(
        entity_type="Organization", entity_id=supplier.id, org_id=supplier.id,
        body="Owner was evasive about the subcontracting question.", is_internal_only=True,
    )
    db.add(note)
    db.commit()
    assert not can(supplier_principal, Action.VIEW, note)


def test_shared_note_on_own_org_is_visible(db, supplier, supplier_principal):
    note = m.Note(
        entity_type="Organization", entity_id=supplier.id, org_id=supplier.id,
        body="Please upload your GOTS scope certificate.", is_internal_only=False,
    )
    db.add(note)
    db.commit()
    assert can(supplier_principal, Action.VIEW, note)


def test_supplier_cannot_read_its_own_performance_scores(db, supplier, supplier_principal):
    """Our grading of a factory is ours. Exposing it invites gaming rather than improvement."""
    perf = m.SupplierPerformance(org_id=supplier.id, period_start=date(2026, 7, 1), composite_score=71.4)
    db.add(perf)
    db.commit()
    assert not can(supplier_principal, Action.VIEW, perf)


def test_org_users_cannot_reach_the_activity_log(db, supplier, supplier_principal):
    log = m.ActivityLog(entity_type="Organization", entity_id=supplier.id, org_id=supplier.id,
                        action="UPDATE")
    db.add(log)
    db.commit()
    assert not can(supplier_principal, Action.VIEW, log)


# --------------------------------------------------------------- own-org confinement
def test_supplier_can_manage_its_own_profile(db, supplier, supplier_principal, taxonomy):
    process = m.SupplierProcess(org_id=supplier.id, process_type_id=taxonomy["knitting"].id)
    db.add(process)
    db.commit()
    assert can(supplier_principal, Action.VIEW, process)
    assert can(supplier_principal, Action.UPDATE, process)


def test_supplier_cannot_touch_another_suppliers_process(db, other_supplier, supplier_principal,
                                                         taxonomy):
    process = m.SupplierProcess(org_id=other_supplier.id, process_type_id=taxonomy["dyeing"].id)
    db.add(process)
    db.commit()
    assert not can(supplier_principal, Action.VIEW, process)
    assert not can(supplier_principal, Action.UPDATE, process)


def test_plain_user_cannot_invite_or_manage_users(db, supplier):
    user = make_user(db, supplier, Role.SUPPLIER_USER)
    actor = principal_for(user, supplier)
    assert not can(actor, Action.INVITE, supplier)
    assert not can(actor, Action.MANAGE_USERS, supplier)


def test_disabled_user_can_do_nothing(db, supplier):
    user = make_user(db, supplier, Role.SUPPLIER_ADMIN)
    user.status = UserStatus.DISABLED
    actor = principal_for(user, supplier)
    assert not can(actor, Action.VIEW, supplier)


# --------------------------------------------------------------- internal roles
def test_management_is_read_only(db, supplier):
    user = make_user(db, None, Role.INTERNAL_MANAGEMENT)
    actor = principal_for(user, None)
    assert can(actor, Action.VIEW, supplier)
    assert can(actor, Action.VIEW_INTERNAL, supplier)
    assert not can(actor, Action.UPDATE, supplier)
    assert not can(actor, Action.VERIFY, supplier)


def test_merchandiser_cannot_verify_or_reveal(db, supplier, merchandiser_principal):
    """Verification and identity reveal are the two decisions that need a second pair of eyes."""
    assert not can(merchandiser_principal, Action.VERIFY, supplier)
    assert not can(merchandiser_principal, Action.REVEAL_IDENTITY, supplier)


def test_sourcing_head_can_verify_and_reveal(db, supplier):
    user = make_user(db, None, Role.INTERNAL_SOURCING_HEAD)
    actor = principal_for(user, None)
    assert can(actor, Action.VERIFY, supplier)
    assert can(actor, Action.REVEAL_IDENTITY, supplier)


def test_only_super_admin_manages_master_data(db, taxonomy, merchandiser_principal):
    item = taxonomy["cotton"]
    assert not can(merchandiser_principal, Action.MANAGE_MASTER_DATA, item)
    admin = principal_for(make_user(db, None, Role.INTERNAL_SUPER_ADMIN), None)
    assert can(admin, Action.MANAGE_MASTER_DATA, item)


def test_taxonomy_is_readable_by_everyone(db, taxonomy, supplier_principal, brand_principal):
    """A supplier must be able to pick "Single Jersey" from the list to fill in their profile."""
    assert can(supplier_principal, Action.VIEW, taxonomy["single_jersey"])
    assert can(brand_principal, Action.VIEW, taxonomy["gots"])
    assert not can(supplier_principal, Action.UPDATE, taxonomy["single_jersey"])


# --------------------------------------------------------------- query scoping
def test_scope_filter_hides_other_orgs_from_a_list_query(db, supplier, other_supplier,
                                                         supplier_principal, taxonomy):
    db.add_all([
        m.SupplierProcess(org_id=supplier.id, process_type_id=taxonomy["knitting"].id),
        m.SupplierProcess(org_id=other_supplier.id, process_type_id=taxonomy["knitting"].id),
    ])
    db.commit()

    rows = db.scalars(
        apply_scope(select(m.SupplierProcess), m.SupplierProcess, supplier_principal)
    ).all()
    assert [r.org_id for r in rows] == [supplier.id]


def test_scope_filter_on_organization_uses_the_primary_key(db, brand, supplier, brand_principal):
    rows = db.scalars(apply_scope(select(m.Organization), m.Organization, brand_principal)).all()
    assert [r.id for r in rows] == [brand.id]


def test_scope_filter_excludes_unverified_orgs_even_when_revealed(db, brand, supplier):
    """A reveal on a record still under review must not publish our draft of it."""
    supplier.status = OrgStatus.UNDER_REVIEW
    db.commit()
    user = make_user(db, brand, Role.BRAND_ADMIN)
    actor = principal_for(user, brand, revealed={supplier.id})
    rows = db.scalars(apply_scope(select(m.Organization), m.Organization, actor)).all()
    assert supplier.id not in [r.id for r in rows]


def test_scope_filter_returns_nothing_for_an_orgless_org_user(db, supplier):
    """A corrupt principal must fail closed, not fall through to an unfiltered query."""
    broken = Principal(user_id=uuid.uuid4(), role=Role.SUPPLIER_ADMIN, org_id=None)
    rows = db.scalars(apply_scope(select(m.Organization), m.Organization, broken)).all()
    assert rows == []


def test_scope_filter_hides_internal_only_notes_in_list_queries(db, supplier, supplier_principal):
    db.add_all([
        m.Note(entity_type="Organization", entity_id=supplier.id, org_id=supplier.id,
               body="internal", is_internal_only=True),
        m.Note(entity_type="Organization", entity_id=supplier.id, org_id=supplier.id,
               body="shared", is_internal_only=False),
    ])
    db.commit()
    rows = db.scalars(apply_scope(select(m.Note), m.Note, supplier_principal)).all()
    assert [r.body for r in rows] == ["shared"]


def test_internal_staff_see_everything(db, supplier, other_supplier, merchandiser_principal):
    rows = db.scalars(
        apply_scope(select(m.Organization), m.Organization, merchandiser_principal)
    ).all()
    assert {r.id for r in rows} == {supplier.id, other_supplier.id}


def test_directory_shows_the_counterparty_side_only(db, brand, supplier, brand_principal):
    """A brand browsing the directory sees verified suppliers — and no other brands."""
    make_org(db, OrgType.BRAND, "Southgate Retail Ltd")
    unverified = make_org(db, OrgType.SUPPLIER, "Half Filled Unit", status=OrgStatus.DRAFT)

    rows = db.scalars(
        select(m.Organization).where(directory_filter(m.Organization, brand_principal))
    ).all()
    ids = {r.id for r in rows}
    assert ids == {supplier.id}
    assert unverified.id not in ids


# --------------------------------------------------------------- redaction
def test_directory_results_are_redacted_until_reveal(db, supplier, brand_principal):
    payload = {
        "id": str(supplier.id), "legal_name": supplier.legal_name, "city": "Tiruppur",
        "phone": "+91 90000 00000", "monthly_capacity_value": 120000,
    }
    redacted = redact_identity(brand_principal, supplier, payload)
    assert "legal_name" not in redacted and "phone" not in redacted
    # The point of the directory survives redaction: capability data still comes through.
    assert redacted["city"] == "Tiruppur"
    assert redacted["monthly_capacity_value"] == 120000


def test_redaction_is_a_no_op_once_revealed(db, brand, supplier):
    user = make_user(db, brand, Role.BRAND_ADMIN)
    actor = principal_for(user, brand, revealed={supplier.id})
    payload = {"legal_name": supplier.legal_name, "phone": "+91 90000 00000"}
    assert redact_identity(actor, supplier, payload) == payload


def test_require_raises_access_denied(db, supplier, brand_principal):
    with pytest.raises(AccessDenied):
        require(brand_principal, Action.UPDATE, supplier)
