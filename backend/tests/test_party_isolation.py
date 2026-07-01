"""
Party tenant isolation — parties are scoped per organization exactly like
contracts, so one org can never see, match, or reuse another org's parties.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.tenancy import bind_session_to_org
from app.models.party import Party

ORG_A = "org_aaaaaaaaaaaaaaaaaaaaaaaa"
ORG_B = "org_bbbbbbbbbbbbbbbbbbbbbbbb"


def test_party_is_invisible_to_another_org(db_session) -> None:
    bind_session_to_org(db_session, ORG_A)
    db_session.add(Party(name="Acme Insurance Co"))
    db_session.flush()

    bind_session_to_org(db_session, ORG_B)
    assert db_session.query(Party).filter_by(name="Acme Insurance Co").count() == 0


def test_same_registration_number_allowed_across_orgs(db_session) -> None:
    bind_session_to_org(db_session, ORG_A)
    db_session.add(Party(name="A Corp", registration_number="REG-1"))
    db_session.flush()

    bind_session_to_org(db_session, ORG_B)
    db_session.add(Party(name="B Corp", registration_number="REG-1"))
    db_session.flush()  # must not raise


def test_duplicate_registration_number_within_org_rejected(db_session) -> None:
    bind_session_to_org(db_session, ORG_A)
    db_session.add(Party(name="A Corp", registration_number="REG-DUP"))
    db_session.flush()

    db_session.add(Party(name="Another", registration_number="REG-DUP"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_endpoint_scopes_parties_and_fuzzy_matching(as_org) -> None:
    """Org B cannot see, list, or fuzzy-match against org A's parties."""
    org_a = as_org(ORG_A)
    created = org_a.post("/api/parties/", json={"name": "Vesta Fire Insurance Corp"})
    assert created.status_code == 201, created.text
    party_id = created.json()["id"]

    org_b = as_org(ORG_B)
    assert org_b.get(f"/api/parties/{party_id}").status_code == 404
    assert all(p["id"] != party_id for p in org_b.get("/api/parties/").json())

    # Fuzzy matching must not surface another org's party — no counterparty leak.
    match = org_b.post(
        "/api/parties/match", json={"names": ["Vesta Fire Insurance Corporation"]}
    )
    assert match.status_code == 200
    assert match.json()[0]["candidates"] == []
