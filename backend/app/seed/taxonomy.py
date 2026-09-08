"""The taxonomy.

Wider than apparel on purpose. Ecolink brokers Australian cotton into Indian spinning mills and
routes Japanese cooling chemistry through a Tiruppur dye house — a process list that starts at
knitting would have nowhere to put either.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ReferenceDomain as D
from app.models import ReferenceItem

# (code, name, [aliases])
PROCESS = [
    ("COTTON_GROWING", "Cotton growing", ["cotton farming", "cotton grower", "farm", "grower"]),
    ("GINNING", "Ginning", ["ginner", "ginning mill", "gin"]),
    ("BALING", "Baling", ["bale", "baling press"]),
    ("SPINNING", "Spinning", ["spinning mill", "yarn manufacturing", "spinner"]),
    ("YARN_DYEING", "Yarn dyeing", ["package dyeing", "hank dyeing"]),
    ("KNITTING", "Knitting", ["circular knitting", "sinker", "flat knitting", "knitter"]),
    ("WEAVING", "Weaving", ["loom", "powerloom", "weaver"]),
    ("FABRIC_DYEING", "Fabric dyeing", ["dyeing", "dye house", "process house", "dyer"]),
    ("FINISHING", "Finishing", ["compacting", "stentering", "calendering", "finisher"]),
    ("PRINTING", "Printing", ["rotary printing", "screen printing", "digital printing"]),
    ("GARMENTING", "Garmenting", ["stitching", "sewing", "cmt", "cut make trim", "garment unit"]),
    ("WASHING", "Washing", ["garment washing", "laundry"]),
    ("EMBROIDERY", "Embroidery", ["embroidery unit"]),
    # The Japan deal: a company that supplies chemistry or a licensed treatment, not fabric.
    ("CHEMICAL_SUPPLY", "Chemical / treatment supply", [
        "chemical supplier", "auxiliaries", "finishing chemical", "cooling tech", "treatment",
    ]),
    ("TRADING", "Trading / sourcing", ["trader", "agent", "merchant", "sourcing agent"]),
    ("TESTING", "Testing lab", ["lab", "testing", "quality lab"]),
    ("LOGISTICS", "Logistics", ["freight", "forwarder", "shipping line", "cha"]),
]

PRODUCT = [
    ("RAW_COTTON", "Raw cotton", None, ["cotton", "lint", "cotton bales", "australian cotton"]),
    ("YARN", "Yarn", None, ["cotton yarn", "combed yarn", "carded yarn"]),
    ("GREIGE_FABRIC", "Greige fabric", None, ["greige", "grey fabric", "raw fabric"]),
    ("FINISHED_FABRIC", "Finished fabric", None, ["dyed fabric", "processed fabric"]),
    ("CHEMICALS", "Chemicals & treatments", None, ["auxiliaries", "finishing agents"]),
    ("APPAREL", "Apparel", None, ["garments", "clothing"]),
    ("TSHIRT", "T-shirts", "APPAREL", ["tee", "t shirt", "round neck"]),
    ("POLO", "Polo shirts", "APPAREL", ["polo", "collar t shirt"]),
    ("INNERWEAR", "Innerwear", "APPAREL", ["underwear", "vests", "briefs", "inner wear"]),
    ("SWEATSHIRT", "Sweatshirts & hoodies", "APPAREL", ["hoodie", "fleece top", "sweat shirt"]),
    ("KIDSWEAR", "Kidswear", "APPAREL", ["kids", "children wear", "infant wear"]),
    ("HOME_TEXTILES", "Home textiles", None, ["bed linen", "towels", "home tex"]),
]

CERTIFICATION = [
    ("GOTS", "GOTS", ["global organic textile standard"]),
    ("OCS", "OCS", ["organic content standard"]),
    ("GRS", "GRS", ["global recycled standard"]),
    ("OEKO_TEX", "OEKO-TEX Standard 100", ["oeko tex", "oekotex", "standard 100"]),
    ("BCI", "BCI", ["better cotton initiative", "better cotton"]),
    ("ISO_9001", "ISO 9001", ["iso9001"]),
    ("ISO_14001", "ISO 14001", ["iso14001"]),
    ("SEDEX", "SEDEX / SMETA", ["sedex", "smeta"]),
    ("BSCI", "amfori BSCI", ["bsci"]),
    ("WRAP", "WRAP", ["wrap certification"]),
    ("ZDHC", "ZDHC", ["zero discharge"]),
    ("MYBMP", "myBMP", ["best management practice", "australian cotton bmp"]),
]

COUNTRY = [
    ("IN", "India", ["bharat"]), ("AU", "Australia", ["aus"]), ("JP", "Japan", []),
    ("BD", "Bangladesh", []), ("VN", "Vietnam", []), ("CN", "China", []),
    ("US", "United States", ["usa"]), ("GB", "United Kingdom", ["uk", "britain"]),
    ("DE", "Germany", []), ("FR", "France", []), ("IT", "Italy", []), ("NL", "Netherlands", []),
    ("AE", "United Arab Emirates", ["uae", "dubai"]), ("SG", "Singapore", []),
]

CURRENCY = [
    ("INR", "Indian Rupee", ["rs", "rupees"]), ("USD", "US Dollar", ["dollar", "$"]),
    ("AUD", "Australian Dollar", ["aud"]), ("JPY", "Japanese Yen", ["yen"]),
    ("EUR", "Euro", []), ("GBP", "Pound Sterling", ["pound"]),
]

UOM = [
    ("KG", "Kilograms", ["kg", "kgs", "kilo"]), ("MT", "Metric tonnes", ["ton", "tonne", "mt"]),
    ("BALE", "Bales", ["bales"]), ("PCS", "Pieces", ["pcs", "nos", "units"]),
    ("MTR", "Metres", ["m", "mtr", "meters"]), ("LTR", "Litres", ["l", "ltr", "liters"]),
]

INCOTERM = [
    ("FOB", "Free On Board", ["fob"]), ("CIF", "Cost, Insurance and Freight", ["cif"]),
    ("CFR", "Cost and Freight", ["c&f", "cfr"]), ("EXW", "Ex Works", ["ex works"]),
    ("DDP", "Delivered Duty Paid", ["ddp"]), ("DAP", "Delivered At Place", ["dap"]),
]

_FLAT = [
    (D.PROCESS, PROCESS), (D.CERTIFICATION, CERTIFICATION), (D.COUNTRY, COUNTRY),
    (D.CURRENCY, CURRENCY), (D.UOM, UOM), (D.INCOTERM, INCOTERM),
]


def _upsert(db: Session, domain: D, code: str, name: str, aliases: list[str],
            parent: ReferenceItem | None = None, order: int = 0) -> ReferenceItem:
    item = db.scalars(
        select(ReferenceItem).where(ReferenceItem.domain == domain, ReferenceItem.code == code)
    ).first()
    if item is None:
        item = ReferenceItem(domain=domain, code=code)
        db.add(item)
    item.name = name
    item.aliases = sorted(set(aliases))
    item.parent_id = parent.id if parent else None
    item.sort_order = order
    db.flush()
    return item


def seed_taxonomy(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for domain, rows in _FLAT:
        for order, (code, name, aliases) in enumerate(rows):
            _upsert(db, domain, code, name, aliases, order=order)
        counts[domain.value] = len(rows)

    created: dict[str, ReferenceItem] = {}
    for order, (code, name, parent_code, aliases) in enumerate(PRODUCT):
        parent = created.get(parent_code) if parent_code else None
        if parent_code and parent is None:
            raise ValueError(f"product {code} names parent {parent_code} before it is defined")
        created[code] = _upsert(db, D.PRODUCT, code, name, aliases, parent=parent, order=order)
    counts[D.PRODUCT.value] = len(PRODUCT)

    db.commit()
    return counts


def resolve(db: Session, domain: D, text: str) -> ReferenceItem | None:
    """Find a taxonomy value by code, name or alias. No fuzzy matching — a near miss that
    silently resolves to the wrong process is worse than a miss a human looks at."""
    if not text or not text.strip():
        return None
    needle = text.strip().lower()

    for item in db.scalars(select(ReferenceItem).where(ReferenceItem.domain == domain)).all():
        if item.code.lower() == needle or item.name.lower() == needle:
            return item
        if any(a.lower() == needle for a in (item.aliases or [])):
            return item
    return None
