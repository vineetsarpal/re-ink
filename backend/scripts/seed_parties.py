"""
Seed script: populate the parties table with a set of well-known reinsurance
market participants, including all parties referenced in the mock extraction
fixtures so that fuzzy-matching works out of the box during local development.

Usage (from the backend/ directory, venv activated):
    python scripts/seed_parties.py

The script is idempotent — parties whose name already exists are skipped.
"""
import sys
import os

# Make sure app imports resolve when run directly from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal, engine, Base
from app.models.party import Party  # noqa: F401 — registers the model
from app.models.contract import Contract, contract_parties  # noqa: F401 — registers contract models

# Ensure all tables exist (no-op if already created)
Base.metadata.create_all(bind=engine)

PARTIES = [
    # ------------------------------------------------------------------ #
    # Cedants — appear as cedant in the mock extraction scenarios
    # ------------------------------------------------------------------ #
    {
        "name": "Vesta Fire Insurance Corp",
        "email": "reinsurance@vestafire.com",
        "phone": "+1-415-555-0101",
        "address_line1": "650 California Street",
        "city": "San Francisco",
        "state": "CA",
        "postal_code": "94108",
        "country": "United States",
        "registration_number": "US-INS-VESTA-001",
        "license_number": "CA-LIC-VESTA-2024",
        "notes": "California-based property insurer; primary cedant in quota share programs.",
    },
    {
        "name": "Republic Insurance Company",
        "email": "treaty@republicins.com",
        "phone": "+1-214-555-0202",
        "address_line1": "8144 Walnut Hill Lane",
        "city": "Dallas",
        "state": "TX",
        "postal_code": "75231",
        "country": "United States",
        "registration_number": "US-INS-REPUBLIC-002",
        "license_number": "TX-LIC-REPUBLIC-2024",
        "notes": "Texas domiciled insurer specialising in commercial lines; primary cedant in XOL programs.",
    },
    {
        "name": "National Union Fire Insurance",
        "email": "reinsurance@nationalunion.com",
        "phone": "+1-212-555-0303",
        "address_line1": "175 Water Street",
        "city": "New York",
        "state": "NY",
        "postal_code": "10038",
        "country": "United States",
        "registration_number": "US-INS-NUFI-003",
        "license_number": "NY-LIC-NUFI-2024",
        "notes": "AIG subsidiary; cedant in surplus treaty arrangements.",
    },
    {
        "name": "ABC Insurance Company",
        "email": "contact@abcinsurance.com",
        "phone": "+1-555-0100",
        "address_line1": "123 Main Street",
        "city": "New York",
        "state": "NY",
        "postal_code": "10001",
        "country": "United States",
        "registration_number": "US-INS-ABC-004",
        "notes": "Used in test/mock extraction scenarios.",
    },

    # ------------------------------------------------------------------ #
    # Reinsurers — appear as reinsurer in the mock extraction scenarios
    # ------------------------------------------------------------------ #
    {
        "name": "Affirmative Insurance Company",
        "email": "submissions@affirmative.com",
        "phone": "+1-972-555-0404",
        "address_line1": "4450 Sojourn Drive",
        "city": "Addison",
        "state": "TX",
        "postal_code": "75001",
        "country": "United States",
        "registration_number": "US-INS-AFF-005",
        "license_number": "TX-LIC-AFF-2024",
        "notes": "Non-standard lines reinsurer.",
    },
    {
        "name": "Winterthur Swiss Insurance",
        "email": "reinsurance@winterthur.ch",
        "phone": "+41-52-261-2121",
        "address_line1": "Römerstrasse 17",
        "city": "Winterthur",
        "postal_code": "8400",
        "country": "Switzerland",
        "registration_number": "CH-INS-WTH-006",
        "license_number": "FINMA-WTH-2024",
        "notes": "Swiss reinsurer; part of the AXA group.",
    },
    {
        "name": "Swiss Reinsurance Company Ltd",
        "email": "client.markets@swissre.com",
        "phone": "+41-43-285-2121",
        "address_line1": "Mythenquai 50/60",
        "city": "Zurich",
        "postal_code": "8022",
        "country": "Switzerland",
        "registration_number": "CH-INS-SWRE-007",
        "license_number": "FINMA-SWRE-2024",
        "notes": "One of the world's largest reinsurers.",
    },
    {
        "name": "XYZ Reinsurance Ltd",
        "email": "info@xyzre.com",
        "address_line1": "456 Financial District",
        "city": "London",
        "country": "United Kingdom",
        "registration_number": "UK-INS-XYZ-008",
        "notes": "Used in test/mock extraction scenarios.",
    },

    # ------------------------------------------------------------------ #
    # Brokers
    # ------------------------------------------------------------------ #
    {
        "name": "Aon Benfield Securities",
        "email": "reinsurance@aonbenfield.com",
        "phone": "+1-312-381-1000",
        "address_line1": "200 E. Randolph Street",
        "city": "Chicago",
        "state": "IL",
        "postal_code": "60601",
        "country": "United States",
        "registration_number": "US-BKR-AON-009",
        "license_number": "IL-BKR-AON-2024",
        "notes": "Global reinsurance broker; intermediary on surplus treaty programs.",
    },
    {
        "name": "Guy Carpenter & Company",
        "email": "info@guycarpenter.com",
        "phone": "+1-212-345-5000",
        "address_line1": "1166 Avenue of the Americas",
        "city": "New York",
        "state": "NY",
        "postal_code": "10036",
        "country": "United States",
        "registration_number": "US-BKR-GC-010",
        "license_number": "NY-BKR-GC-2024",
        "notes": "Marsh McLennan subsidiary; one of the leading reinsurance intermediaries.",
    },
    {
        "name": "Willis Re",
        "email": "willisre@wtwco.com",
        "phone": "+44-20-3124-6000",
        "address_line1": "51 Lime Street",
        "city": "London",
        "postal_code": "EC3M 7DQ",
        "country": "United Kingdom",
        "registration_number": "UK-BKR-WRE-011",
        "notes": "WTW reinsurance broking division.",
    },

    # ------------------------------------------------------------------ #
    # Additional well-known market participants
    # ------------------------------------------------------------------ #
    {
        "name": "Munich Reinsurance Company",
        "email": "info@munichre.com",
        "phone": "+49-89-38910",
        "address_line1": "Königinstrasse 107",
        "city": "Munich",
        "postal_code": "80802",
        "country": "Germany",
        "registration_number": "DE-INS-MRE-012",
        "notes": "World's largest reinsurer by premium volume.",
    },
    {
        "name": "Hannover Re",
        "email": "info@hannover-re.com",
        "phone": "+49-511-5604-0",
        "address_line1": "Karl-Wiechert-Allee 50",
        "city": "Hannover",
        "postal_code": "30625",
        "country": "Germany",
        "registration_number": "DE-INS-HRE-013",
        "notes": "Third-largest reinsurance group worldwide.",
    },
    {
        "name": "Lloyd's of London",
        "email": "enquiries@lloyds.com",
        "phone": "+44-20-7327-1000",
        "address_line1": "One Lime Street",
        "city": "London",
        "postal_code": "EC3M 7HA",
        "country": "United Kingdom",
        "registration_number": "UK-INS-LLOYDS-014",
        "notes": "Insurance and reinsurance marketplace.",
    },
]


def seed():
    db = SessionLocal()
    created = 0
    skipped = 0

    try:
        for data in PARTIES:
            existing = db.query(Party).filter(Party.name == data["name"]).first()
            if existing:
                print(f"  skip  {data['name']}")
                skipped += 1
                continue

            party = Party(**data)
            db.add(party)
            db.flush()
            print(f"  add   {party.name} (id={party.id})")
            created += 1

        db.commit()
        print(f"\nDone — {created} created, {skipped} skipped.")
    except Exception as e:
        db.rollback()
        print(f"\nError: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
