"""Build `ecolink_eval`: a separate database of imagined companies and deals, for scoring and
training the SQL writer.

    .venv/bin/python -m scripts.seed_eval_db            # create it if it doesn't exist
    .venv/bin/python -m scripts.seed_eval_db --reset    # drop and rebuild from scratch

Why a separate database rather than the real one:

  - The real database holds five companies and two deals. With that few rows a wrong query often
    returns the right answer by luck — forget a filter, and there was only one row to return
    anyway. Thirty companies and fifty deals make a missing WHERE clause visible.
  - It is never shown in the app. The app reads DATABASE_URL (`ecolink`); this lives beside it
    under a different name, and the script refuses to touch `ecolink` whatever it is told.
  - Every date is fixed. The demo seed uses date.today(), which is why "which follow-ups are
    overdue?" in the old test set went stale a week after it was written. Here "today" is always
    15 September 2026, so a correct query returns the same rows next year.
  - It is deterministic. The same seed builds the same rows, so a gold query written today
    still returns the same answer after a rebuild.

Commission is calculated by the app's own `refresh_commission()`, and deal value counts BUYER
legs only — the same rules the app uses — so a query that is right here is right in production.
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.enums import (
    CommissionBasis as B,
    CommissionStatus as CS,
    CompanyStatus,
    DealRole as R,
    DealStatus as S,
    MilestoneStatus as M,
    ReferenceDomain as D,
    UserRole,
    UserStatus,
)
from app.models import (
    Company,
    CompanyCertification,
    CompanyClient,
    CompanyProcess,
    CompanyProduct,
    Contact,
    Deal,
    DealMilestone,
    DealParty,
    User,
)
from app.seed.taxonomy import resolve, seed_taxonomy
from app.services import deals as svc

EVAL_DB = "ecolink_eval"
PROTECTED = {"ecolink", "postgres", "template0", "template1"}
ANCHOR = date(2026, 9, 15)          # "today", as far as this database is concerned
SEED = 20260915
BACKEND = Path(__file__).resolve().parent.parent


# ================================================================== the companies
@dataclass
class Co:
    name: str
    city: str
    country: str
    buys: bool = False
    sells: bool = True
    status: str = CompanyStatus.ACTIVE
    year: int | None = None
    # (process, monthly_capacity, min_order_qty, uom, lead_time_days)
    processes: list[tuple] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    certs: list[tuple[str, str | None]] = field(default_factory=list)
    clients: list[tuple[str, bool]] = field(default_factory=list)
    # (name, designation, email, phone, is_primary)
    contacts: list[tuple] = field(default_factory=list)
    payment_terms: str | None = None
    moq_notes: str | None = None
    lead_time_notes: str | None = None
    quality: str | None = None
    notes: str | None = None


COMPANIES = [
    Co("Kavya Knitwear", "Tiruppur", "India", year=2004,
       processes=[("Knitting", 180000, 800, "KG", 25), ("Garmenting", 400000, 3000, "PCS", 45)],
       products=["T-shirts", "Polo shirts", "Kidswear"],
       certs=[("GOTS", "GOTS-TPR-11820"), ("OEKO-TEX Standard 100", "OTX-22-1043"),
              ("SEDEX / SMETA", None)],
       clients=[("Primark", True), ("H&M", False)],
       contacts=[("Deepa Raman", "Merchandising head", "deepa@kavyaknit.example",
                  "+91 94430 11001", True),
                 ("Karthik Selvan", "Production manager", None, "+91 94430 11002", False)],
       payment_terms="45 days from invoice", moq_notes="3,000 pieces per style",
       lead_time_notes="45 days from fabric approval"),
    Co("Sri Balaji Knits", "Tiruppur", "India", year=2011,
       processes=[("Knitting", 120000, 1000, "KG", 20)], products=["Greige fabric"],
       certs=[("OEKO-TEX Standard 100", "OTX-23-0877")],
       contacts=[("Balaji Murugan", "Proprietor", None, "+91 98422 30511", True)],
       payment_terms="30 days", moq_notes="1,000 kg per quality"),
    Co("Orient Fabric Processors", "Tiruppur", "India", year=1998,
       processes=[("Fabric dyeing", 300000, 500, "KG", 21), ("Finishing", 300000, 500, "KG", 7)],
       products=["Finished fabric"],
       certs=[("GOTS", "GOTS-TPR-09914"), ("ZDHC", None), ("OEKO-TEX Standard 100", "OTX-21-3310")],
       clients=[("Decathlon", True)],
       contacts=[("Lakshmi Venkat", "Technical director", "lakshmi.v@orientfab.example",
                  "+91 90030 44120", True)],
       payment_terms="30 days from dispatch", moq_notes="500 kg per shade",
       lead_time_notes="21 days for dyeing and finishing"),
    Co("Karur Home Textiles", "Karur", "India", year=1989,
       processes=[("Weaving", 250000, 5000, "MTR", 30), ("Garmenting", 150000, 2000, "PCS", 40)],
       products=["Home textiles"],
       certs=[("OEKO-TEX Standard 100", "OTX-20-5521"), ("amfori BSCI", None)],
       clients=[("IKEA", True)],
       contacts=[("Rajesh Kannan", "Export manager", "rajesh@karurhome.example",
                  "+91 94433 70808", True)],
       payment_terms="LC at sight", moq_notes="2,000 pieces per design"),
    Co("Salem Yarn Dyers", "Salem", "India", year=2008,
       processes=[("Yarn dyeing", 60000, 300, "KG", 14)], products=["Yarn"],
       certs=[("OEKO-TEX Standard 100", "OTX-22-7781"), ("ZDHC", None)],
       contacts=[("Suresh Palani", "Partner", None, "+91 97890 55410", True)],
       moq_notes="300 kg per colour"),
    Co("Ludhiana Spinners", "Ludhiana", "India", buys=True, year=1995,
       processes=[("Spinning", 1200000, 20000, "KG", 30)], products=["Yarn"],
       certs=[("ISO 9001", "ISO-9001-LS-2019"), ("BCI", None)],
       contacts=[("Harpreet Singh", "Purchase head", "harpreet@ludhianaspin.example",
                  "+91 98140 22300", True)],
       payment_terms="30 days from bill of lading", moq_notes="20 MT per count"),
    Co("Saurashtra Organic Ginners", "Rajkot", "India", year=2012,
       processes=[("Ginning", 2500, 50, "MT", 15), ("Baling", 2500, 50, "MT", 5)],
       products=["Raw cotton"], certs=[("OCS", "OCS-GJ-4471"), ("GOTS", "GOTS-GJ-2206")],
       contacts=[("Nilesh Patel", "Director", "nilesh@saurashtraorganic.example",
                  "+91 98250 61177", True)],
       payment_terms="Advance 30%, balance against documents"),
    Co("Kutch Cotton Farmers Collective", "Bhuj", "India", status=CompanyStatus.LEAD, year=2019,
       processes=[("Cotton growing", 800, 100, "MT", None)], products=["Raw cotton"],
       certs=[("OCS", None)],
       contacts=[("Dilip Jadeja", "Coordinator", None, "+91 99099 18820", True)],
       notes="Met at the 2026 Rajkot cotton meet; organic, rain-fed, first season with us."),
    Co("Surat Weaving Works", "Surat", "India", status=CompanyStatus.BLACKLISTED, year=2001,
       processes=[("Weaving", 400000, 10000, "MTR", 25)], products=["Greige fabric"],
       certs=[("ISO 9001", "ISO-9001-SW-2017")],
       contacts=[("Mehul Shah", "Owner", "mehul@suratweave.example", "+91 98980 40400", True)],
       notes="Blacklisted in March 2026 after two short-shipped orders."),
    Co("Ahmedabad Denim Mills", "Ahmedabad", "India", year=1986,
       processes=[("Weaving", 900000, 10000, "MTR", 35), ("Washing", 200000, 5000, "PCS", 10)],
       products=["Finished fabric"],
       certs=[("GRS", "GRS-AD-3309"), ("OEKO-TEX Standard 100", "OTX-19-6012"),
              ("ISO 14001", None)],
       clients=[("Levi's", True)],
       contacts=[("Anita Desai", "Head of sales", "anita@ahmdenim.example",
                  "+91 99250 33011", True)],
       payment_terms="60 days from dispatch", moq_notes="10,000 metres per shade"),
    Co("Panipat Recycled Fibres", "Panipat", "India", year=2015,
       processes=[("Spinning", 400000, 10000, "KG", 21)], products=["Yarn"],
       certs=[("GRS", "GRS-PP-1180")],
       contacts=[("Vikas Goel", "Managing director", "vikas@panipatrf.example",
                  "+91 98120 77001", True)]),
    Co("Coimbatore Compact Spinning", "Coimbatore", "India", buys=True, year=2002,
       processes=[("Spinning", 1500000, 20000, "KG", 25)], products=["Yarn"],
       certs=[("OEKO-TEX Standard 100", "OTX-21-0450"), ("ISO 9001", "ISO-9001-CC-2020")],
       clients=[("Arvind Ltd", True)],
       contacts=[("Ganesh Iyer", "VP marketing", "ganesh@ccspin.example", "+91 94421 50505", True),
                 ("Meenakshi R", "Accounts", "accounts@ccspin.example", None, False)],
       payment_terms="30 days from bill of lading", moq_notes="20 MT per count"),
    Co("Erode Print House", "Erode", "India", status=CompanyStatus.INACTIVE, year=2006,
       processes=[("Printing", 80000, 400, "KG", 18)], products=["Finished fabric"],
       certs=[("OEKO-TEX Standard 100", "OTX-20-8841")],
       contacts=[("Mani Selvam", "Owner", None, "+91 94432 60090", True)],
       notes="Paused operations after the flood in July 2026; not taking orders."),
    Co("Chennai Testing Labs", "Chennai", "India", year=2010,
       processes=[("Testing lab", None, None, None, 5)], certs=[("ISO 9001", None)],
       contacts=[("Revathi Krishnan", "Lab head", "revathi@chennailabs.example",
                  "+91 44 2811 0303", True)]),
    Co("Tuticorin Freight Services", "Thoothukudi", "India", year=2003,
       processes=[("Logistics", None, None, None, 3)],
       contacts=[("Joseph Fernando", "Operations", "joseph@tutfreight.example",
                  "+91 461 232 1144", True)]),
    Co("Nagoya Finishing Chemicals", "Nagoya", "Japan", year=1972,
       processes=[("Chemical / treatment supply", 20000, 200, "LTR", 21)],
       products=["Chemicals & treatments"], certs=[("ZDHC", None)],
       contacts=[("Kenji Watanabe", "Export sales", "watanabe@nagoyachem.example", None, True)],
       payment_terms="TT in advance"),
    Co("Rhine Textile Auxiliaries", "Leverkusen", "Germany", year=1961,
       processes=[("Chemical / treatment supply", 50000, 500, "LTR", 28)],
       products=["Chemicals & treatments"], certs=[("ZDHC", None), ("ISO 14001", None)],
       contacts=[("Julia Becker", "Key account manager", "j.becker@rhineaux.example",
                  "+49 214 300 8811", True)],
       payment_terms="30 days net"),
    Co("Dhaka Knit Composite", "Dhaka", "Bangladesh", year=2007,
       processes=[("Knitting", 250000, 1000, "KG", 20), ("Fabric dyeing", 250000, 800, "KG", 20),
                  ("Garmenting", 500000, 5000, "PCS", 50)],
       products=["T-shirts", "Sweatshirts & hoodies", "Kidswear"],
       certs=[("GOTS", "GOTS-BD-5520"), ("WRAP", None), ("amfori BSCI", None)],
       clients=[("Tesco", True)],
       contacts=[("Rafiq Hasan", "Director", "rafiq@dhakaknit.example", "+880 17 1100 2200", True)],
       payment_terms="LC 60 days", moq_notes="5,000 pieces per style"),
    Co("Chittagong Denim Ltd", "Chattogram", "Bangladesh", year=2013,
       processes=[("Weaving", 500000, 8000, "MTR", 30), ("Washing", 300000, 3000, "PCS", 10),
                  ("Garmenting", 300000, 3000, "PCS", 55)],
       products=["Apparel"], certs=[("GRS", "GRS-BD-0917"), ("WRAP", None)],
       contacts=[("Nusrat Jahan", "Merchandiser", "nusrat@ctgdenim.example", None, True)]),
    Co("Saigon Garment Co", "Ho Chi Minh City", "Vietnam", year=2009,
       processes=[("Garmenting", 350000, 2000, "PCS", 40)],
       products=["Polo shirts", "Innerwear"], certs=[("WRAP", None), ("amfori BSCI", None)],
       contacts=[("Nguyen Thi Lan", "Sales manager", "lan@saigongarment.example",
                  "+84 90 812 3344", True)],
       payment_terms="LC at sight"),
    Co("Texas Gin & Cotton", "Lubbock", "United States", year=1979,
       processes=[("Ginning", 3000, 100, "MT", 20)], products=["Raw cotton"],
       contacts=[("Bill Harlan", "Export desk", "bill@texasgin.example", "+1 806 555 0190", True)],
       payment_terms="CAD, documents through bank"),
    Co("Hanse Mode GmbH", "Hamburg", "Germany", buys=True, sells=False, year=1994,
       products=["T-shirts", "Sweatshirts & hoodies"],
       contacts=[("Katrin Vogel", "Sourcing lead", "k.vogel@hansemode.example", None, True)],
       payment_terms="60 days from delivery",
       quality="AQL 2.5; GOTS certification on every organic line."),
    Co("Amstel Basics BV", "Amsterdam", "Netherlands", buys=True, sells=False, year=2005,
       products=["T-shirts", "Innerwear"],
       contacts=[("Pieter de Vries", "Buyer", "pieter@amstelbasics.example", None, True)],
       payment_terms="45 days from delivery"),
    Co("Thames Retail Group", "London", "United Kingdom", buys=True, sells=False, year=1988,
       products=["T-shirts", "Polo shirts", "Home textiles"],
       contacts=[("Sophie Clarke", "Head of sourcing", "sophie.clarke@thamesretail.example",
                  "+44 20 7946 0331", True),
                 ("Tom Hughes", "Quality manager", None, "+44 20 7946 0332", False)],
       payment_terms="60 days, LC for first order",
       quality="AQL 2.5. OEKO-TEX on all fabric. Pre-shipment inspection by a third party."),
    Co("Sakura Lifestyle KK", "Tokyo", "Japan", buys=True, sells=False, year=1999,
       products=["Polo shirts", "Innerwear"],
       contacts=[("Yuki Sato", "Merchandise manager", "sato@sakuralife.example", None, True)],
       quality="Japanese colour-fastness standards; hand-feel approval on every lot."),
    Co("Lyon Maison SARL", "Lyon", "France", buys=True, sells=False, year=2011,
       products=["Home textiles"],
       contacts=[("Camille Laurent", "Head buyer", "camille@lyonmaison.example", None, True)]),
    Co("Milano Sportswear Srl", "Milan", "Italy", buys=True, sells=False, year=2003,
       products=["Sweatshirts & hoodies", "T-shirts"],
       contacts=[("Luca Bianchi", "Product director", "luca@milanosport.example",
                  "+39 02 5555 0142", True)]),
    Co("Gulf Uniforms LLC", "Dubai", "United Arab Emirates", buys=True, sells=False, year=2014,
       products=["Polo shirts"],
       contacts=[("Omar Haddad", "Procurement", "omar@gulfuniforms.example", None, True)],
       payment_terms="30 days"),
    Co("Pacific Outdoor Co", "Seattle", "United States", buys=True, sells=False,
       status=CompanyStatus.LEAD, year=2018, products=["Sweatshirts & hoodies"],
       contacts=[("Rachel Kim", "Sourcing manager", "rachel@pacificoutdoor.example", None, True)],
       notes="Asked for recycled-polyester fleece samples; nothing agreed."),
    Co("Marina Bay Trading Pte", "Singapore", "Singapore", buys=True, year=2016,
       processes=[("Trading / sourcing", None, None, None, None)],
       products=["Yarn", "Raw cotton"],
       contacts=[("Wei Ling Tan", "Trader", "weiling@marinabay.example", "+65 6555 0199", True)],
       payment_terms="CAD"),
]

USERS = [("Meera Nair", "meera@ecolink.example", UserRole.ADMIN),
         ("Arjun Rao", "arjun@ecolink.example", UserRole.MEMBER),
         ("Priya Iyer", "priya@ecolink.example", UserRole.MEMBER)]


# ======================================================================= the deals
# How many deals of each kind, and in which states. Fifty in all: eight closed in 2025, the rest
# spread across every status this year, so "which deals are on hold" and "what did we earn last
# year" both have real answers.
STATUS_2025 = [S.COMPLETED] * 6 + [S.LOST] * 2
STATUS_2026 = ([S.COMPLETED] * 3 + [S.SHIPPED] * 7 + [S.IN_PROGRESS] * 10 + [S.AGREED] * 6
               + [S.NEGOTIATING] * 8 + [S.LEAD] * 4 + [S.ON_HOLD] * 3 + [S.LOST] * 1)
KINDS = (["cotton"] * 8 + ["yarn"] * 7 + ["garments"] * 14 + ["finishing"] * 7
         + ["denim"] * 6 + ["home"] * 5 + ["trading"] * 3)
LOST_REASONS = ["Price — the buyer took a cheaper offer",
                "Lead time too long for the buyer's season",
                "Buyer postponed the programme indefinitely"]


@dataclass
class Leg:
    company: str
    role: str
    qty: float
    uom: str
    unit_price: float
    basis: str = B.NONE
    pct: float | None = None
    resale: float | None = None
    fixed: float | None = None
    process: str | None = None


def _buyer_currency(buyer: str) -> str:
    eur = {"Hanse Mode GmbH", "Amstel Basics BV", "Lyon Maison SARL", "Milano Sportswear Srl"}
    if buyer in eur:
        return "EUR"
    if buyer == "Thames Retail Group":
        return "GBP"
    return "USD"


def plan_deal(kind: str, rng: random.Random) -> tuple[str, str, str, str, list[Leg]]:
    """Title, product, currency, incoterm and legs for one deal of a given kind."""
    r = rng
    if kind == "cotton":
        supplier = r.choice(["Saurashtra Organic Ginners", "Texas Gin & Cotton",
                             "Kutch Cotton Farmers Collective", "Marina Bay Trading Pte"])
        buyer = r.choice(["Ludhiana Spinners", "Coimbatore Compact Spinning"])
        qty = r.choice([60, 90, 120, 150, 180, 240, 300])
        price = r.choice([1650, 1720, 1780, 1850, 1910, 2040])
        organic = supplier in {"Saurashtra Organic Ginners", "Kutch Cotton Farmers Collective"}
        legs = [Leg(supplier, R.SUPPLIER, qty, "MT", price, B.PERCENTAGE,
                    pct=r.choice([1.0, 1.5, 2.0]),
                    process="Cotton growing" if "Kutch" in supplier else "Ginning"),
                Leg(buyer, R.BUYER, qty, "MT", price)]
        title = f"{'Organic cotton' if organic else 'Cotton'} — {qty} MT to {buyer.split()[0]}"
        return title, "Raw cotton", "USD", r.choice(["FOB", "CIF"]), legs

    if kind == "yarn":
        supplier = r.choice(["Ludhiana Spinners", "Coimbatore Compact Spinning",
                             "Panipat Recycled Fibres", "Salem Yarn Dyers"])
        buyer = r.choice(["Kavya Knitwear", "Sri Balaji Knits", "Dhaka Knit Composite"])
        qty = r.choice([20000, 35000, 50000, 80000, 120000])
        domestic = buyer != "Dhaka Knit Composite"
        price = r.choice([285, 310, 340, 365]) if domestic else r.choice([3.4, 3.7, 4.1])
        legs = [Leg(supplier, R.SUPPLIER, qty, "KG", price, B.PERCENTAGE,
                    pct=r.choice([1.0, 1.5, 2.0]),
                    process="Yarn dyeing" if supplier == "Salem Yarn Dyers" else "Spinning"),
                Leg(buyer, R.BUYER, qty, "KG", price)]
        yarn = "Recycled yarn" if supplier == "Panipat Recycled Fibres" else "Combed yarn"
        return (f"{yarn} — {qty // 1000} MT to {buyer.split()[0]}", "Yarn",
                "INR" if domestic else "USD", "EXW" if domestic else "CIF", legs)

    if kind == "garments":
        maker = r.choice(["Kavya Knitwear", "Dhaka Knit Composite", "Saigon Garment Co",
                          "Chittagong Denim Ltd"])
        buyer = r.choice(["Hanse Mode GmbH", "Amstel Basics BV", "Thames Retail Group",
                          "Sakura Lifestyle KK", "Milano Sportswear Srl", "Gulf Uniforms LLC",
                          "Pacific Outdoor Co"])
        product = r.choice(["T-shirts", "Polo shirts", "Sweatshirts & hoodies", "Kidswear",
                            "Innerwear"])
        qty = r.choice([6000, 12000, 20000, 30000, 45000, 60000])
        price = r.choice([2.8, 3.4, 4.2, 5.6, 7.9, 9.5])
        if r.random() < 0.5:
            legs = [Leg(maker, R.SUPPLIER, qty, "PCS", price, B.PERCENTAGE,
                        pct=r.choice([3.0, 4.0, 5.0, 6.0]), process="Garmenting"),
                    Leg(buyer, R.BUYER, qty, "PCS", price)]
        else:
            # We buy in and sell on: the commission is the margin.
            resale = round(price * r.choice([1.08, 1.1, 1.12, 1.15]), 2)
            legs = [Leg(maker, R.SUPPLIER, qty, "PCS", price, process="Garmenting"),
                    Leg(buyer, R.BUYER, qty, "PCS", price, B.MARGIN, resale=resale)]
        if r.random() < 0.3:
            legs.insert(1, Leg("Chennai Testing Labs", R.OTHER, 1, "PCS",
                               r.choice([900, 1200, 1800]), process="Testing lab"))
        return (f"{product} — {qty:,} pcs for {buyer.split()[0]}", product,
                _buyer_currency(buyer), r.choice(["FOB", "CIF", "DDP"]), legs)

    if kind == "finishing":
        chem = r.choice(["Nagoya Finishing Chemicals", "Rhine Textile Auxiliaries"])
        processor = r.choice(["Orient Fabric Processors", "Orient Fabric Processors",
                              "Dhaka Knit Composite"])
        buyer = r.choice(["Hanse Mode GmbH", "Thames Retail Group", "Sakura Lifestyle KK",
                          "Milano Sportswear Srl"])
        kg = r.choice([8000, 12000, 18000, 25000])
        buy_in = r.choice([4.6, 5.05, 5.4])
        legs = [Leg(chem, R.INPUT_SUPPLIER, r.choice([200, 300, 400]), "LTR",
                    r.choice([38, 42, 47]), process="Chemical / treatment supply"),
                Leg(processor, R.PROCESSOR, kg, "KG", r.choice([2.6, 2.9, 3.2]), B.PERCENTAGE,
                    pct=r.choice([3.0, 4.0, 5.0]), process="Fabric dyeing"),
                Leg(buyer, R.BUYER, kg, "KG", buy_in, B.MARGIN,
                    resale=round(buy_in * r.choice([1.08, 1.11, 1.14]), 2))]
        finish = "Cooling finish" if "Nagoya" in chem else "Anti-odour finish"
        return (f"{finish} — {kg // 1000} MT fabric for {buyer.split()[0]}", "Finished fabric",
                _buyer_currency(buyer), "CIF", legs)

    if kind == "denim":
        mill = r.choice(["Ahmedabad Denim Mills", "Chittagong Denim Ltd"])
        buyer = r.choice(["Milano Sportswear Srl", "Pacific Outdoor Co", "Thames Retail Group",
                          "Hanse Mode GmbH"])
        metres = r.choice([20000, 40000, 60000, 90000])
        price = r.choice([3.1, 3.6, 4.2])
        legs = [Leg(mill, R.SUPPLIER, metres, "MTR", price, B.PERCENTAGE,
                    pct=r.choice([2.0, 3.0]), process="Weaving"),
                Leg(buyer, R.BUYER, metres, "MTR", price)]
        if r.random() < 0.4:
            legs.insert(1, Leg("Tuticorin Freight Services", R.OTHER, 1, "PCS",
                               r.choice([2400, 3800, 5200]), process="Logistics"))
        return (f"Denim — {metres:,} m for {buyer.split()[0]}", "Finished fabric",
                _buyer_currency(buyer), "FOB", legs)

    if kind == "home":
        buyer = r.choice(["Lyon Maison SARL", "Thames Retail Group", "Hanse Mode GmbH"])
        pcs = r.choice([8000, 15000, 25000, 40000])
        price = r.choice([6.5, 8.2, 11.0, 14.5])
        fixed = r.random() < 0.4
        legs = [Leg("Karur Home Textiles", R.SUPPLIER, pcs, "PCS", price,
                    B.FIXED if fixed else B.PERCENTAGE,
                    pct=None if fixed else r.choice([3.0, 4.0]),
                    fixed=r.choice([2500, 4000, 6000]) if fixed else None,
                    process="Weaving"),
                Leg(buyer, R.BUYER, pcs, "PCS", price)]
        item = r.choice(["Bed linen", "Kitchen towels", "Table linen"])
        return (f"{item} — {pcs:,} pcs for {buyer.split()[0]}", "Home textiles",
                _buyer_currency(buyer), "FOB", legs)

    # trading: yarn through Marina Bay, who buy from our spinners and sell on in Asia.
    supplier = r.choice(["Coimbatore Compact Spinning", "Ludhiana Spinners"])
    kg = r.choice([40000, 60000, 100000])
    price = r.choice([3.3, 3.6, 3.9])
    legs = [Leg(supplier, R.SUPPLIER, kg, "KG", price, B.PERCENTAGE, pct=1.5, process="Spinning"),
            Leg("Marina Bay Trading Pte", R.BUYER, kg, "KG", price)]
    return f"Yarn — {kg // 1000} MT via Marina Bay", "Yarn", "USD", "CIF", legs


MILESTONES = {
    "cotton": ["Contract signed", "Lot samples approved", "Bales pressed", "Container booked",
               "Vessel sails", "Documents to mill", "Commission received"],
    "yarn": ["Order confirmed", "Count and twist approved", "Production complete",
             "Dispatched", "Commission received"],
    "garments": ["Proto sample approved", "Fit sample approved", "Fabric in-house",
                 "Production starts", "Pre-shipment inspection", "Shipped",
                 "Commission received"],
    "finishing": ["Lab dips approved", "Chemistry shipped", "Bulk dyeing starts",
                  "Fabric ex-mill", "Commission received"],
    "denim": ["Fabric development approved", "Wash standard approved", "Bulk production",
              "Shipped", "Commission received"],
    "home": ["Designs approved", "Strike-off approved", "Bulk weaving", "Shipped",
             "Commission received"],
    "trading": ["Order confirmed", "Dispatched", "Commission received"],
}


# ================================================================== the machinery
def eval_url() -> str:
    url = make_url(settings.database_url).set(database=EVAL_DB)
    return url.render_as_string(hide_password=False)


def _assert_safe(url: str) -> None:
    name = make_url(url).database
    live = make_url(settings.database_url).database
    if name in PROTECTED or name == live or name != EVAL_DB:
        raise SystemExit(f"Refusing to touch database {name!r} — this script only ever builds "
                         f"{EVAL_DB!r}.")


def _psql(sql: str, db: str = "postgres") -> str:
    # Runs as the local superuser. Only needed for CREATE DATABASE and CREATE EXTENSION —
    # the app's own role can create a database but not the vector extension.
    return subprocess.run(["psql", "-d", db, "-Atqc", sql], check=True,
                          capture_output=True, text=True).stdout.strip()


def create_database(reset: bool) -> bool:
    exists = _psql(f"select 1 from pg_database where datname = '{EVAL_DB}'") == "1"
    if exists and not reset:
        return False
    owner = make_url(settings.database_url).username
    if exists:
        _psql(f"drop database {EVAL_DB} with (force)")
    _psql(f'create database {EVAL_DB} owner "{owner}"')
    _psql("create extension if not exists vector", db=EVAL_DB)
    env = {**os.environ, "DATABASE_URL": eval_url()}
    subprocess.run([str(BACKEND / ".venv" / "bin" / "alembic"), "upgrade", "head"],
                   cwd=BACKEND, env=env, check=True, capture_output=True)
    return True


def _at(d: date, hour: int = 10) -> datetime:
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def seed(db: Session) -> None:
    rng = random.Random(SEED)
    seed_taxonomy(db)

    def ref(domain: D, text: str):
        item = resolve(db, domain, text)
        if item is None:
            raise SystemExit(f"{domain} {text!r} is not in the taxonomy")
        return item

    users = []
    for name, email, role in USERS:
        user = User(name=name, email=email, role=role, status=UserStatus.ACTIVE)
        db.add(user)
        users.append(user)
    db.flush()

    companies: dict[str, Company] = {}
    for i, c in enumerate(COMPANIES):
        created = _at(date(2025, 1, 6) + timedelta(days=9 * i))
        company = Company(
            name=c.name, legal_name=None, country_id=ref(D.COUNTRY, c.country).id, city=c.city,
            buys=c.buys, sells=c.sells, status=c.status, year_established=c.year,
            payment_terms=c.payment_terms, moq_notes=c.moq_notes,
            lead_time_notes=c.lead_time_notes, quality_requirements=c.quality, notes=c.notes,
            created_at=created, updated_at=created,
        )
        db.add(company)
        db.flush()
        companies[c.name] = company
        for process, cap, moq, uom, lead in c.processes:
            db.add(CompanyProcess(company_id=company.id, process_id=ref(D.PROCESS, process).id,
                                  monthly_capacity=cap, min_order_qty=moq, uom=uom,
                                  lead_time_days=lead))
        for product in c.products:
            db.add(CompanyProduct(company_id=company.id, product_id=ref(D.PRODUCT, product).id))
        for cert, ref_no in c.certs:
            db.add(CompanyCertification(company_id=company.id, reference_no=ref_no,
                                        certification_id=ref(D.CERTIFICATION, cert).id))
        for client, current in c.clients:
            db.add(CompanyClient(company_id=company.id, client_name=client, is_current=current))
        for name, designation, email, phone, primary in c.contacts:
            db.add(Contact(company_id=company.id, name=name, designation=designation,
                           email=email, phone=phone, whatsapp=phone if phone else None,
                           is_primary=primary))
    db.flush()

    # ---- fifty deals, created in date order so their numbers run with the calendar
    kinds = KINDS[:]
    rng.shuffle(kinds)
    statuses = [(s, 2025) for s in STATUS_2025] + [(s, 2026) for s in STATUS_2026]
    plans = []
    for (status, year), kind in zip(statuses, kinds):
        if year == 2025:
            created = date(2025, 2, 3) + timedelta(days=rng.randint(0, 260))
        elif status in (S.LEAD, S.NEGOTIATING):
            created = date(2026, 6, 1) + timedelta(days=rng.randint(0, 95))
        else:
            created = date(2026, 1, 5) + timedelta(days=rng.randint(0, 200))
        plans.append((created, kind, status))
    plans.sort(key=lambda p: p[0])

    for n, (created, kind, status) in enumerate(plans):
        title, product, currency, incoterm, legs = plan_deal(kind, rng)
        # A mill shut by a flood can only be on a programme that is now on hold. Surat Weaving
        # (blacklisted) is never picked at all, so "companies we have never dealt with" has a
        # real answer.
        if status == S.ON_HOLD and kind == "finishing":
            legs[1].company = "Erode Print House"
            legs[1].process = "Printing"

        ship = {
            S.COMPLETED: created + timedelta(days=rng.randint(40, 110)),
            S.SHIPPED: created + timedelta(days=rng.randint(40, 90)),
            S.IN_PROGRESS: ANCHOR + timedelta(days=rng.randint(-12, 55)),
            S.AGREED: ANCHOR + timedelta(days=rng.randint(20, 100)),
            S.NEGOTIATING: ANCHOR + timedelta(days=rng.randint(45, 140)),
            S.LEAD: ANCHOR + timedelta(days=rng.randint(60, 150)),
            S.ON_HOLD: ANCHOR + timedelta(days=rng.randint(-20, 60)),
            S.LOST: None,
        }[status]
        # Shipped and completed deals shipped in the past — and a completed one early enough to
        # have been closed afterwards.
        if status == S.SHIPPED:
            ship = min(ship, ANCHOR - timedelta(days=rng.randint(3, 30)))
        elif status == S.COMPLETED:
            ship = min(ship, ANCHOR - timedelta(days=rng.randint(25, 60)))
        closed = None
        if status == S.COMPLETED:
            closed = min(ship + timedelta(days=rng.randint(20, 60)), ANCHOR - timedelta(days=2))
        elif status == S.LOST:
            closed = created + timedelta(days=rng.randint(15, 60))

        deal = Deal(
            deal_no=svc.next_deal_no(db, on=created), title=title,
            description=f"{kind.title()} programme — imagined for evaluation.",
            product_id=ref(D.PRODUCT, product).id, currency_id=ref(D.CURRENCY, currency).id,
            incoterm_id=ref(D.INCOTERM, incoterm).id, status=status,
            lost_reason=rng.choice(LOST_REASONS) if status == S.LOST else None,
            target_ship_date=ship, closed_at=_at(closed, 17) if closed else None,
            owner_user_id=users[n % len(users)].id,
            created_at=_at(created), updated_at=_at(created),
        )
        if status in (S.COMPLETED, S.LOST):
            deal.last_activity_at = _at(closed, 17)
        else:
            # Some deals have been left alone for weeks: the "gone quiet" questions need them.
            deal.last_activity_at = _at(ANCHOR - timedelta(days=rng.choice([1, 2, 4, 6, 9, 16,
                                                                          21, 30, 38])))
        db.add(deal)
        db.flush()

        for seq, leg in enumerate(legs, start=1):
            value = round(leg.qty * (leg.resale if leg.resale else leg.unit_price), 2)
            party = DealParty(
                deal_id=deal.id, company_id=companies[leg.company].id, role=leg.role,
                sequence=seq, qty=leg.qty, uom=leg.uom, unit_price=leg.unit_price,
                resale_unit_price=leg.resale, value=value,
                process_id=ref(D.PROCESS, leg.process).id if leg.process else None,
                commission_basis=leg.basis, commission_pct=leg.pct,
                commission_amount=leg.fixed,
                ship_date=ship if leg.role in (R.SUPPLIER, R.PROCESSOR, R.BUYER) else None,
            )
            if leg.basis != B.NONE:
                party.commission_status = _commission_status(status, rng)
                if party.commission_status in (CS.INVOICED, CS.RECEIVED) and ship:
                    party.invoiced_on = min(ship + timedelta(days=rng.randint(3, 15)), ANCHOR)
                if party.commission_status == CS.RECEIVED and party.invoiced_on:
                    party.received_on = min(party.invoiced_on + timedelta(
                        days=rng.randint(10, 45)), ANCHOR)
            svc.refresh_commission(party)
            db.add(party)

        names = MILESTONES[kind]
        if status in (S.LEAD, S.NEGOTIATING):
            names = names[:2]
        horizon = ship or (closed or created + timedelta(days=60))
        span = max((horizon - created).days, len(names))
        for i, name in enumerate(names):
            planned = created + timedelta(days=round(span * (i + 1) / (len(names) + 1)))
            if name == "Commission received":
                planned = horizon + timedelta(days=30)
            done = planned < ANCHOR and status not in (S.ON_HOLD, S.LOST)
            if status == S.COMPLETED:
                m_status = M.DONE
            elif status == S.LOST:
                m_status = M.SKIPPED
            elif status == S.ON_HOLD and planned >= created + timedelta(days=span // 3):
                m_status = M.BLOCKED
            elif done and rng.random() < 0.2:
                m_status = M.IN_PROGRESS      # overdue: planned in the past, not finished
            elif done:
                m_status = M.DONE
            else:
                m_status = M.PENDING
            actual = (min(planned + timedelta(days=rng.randint(-2, 4)), ANCHOR)
                      if m_status == M.DONE else None)
            db.add(DealMilestone(deal_id=deal.id, name=name, sequence=i + 1,
                                 planned_date=planned, actual_date=actual, status=m_status,
                                 owner_user_id=deal.owner_user_id))
        db.flush()

    db.commit()


def _commission_status(deal_status: str, rng: random.Random) -> str:
    if deal_status == S.COMPLETED:
        return CS.RECEIVED if rng.random() < 0.8 else CS.WRITTEN_OFF
    if deal_status == S.SHIPPED:
        return CS.INVOICED if rng.random() < 0.6 else CS.DUE
    if deal_status == S.IN_PROGRESS:
        return CS.DUE if rng.random() < 0.4 else CS.NOT_DUE
    return CS.NOT_DUE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true",
                        help=f"drop {EVAL_DB} and rebuild it from scratch")
    args = parser.parse_args()

    url = eval_url()
    _assert_safe(url)
    if not create_database(args.reset):
        print(f"{EVAL_DB} already exists — pass --reset to rebuild it.")
        return 0

    engine = create_engine(url)
    with sessionmaker(bind=engine)() as db:
        if db.scalar(select(func.count(Deal.id))):
            raise SystemExit(f"{EVAL_DB} already has deals; refusing to seed twice.")
        seed(db)
        companies = db.scalar(select(func.count(Company.id)))
        deals = db.scalar(select(func.count(Deal.id)))
        legs = db.scalar(select(func.count(DealParty.id)))
        milestones = db.scalar(select(func.count(DealMilestone.id)))
    engine.dispose()
    print(f"{EVAL_DB}: {companies} companies, {deals} deals, {legs} deal legs, "
          f"{milestones} milestones — 'today' is fixed at {ANCHOR:%d %B %Y}.")
    print(f"The app still reads {make_url(settings.database_url).database!r}; this is invisible "
          f"to it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
