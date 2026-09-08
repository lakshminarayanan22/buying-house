"""Controlled vocabularies that business logic branches on.

Anything an admin should be able to extend without a deploy — processes, product categories,
certifications, countries — lives in `reference_item` instead.
"""
from enum import StrEnum


class UserRole(StrEnum):
    """Only Ecolink staff use this system, so the role model is deliberately two lines."""

    ADMIN = "ADMIN"      # everything, including master data and user management
    MEMBER = "MEMBER"    # everything except user management and master data


class CompanyStatus(StrEnum):
    LEAD = "LEAD"            # we know of them, nothing agreed
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLACKLISTED = "BLACKLISTED"


class DealRole(StrEnum):
    """What a company does *in one particular deal*.

    A company is not a brand or a supplier — it depends on the deal. An Indian spinning mill is
    the BUYER when we sell it Australian cotton and the SUPPLIER when it sells yarn onward.
    Typing the company itself would make that impossible to express.
    """

    BUYER = "BUYER"                    # pays for the output
    SUPPLIER = "SUPPLIER"              # supplies the goods
    PROCESSOR = "PROCESSOR"            # converts them — dyeing, finishing, garmenting
    INPUT_SUPPLIER = "INPUT_SUPPLIER"  # supplies an input into someone else's process
    OTHER = "OTHER"                    # logistics, testing, an agent


class DealStatus(StrEnum):
    LEAD = "LEAD"
    NEGOTIATING = "NEGOTIATING"
    AGREED = "AGREED"
    IN_PROGRESS = "IN_PROGRESS"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    LOST = "LOST"

    @property
    def is_open(self) -> bool:
        return self in {
            DealStatus.LEAD, DealStatus.NEGOTIATING, DealStatus.AGREED,
            DealStatus.IN_PROGRESS, DealStatus.SHIPPED,
        }


class CommissionBasis(StrEnum):
    """How we get paid on one party's leg of a deal.

    PERCENTAGE  a cut of what that party pays or receives — the Australian cotton trade
    MARGIN      we sell above what we pay and keep the difference — the finished-fabric sale
    FIXED       a flat fee
    NONE        a party we coordinate but do not earn from
    """

    PERCENTAGE = "PERCENTAGE"
    MARGIN = "MARGIN"
    FIXED = "FIXED"
    NONE = "NONE"


class CommissionStatus(StrEnum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    INVOICED = "INVOICED"
    RECEIVED = "RECEIVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MilestoneStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class ReferenceDomain(StrEnum):
    """Taxonomy namespaces. Broader than apparel, because the business is."""

    PROCESS = "PROCESS"                  # growing, ginning, spinning, dyeing, garmenting…
    PRODUCT = "PRODUCT"                  # raw cotton, yarn, fabric, t-shirts, chemicals
    CERTIFICATION = "CERTIFICATION"
    COUNTRY = "COUNTRY"
    CURRENCY = "CURRENCY"
    UOM = "UOM"
    INCOTERM = "INCOTERM"


class DocumentKind(StrEnum):
    """Deliberately coarse. A folder per deal is what was asked for, not a filing taxonomy."""

    BROCHURE = "BROCHURE"                # the factory profile PDF
    PURCHASE_ORDER = "PURCHASE_ORDER"
    INVOICE = "INVOICE"
    PACKING_LIST = "PACKING_LIST"
    CERTIFICATE = "CERTIFICATE"
    CONTRACT = "CONTRACT"
    TEST_REPORT = "TEST_REPORT"
    PHOTO = "PHOTO"
    OTHER = "OTHER"


class ActivityAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"
    UPLOAD = "UPLOAD"
    LOGIN = "LOGIN"
    NOTE = "NOTE"
