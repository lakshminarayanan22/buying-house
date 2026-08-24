"""The §3 taxonomy, with the synonyms suppliers actually type.

Aliases are not decoration. "Sinker", "S/J" and "Single Jersey" are the same construction, and
whether the bulk importer knows that decides whether 200 rows land in the directory or in a
review queue. Seeding is idempotent — safe to re-run after adding values.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ReferenceDomain as D
from app.models import ReferenceItem
from app.services.taxonomy import add_alias, refresh_path

# (code, name, [aliases])
PROCESS_TYPES = [
    ("SPINNING", "Spinning", ["yarn manufacturing", "spinning mill"]),
    ("KNITTING_CIRCULAR", "Knitting - circular", ["circular knitting", "ckm", "tubular knitting"]),
    ("KNITTING_FLAT", "Knitting - flat", ["flat knitting", "collar knitting", "flat bed"]),
    ("KNITTING_WARP", "Knitting - warp", ["warp knitting", "tricot"]),
    ("WEAVING", "Weaving", ["loom", "weaving unit", "powerloom"]),
    ("YARN_DYEING", "Dyeing - yarn", ["yarn dyeing", "package dyeing", "hank dyeing"]),
    ("FABRIC_DYEING", "Dyeing - fabric", ["fabric dyeing", "dye house", "process house", "dyeing"]),
    ("GARMENT_DYEING", "Dyeing - garment", ["garment dyeing", "gmt dyeing"]),
    ("PRINTING_ROTARY", "Printing - rotary", ["rotary printing"]),
    ("PRINTING_SCREEN", "Printing - screen", ["screen printing", "table printing", "flat bed printing"]),
    ("PRINTING_DIGITAL", "Printing - digital", ["digital printing", "dtg", "direct to garment"]),
    ("PRINTING_SUBLIMATION", "Printing - sublimation", ["sublimation", "sublimation printing"]),
    ("FINISHING", "Finishing", ["compacting", "calendering", "stentering", "finishing unit"]),
    ("EMBROIDERY", "Embroidery", ["embroidery unit", "schiffli", "computer embroidery"]),
    ("CUTTING", "Cutting", ["cutting section", "cad cutting"]),
    ("STITCHING", "Stitching", ["sewing", "garmenting", "cmt", "cut make trim", "stitching unit"]),
    ("WASHING", "Washing", ["garment washing", "laundry", "wash house"]),
    ("TRIMS_ACCESSORIES", "Trims & accessories", ["trims", "accessories", "labels", "buttons"]),
    ("PACKAGING", "Packaging", ["packing", "poly bags", "cartons"]),
    ("TESTING_LAB", "Testing lab", ["lab", "testing", "quality lab"]),
]

# (code, name, parent_code, [aliases])
PRODUCT_CATEGORIES = [
    ("APPAREL", "Apparel", None, ["garments", "clothing"]),
    ("KNITWEAR", "Knitwear", "APPAREL", ["knits", "knitted garments"]),
    ("TSHIRT", "T-shirts", "KNITWEAR", ["tee", "t shirt", "tees", "round neck"]),
    ("POLO", "Polo shirts", "KNITWEAR", ["polo", "polo tee", "collar t shirt"]),
    ("SWEATSHIRT", "Sweatshirts & hoodies", "KNITWEAR", ["hoodie", "hoody", "sweat shirt", "fleece top"]),
    ("LEGGINGS", "Leggings & bottoms", "KNITWEAR", ["leggings", "joggers", "track pants"]),
    ("INNERWEAR", "Innerwear", "KNITWEAR", ["underwear", "vests", "briefs", "inner wear"]),
    ("KIDSWEAR_KNIT", "Kidswear - knitted", "KNITWEAR", ["kids knits", "children knitwear", "infant wear"]),
    ("WOVEN", "Wovenwear", "APPAREL", ["wovens", "woven garments"]),
    ("SHIRT", "Shirts", "WOVEN", ["formal shirt", "casual shirt"]),
    ("TROUSER", "Trousers", "WOVEN", ["pants", "chinos", "formal trouser"]),
    ("DENIM", "Denim", "WOVEN", ["jeans", "denim wear"]),
    ("DRESS", "Dresses", "WOVEN", ["frock", "gown", "one piece"]),
    ("OUTERWEAR", "Outerwear", "APPAREL", ["jacket", "jackets", "coats"]),
    ("HOME_TEXTILES", "Home textiles", None, ["home tex", "hometextiles"]),
    ("BED_LINEN", "Bed linen", "HOME_TEXTILES", ["bedsheet", "bed sheets", "duvet", "bedding"]),
    ("TOWELS", "Towels", "HOME_TEXTILES", ["terry towel", "bath towel"]),
    ("KITCHEN_LINEN", "Kitchen linen", "HOME_TEXTILES", ["kitchen towel", "apron", "napkins"]),
    ("TECHNICAL", "Technical textiles", None, ["industrial textiles", "techtex"]),
]

FIBRES = [
    ("COTTON", "Cotton", ["cotton", "ctn", "100% cotton"]),
    ("ORGANIC_COTTON", "Organic cotton", ["organic cotton", "gots cotton", "bio cotton"]),
    ("RECYCLED_COTTON", "Recycled cotton", ["recycled cotton", "rcot"]),
    ("BCI_COTTON", "BCI cotton", ["bci", "better cotton"]),
    ("POLYESTER", "Polyester", ["poly", "pes", "pet"]),
    ("RPET", "Recycled polyester", ["rpet", "recycled poly", "recycled polyester"]),
    ("VISCOSE", "Viscose", ["rayon", "viscose rayon"]),
    ("MODAL", "Modal", ["modal"]),
    ("LYOCELL", "Lyocell", ["tencel", "lyocell"]),
    ("LINEN", "Linen", ["flax", "linen"]),
    ("WOOL", "Wool", ["wool", "merino"]),
    ("NYLON", "Nylon", ["polyamide", "nylon"]),
    ("ELASTANE", "Elastane", ["spandex", "lycra", "elastane"]),
    ("BAMBOO", "Bamboo", ["bamboo viscose", "bamboo"]),
    ("HEMP", "Hemp", ["hemp"]),
]

FABRIC_CONSTRUCTIONS = [
    ("SINGLE_JERSEY", "Single Jersey", ["s/j", "sj", "sinker", "single jersey", "plain knit"]),
    ("RIB_1X1", "Rib 1x1", ["1x1 rib", "rib", "1*1 rib"]),
    ("RIB_2X2", "Rib 2x2", ["2x2 rib", "2*2 rib"]),
    ("INTERLOCK", "Interlock", ["interlock", "double jersey"]),
    ("PIQUE", "Pique", ["pique", "polo pique", "honeycomb"]),
    ("FRENCH_TERRY", "French Terry", ["french terry", "ft", "loop knit"]),
    ("FLEECE", "Fleece", ["fleece", "brushed fleece", "polar fleece"]),
    ("WAFFLE", "Waffle", ["waffle", "thermal knit"]),
    ("LYCRA_JERSEY", "Lycra Jersey", ["lycra jersey", "stretch jersey", "sj lycra"]),
    ("SLUB_JERSEY", "Slub Jersey", ["slub", "slub jersey"]),
    ("PLAIN_WEAVE", "Plain weave", ["poplin", "plain weave", "voile"]),
    ("TWILL", "Twill", ["twill", "drill", "chino weave"]),
    ("SATIN", "Satin", ["sateen", "satin"]),
    ("OXFORD", "Oxford", ["oxford", "ox weave"]),
    ("DOBBY", "Dobby", ["dobby"]),
    ("TERRY_WOVEN", "Terry (woven)", ["terry", "towel terry"]),
]

FINISH_TYPES = [
    ("BIO_WASH", "Bio wash", ["biowash", "bio wash", "enzyme wash"]),
    ("PEACH_FINISH", "Peach finish", ["peaching", "peach"]),
    ("SILICONE", "Silicone finish", ["silicone", "soft finish"]),
    ("MERCERISED", "Mercerised", ["mercerized", "mercerising"]),
    ("ANTI_MICROBIAL", "Anti-microbial", ["antimicrobial", "anti bacterial"]),
    ("MOISTURE_WICKING", "Moisture wicking", ["dry fit", "wicking", "quick dry"]),
    ("WATER_REPELLENT", "Water repellent", ["wr finish", "water repellant"]),
    ("BRUSHED", "Brushed", ["brushing", "raising"]),
    ("COMPACTED", "Compacted", ["compacting", "compact finish"]),
]

CERTIFICATIONS = [
    ("GOTS", "GOTS", ["global organic textile standard", "gots"]),
    ("OCS", "OCS", ["organic content standard", "ocs 100", "ocs blended"]),
    ("GRS", "GRS", ["global recycled standard", "grs"]),
    ("RCS", "RCS", ["recycled claim standard", "rcs"]),
    ("OEKO_TEX_100", "OEKO-TEX Standard 100", ["oeko tex", "oekotex", "standard 100"]),
    ("BCI", "BCI", ["better cotton initiative", "bci"]),
    ("ZDHC", "ZDHC", ["zdhc", "zero discharge"]),
    ("ISO_9001", "ISO 9001", ["iso9001", "iso 9001:2015"]),
    ("ISO_14001", "ISO 14001", ["iso14001"]),
    ("SEDEX_SMETA", "SEDEX / SMETA", ["sedex", "smeta", "sedex smeta"]),
    ("BSCI", "BSCI", ["amfori bsci", "bsci"]),
    ("WRAP", "WRAP", ["wrap certification", "wrap"]),
    ("SA8000", "SA8000", ["sa 8000", "sa8000"]),
    ("HIGG_FEM", "Higg FEM", ["higg fem", "higg index fem"]),
    ("HIGG_FSLM", "Higg FSLM", ["higg fslm"]),
    ("FAIRTRADE", "Fairtrade", ["fair trade", "fairtrade"]),
]

COMPLIANCE_AUDIT_TYPES = [
    ("SMETA_2P", "SMETA 2-Pillar", ["smeta 2p"]),
    ("SMETA_4P", "SMETA 4-Pillar", ["smeta 4p"]),
    ("BSCI_AUDIT", "amfori BSCI audit", ["bsci audit"]),
    ("WRAP_AUDIT", "WRAP audit", ["wrap audit"]),
    ("SA8000_AUDIT", "SA8000 audit", ["sa8000 audit"]),
    ("HIGG_FEM_VERIFIED", "Higg FEM verified", ["higg fem verification"]),
    ("BUYER_SOCIAL_AUDIT", "Buyer social audit", ["customer audit", "buyer audit"]),
    ("TECHNICAL_AUDIT", "Technical / capability audit", ["technical audit", "capability audit"]),
]

MACHINERY_TYPES = [
    ("CIRCULAR_KNIT_SJ", "Circular knitting - single jersey", ["sinker machine", "sj machine"]),
    ("CIRCULAR_KNIT_RIB", "Circular knitting - rib/interlock", ["rib machine", "interlock machine"]),
    ("FLAT_KNIT", "Flat knitting machine", ["collar machine", "flat bed machine"]),
    ("WARP_KNIT", "Warp knitting machine", ["tricot machine"]),
    ("LOOM_AIRJET", "Loom - air jet", ["air jet loom", "airjet"]),
    ("LOOM_RAPIER", "Loom - rapier", ["rapier loom"]),
    ("SOFT_FLOW_DYEING", "Soft flow dyeing machine", ["soft flow", "softflow"]),
    ("JET_DYEING", "Jet dyeing machine", ["jet dyeing"]),
    ("PACKAGE_DYEING", "Package dyeing machine", ["package dyeing"]),
    ("STENTER", "Stenter", ["stenter machine", "stentering"]),
    ("COMPACTOR", "Compactor", ["compacting machine"]),
    ("ROTARY_PRINT", "Rotary printing machine", ["rotary printer"]),
    ("DIGITAL_PRINTER", "Digital printing machine", ["digital printer", "dtg machine"]),
    ("SNLS", "Single needle lock stitch", ["snls", "single needle"]),
    ("OVERLOCK", "Overlock machine", ["overlock", "4 thread", "5 thread"]),
    ("FLATLOCK", "Flatlock machine", ["flatlock", "flat lock"]),
    ("FEED_OF_ARM", "Feed of the arm", ["feed of arm", "foa"]),
    ("BARTACK", "Bartack machine", ["bartack", "bar tack"]),
    ("BUTTONHOLE", "Buttonhole machine", ["button hole", "buttonhole"]),
    ("EMBROIDERY_MACHINE", "Embroidery machine", ["embroidery m/c", "tajima", "barudan"]),
    ("CUTTING_AUTO", "Automatic cutting machine", ["auto cutter", "cam cutter"]),
    ("WASHING_MACHINE", "Industrial washing machine", ["washing m/c", "washer"]),
]

COUNTRIES = [
    ("IN", "India", ["bharat"]),
    ("BD", "Bangladesh", []),
    ("LK", "Sri Lanka", []),
    ("VN", "Vietnam", []),
    ("CN", "China", []),
    ("PK", "Pakistan", []),
    ("TR", "Turkey", ["turkiye"]),
    ("US", "United States", ["usa", "united states of america"]),
    ("GB", "United Kingdom", ["uk", "britain", "england"]),
    ("DE", "Germany", ["deutschland"]),
    ("FR", "France", []),
    ("NL", "Netherlands", ["holland"]),
    ("ES", "Spain", []),
    ("IT", "Italy", []),
    ("SE", "Sweden", []),
    ("DK", "Denmark", []),
    ("AU", "Australia", []),
    ("CA", "Canada", []),
    ("AE", "United Arab Emirates", ["uae", "dubai"]),
    ("JP", "Japan", []),
]

PORTS = [
    ("INMAA", "Chennai", ["madras", "chennai port"]),
    ("INTUT", "Thoothukudi", ["tuticorin"]),
    ("INCOK", "Kochi", ["cochin"]),
    ("INNSA", "Nhava Sheva", ["jnpt", "mumbai port"]),
    ("INMUN", "Mundra", []),
    ("INBLR", "Bengaluru (ICD)", ["bangalore icd"]),
    ("INTIR", "Tiruppur (ICD)", ["tirupur icd", "tiruppur icd"]),
]

CURRENCIES = [
    ("INR", "Indian Rupee", ["rs", "rupees", "inr"]),
    ("USD", "US Dollar", ["usd", "dollar", "$"]),
    ("EUR", "Euro", ["eur", "euro"]),
    ("GBP", "Pound Sterling", ["gbp", "pound"]),
    ("AED", "UAE Dirham", ["aed", "dirham"]),
]

INCOTERMS = [
    ("EXW", "Ex Works", ["ex works", "ex-works", "exw"]),
    ("FOB", "Free On Board", ["fob", "free on board"]),
    ("CIF", "Cost, Insurance and Freight", ["cif"]),
    ("CFR", "Cost and Freight", ["cfr", "c&f"]),
    ("DDP", "Delivered Duty Paid", ["ddp"]),
    ("DAP", "Delivered At Place", ["dap"]),
    ("FCA", "Free Carrier", ["fca"]),
]

UOMS = [
    ("PCS", "Pieces", ["pcs", "pieces", "nos", "units"]),
    ("KG", "Kilograms", ["kg", "kgs", "kilo"]),
    ("MTR", "Metres", ["m", "mtr", "metres", "meters"]),
    ("YRD", "Yards", ["yd", "yds", "yards"]),
    ("DOZ", "Dozens", ["dz", "doz", "dozens"]),
    ("SET", "Sets", ["set", "sets"]),
]

_FLAT_DOMAINS = [
    (D.PROCESS_TYPE, PROCESS_TYPES),
    (D.FIBRE, FIBRES),
    (D.FABRIC_CONSTRUCTION, FABRIC_CONSTRUCTIONS),
    (D.FINISH_TYPE, FINISH_TYPES),
    (D.CERTIFICATION, CERTIFICATIONS),
    (D.COMPLIANCE_AUDIT_TYPE, COMPLIANCE_AUDIT_TYPES),
    (D.MACHINERY_TYPE, MACHINERY_TYPES),
    (D.COUNTRY, COUNTRIES),
    (D.PORT, PORTS),
    (D.CURRENCY, CURRENCIES),
    (D.INCOTERM, INCOTERMS),
    (D.UOM, UOMS),
]


def _upsert(db: Session, domain: D, code: str, name: str, parent: ReferenceItem | None = None,
            sort_order: int = 0) -> ReferenceItem:
    item = db.scalars(
        select(ReferenceItem).where(ReferenceItem.domain == domain, ReferenceItem.code == code)
    ).first()
    if item is None:
        item = ReferenceItem(domain=domain, code=code, name=name, sort_order=sort_order)
        db.add(item)
    else:
        item.name = name
        item.sort_order = sort_order
    item.parent_id = parent.id if parent else None
    db.flush()
    return item


def seed_master_data(db: Session) -> dict[str, int]:
    """Load the §3 taxonomy. Idempotent: re-running updates names and adds new values."""
    counts: dict[str, int] = {}

    for domain, rows in _FLAT_DOMAINS:
        for order, (code, name, aliases) in enumerate(rows):
            item = _upsert(db, domain, code, name, sort_order=order)
            item.path = code
            item.depth = 0
            for alias in aliases:
                add_alias(db, item, alias)
        counts[domain.value] = len(rows)

    # Categories are hierarchical, so parents must exist before children. The source list is
    # already ordered parent-first; this asserts it rather than assuming it.
    created: dict[str, ReferenceItem] = {}
    for order, (code, name, parent_code, aliases) in enumerate(PRODUCT_CATEGORIES):
        parent = None
        if parent_code is not None:
            parent = created.get(parent_code)
            if parent is None:
                raise ValueError(
                    f"product category {code} lists parent {parent_code} before it is defined"
                )
        item = _upsert(db, D.PRODUCT_CATEGORY, code, name, parent=parent, sort_order=order)
        created[code] = item
        for alias in aliases:
            add_alias(db, item, alias)

    for item in created.values():
        refresh_path(db, item)
    counts[D.PRODUCT_CATEGORY.value] = len(PRODUCT_CATEGORIES)

    db.commit()
    return counts
