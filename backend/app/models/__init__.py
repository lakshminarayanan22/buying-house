"""Model package. Importing it registers every mapper, which Alembic autogenerate relies on."""
from app.models.activity import ActivityLog, Note, Task
from app.models.base import Base
from app.models.brand import (
    BrandCategory,
    BrandExcludedCountry,
    BrandProfile,
    BrandRequiredCertification,
    BrandTargetMarket,
)
from app.models.document import Document
from app.models.notification import (
    NotificationOutbox,
    NotificationPreference,
    NotificationTemplate,
)
from app.models.organization import Contact, ImportBatch, Organization, OrgInvite
from app.models.reference import ReferenceAlias, ReferenceItem, UnmappedTerm, normalise_term
from app.models.supplier import (
    SupplierCapability,
    SupplierCapabilityConstruction,
    SupplierCapabilityFibre,
    SupplierCapacityCalendar,
    SupplierCertification,
    SupplierCompliance,
    SupplierExportMarket,
    SupplierMachine,
    SupplierPerformance,
    SupplierProcess,
    SupplierProfile,
    SupplierReference,
)
from app.models.user import BrandSupplierReveal, OtpChallenge, User

__all__ = [
    "ActivityLog",
    "Base",
    "BrandCategory",
    "BrandExcludedCountry",
    "BrandProfile",
    "BrandRequiredCertification",
    "BrandSupplierReveal",
    "BrandTargetMarket",
    "Contact",
    "Document",
    "ImportBatch",
    "Note",
    "NotificationOutbox",
    "NotificationPreference",
    "NotificationTemplate",
    "Organization",
    "OrgInvite",
    "OtpChallenge",
    "ReferenceAlias",
    "ReferenceItem",
    "SupplierCapability",
    "SupplierCapabilityConstruction",
    "SupplierCapabilityFibre",
    "SupplierCapacityCalendar",
    "SupplierCertification",
    "SupplierCompliance",
    "SupplierExportMarket",
    "SupplierMachine",
    "SupplierPerformance",
    "SupplierProcess",
    "SupplierProfile",
    "SupplierReference",
    "Task",
    "UnmappedTerm",
    "User",
    "normalise_term",
]
