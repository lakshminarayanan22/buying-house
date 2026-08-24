"""Code-level controlled vocabularies.

These are enums, not master data, because business logic branches on them. Anything a
Super Admin should be able to add without a deploy (process types, certifications, product
categories, fibres...) lives in the `reference_item` table instead — see models/reference.py.
"""
from enum import StrEnum


class OrgType(StrEnum):
    BRAND = "BRAND"
    SUPPLIER = "SUPPLIER"


class OrgStatus(StrEnum):
    """§5.3 verification workflow. INVITED precedes the org ever logging in."""

    INVITED = "INVITED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class SupplierTier(StrEnum):
    """§5.2 progressive profiling. A supplier is usable at TIER_1 and only brand-facing at TIER_3."""

    TIER_1_REGISTERED = "TIER_1_REGISTERED"
    TIER_2_PROFILED = "TIER_2_PROFILED"
    TIER_3_VERIFIED = "TIER_3_VERIFIED"


class Role(StrEnum):
    """§2. INTERNAL_* users have org_id NULL; brand/supplier users are always org-scoped."""

    INTERNAL_SUPER_ADMIN = "INTERNAL_SUPER_ADMIN"
    INTERNAL_MANAGEMENT = "INTERNAL_MANAGEMENT"
    INTERNAL_SOURCING_HEAD = "INTERNAL_SOURCING_HEAD"
    INTERNAL_MERCHANDISER = "INTERNAL_MERCHANDISER"
    INTERNAL_QA = "INTERNAL_QA"
    BRAND_ADMIN = "BRAND_ADMIN"
    BRAND_USER = "BRAND_USER"
    SUPPLIER_ADMIN = "SUPPLIER_ADMIN"
    SUPPLIER_USER = "SUPPLIER_USER"

    @property
    def is_internal(self) -> bool:
        return self.value.startswith("INTERNAL_")

    @property
    def side(self) -> "Side":
        if self.is_internal:
            return Side.INTERNAL
        return Side.BRAND if self.value.startswith("BRAND_") else Side.SUPPLIER


class Side(StrEnum):
    """Which of the three portals a user belongs to."""

    INTERNAL = "INTERNAL"
    BRAND = "BRAND"
    SUPPLIER = "SUPPLIER"


class UserStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class DataSource(StrEnum):
    """Provenance of a capability/capacity claim.

    The agent (§10) must be able to discount what a factory told us about itself against what
    we have actually observed. Impossible to retrofit once the rows exist, so it is on every
    self-reported table from day one:

      SELF_REPORTED    the supplier typed it into onboarding
      INTERNAL_VERIFIED  a merchandiser or auditor confirmed it (physical visit, document)
      OBSERVED         derived from real transactions (Phase 5 rollups)
    """

    SELF_REPORTED = "SELF_REPORTED"
    INTERNAL_VERIFIED = "INTERNAL_VERIFIED"
    OBSERVED = "OBSERVED"


class ReferenceDomain(StrEnum):
    """The taxonomy namespaces held in `reference_item` (§3)."""

    PROCESS_TYPE = "PROCESS_TYPE"
    PRODUCT_CATEGORY = "PRODUCT_CATEGORY"   # hierarchical, uses parent_id
    FIBRE = "FIBRE"
    FABRIC_CONSTRUCTION = "FABRIC_CONSTRUCTION"
    FINISH_TYPE = "FINISH_TYPE"
    CERTIFICATION = "CERTIFICATION"
    COMPLIANCE_AUDIT_TYPE = "COMPLIANCE_AUDIT_TYPE"
    MACHINERY_TYPE = "MACHINERY_TYPE"
    COUNTRY = "COUNTRY"
    PORT = "PORT"
    CURRENCY = "CURRENCY"
    INCOTERM = "INCOTERM"
    UOM = "UOM"


class VerificationStatus(StrEnum):
    """Per-document / per-certificate review state (§5.3)."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DocumentType(StrEnum):
    UNIT_PHOTO = "UNIT_PHOTO"
    GST_CERTIFICATE = "GST_CERTIFICATE"
    PAN_CARD = "PAN_CARD"
    IEC_CERTIFICATE = "IEC_CERTIFICATE"
    BANK_DETAILS = "BANK_DETAILS"
    CERTIFICATION = "CERTIFICATION"
    COMPLIANCE_AUDIT_REPORT = "COMPLIANCE_AUDIT_REPORT"
    FACTORY_PHOTO = "FACTORY_PHOTO"
    FACTORY_VIDEO = "FACTORY_VIDEO"
    VISIT_REPORT = "VISIT_REPORT"
    VENDOR_MANUAL = "VENDOR_MANUAL"
    QA_PROTOCOL = "QA_PROTOCOL"
    TECH_PACK = "TECH_PACK"
    REFERENCE_IMAGE = "REFERENCE_IMAGE"
    OTHER = "OTHER"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"


class NotificationStatus(StrEnum):
    """Outbox pattern (§7): rows are written in the request, dispatched by a worker."""

    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CapacityUom(StrEnum):
    PCS = "PCS"
    KG = "KG"
    METRES = "METRES"
    YARDS = "YARDS"
    DOZENS = "DOZENS"


class SubcontractingPolicy(StrEnum):
    NONE = "NONE"
    DISCLOSED_ONLY = "DISCLOSED_ONLY"
    ROUTINE = "ROUTINE"


class MarketSegment(StrEnum):
    MASS = "MASS"
    MID = "MID"
    PREMIUM = "PREMIUM"
    LUXURY = "LUXURY"


class ActivityAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"
    LOGIN = "LOGIN"
    INVITE_SENT = "INVITE_SENT"
    INVITE_ACCEPTED = "INVITE_ACCEPTED"
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    VERIFICATION_DECISION = "VERIFICATION_DECISION"
    BULK_IMPORT = "BULK_IMPORT"
