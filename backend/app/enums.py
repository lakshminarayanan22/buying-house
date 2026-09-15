"""Controlled vocabularies that business logic branches on.

Anything an admin should be able to extend without a deploy — processes, product categories,
certifications, countries — lives in `reference_item` instead.
"""
from enum import StrEnum


class UserRole(StrEnum):
    """Only Ecolink staff use this system, so the role model is deliberately two lines."""

    ADMIN = "ADMIN"      # everything, including master data and user management
    MEMBER = "MEMBER"    # everything except user management and master data


class UserStatus(StrEnum):
    """Where a person is in getting access.

    Signing in with Google creates the account; it does not grant access. An admin does that,
    once, and from then on the person goes straight in. The four states and the moves between
    them are enforced in one place — app/services/access.py — rather than wherever a status
    happens to be written.
    """

    PENDING = "PENDING"      # signed in with Google, waiting for an admin
    ACTIVE = "ACTIVE"        # can use the application
    REJECTED = "REJECTED"    # an admin declined the request
    DISABLED = "DISABLED"    # had access, and it was switched off (left the company, etc.)


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
    MACHINERY = "MACHINERY"              # machine list / equipment spec sheet
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
    # Access lifecycle. Kept distinct from STATUS_CHANGE so "who let this person in, and when"
    # is one indexed query rather than a search through JSON diffs.
    ACCESS_REQUESTED = "ACCESS_REQUESTED"
    ACCESS_APPROVED = "ACCESS_APPROVED"
    ACCESS_REJECTED = "ACCESS_REJECTED"
    ACCESS_DISABLED = "ACCESS_DISABLED"
    ACCESS_RESTORED = "ACCESS_RESTORED"
    ROLE_CHANGE = "ROLE_CHANGE"
    PASSWORD_SET = "PASSWORD_SET"


class ExtractionStatus(StrEnum):
    """How far a document got through the retrieval pipeline."""

    PENDING = "PENDING"        # uploaded, not yet processed
    OK = "OK"                  # text extracted and chunks written
    NEEDS_OCR = "NEEDS_OCR"    # a scan — almost no text layer to extract
    FAILED = "FAILED"          # extraction raised; see extraction_error
    SKIPPED = "SKIPPED"        # not a text-bearing type (an image, a spreadsheet)
