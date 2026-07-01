"""
contract_parties association isolation — the link rows between contracts and
parties are scoped per org too, closing the raw db.execute() paths that bypass
the ORM models.
"""
from __future__ import annotations

from datetime import date

from app.core.tenancy import bind_session_to_org
from app.models.contract import Contract, contract_parties
from app.models.party import Party

ORG_A = "org_aaaaaaaaaaaaaaaaaaaaaaaa"
ORG_B = "org_bbbbbbbbbbbbbbbbbbbbbbbb"


def _link(db):
    """Create a contract + party under the currently-bound org and link them."""
    contract = Contract(
        contract_number="ASSOC-1",
        contract_name="Assoc",
        effective_date=date(2026, 1, 1),
        expiration_date=date(2026, 12, 31),
    )
    party = Party(name="Linked Party")
    db.add_all([contract, party])
    db.flush()
    db.execute(
        contract_parties.insert().values(
            contract_id=contract.id, party_id=party.id, role="cedant"
        )
    )
    return contract.id


def test_association_row_is_invisible_to_another_org(db_session) -> None:
    bind_session_to_org(db_session, ORG_A)
    contract_id = _link(db_session)
    db_session.flush()

    bind_session_to_org(db_session, ORG_B)
    rows = db_session.execute(
        contract_parties.select().where(contract_parties.c.contract_id == contract_id)
    ).fetchall()
    assert rows == []


def test_contract_party_links_are_org_scoped_through_the_api(as_org) -> None:
    """The raw association insert/select paths stamp and enforce org end to end."""
    org_a = as_org(ORG_A)
    party = org_a.post("/api/parties/", json={"name": "Cedant Co"})
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]

    contract = org_a.post(
        "/api/contracts/",
        json={
            "contract_number": "CP-1",
            "contract_name": "CP",
            "effective_date": "2026-01-01",
            "expiration_date": "2026-12-31",
            "party_roles": [{"party_id": party_id, "role": "cedant"}],
        },
    )
    assert contract.status_code == 201, contract.text
    contract_id = contract.json()["id"]

    # Org A sees the party linked with its role (raw association select under RLS).
    detail = org_a.get(f"/api/contracts/{contract_id}").json()
    assert any(
        p["id"] == party_id and p["role"] == "cedant" for p in detail["parties"]
    )

    # Org B cannot see the contract at all.
    org_b = as_org(ORG_B)
    assert org_b.get(f"/api/contracts/{contract_id}").status_code == 404
