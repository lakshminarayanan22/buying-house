"""Thirteen tables. Importing this registers every mapper, which Alembic relies on."""
from app.models.base import Base
from app.models.company import (
    Company,
    CompanyCertification,
    CompanyClient,
    CompanyProcess,
    CompanyProduct,
    Contact,
)
from app.models.core import ActivityLog, Document, User
from app.models.deal import Deal, DealMilestone, DealParty
from app.models.reference import ReferenceItem

__all__ = [
    "ActivityLog",
    "Base",
    "Company",
    "CompanyCertification",
    "CompanyClient",
    "CompanyProcess",
    "CompanyProduct",
    "Contact",
    "Deal",
    "DealMilestone",
    "DealParty",
    "Document",
    "ReferenceItem",
    "User",
]
