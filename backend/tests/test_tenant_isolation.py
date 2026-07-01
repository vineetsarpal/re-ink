"""
Tenant isolation tests — the regulatory core.

These run through the restricted (non-BYPASSRLS) ``db_session`` and prove that
Postgres RLS keeps one organization's contracts invisible to another, keyed on
the ``app.current_org`` GUC set via ``bind_session_to_org``.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core.tenancy import bind_session_to_org
from app.models.contract import Contract

ORG_A = "org_aaaaaaaaaaaaaaaaaaaaaaaa"
ORG_B = "org_bbbbbbbbbbbbbbbbbbbbbbbb"


def _contract(number: str) -> Contract:
    return Contract(
        contract_number=number,
        contract_name="Isolation",
        effective_date=date(2026, 1, 1),
        expiration_date=date(2026, 12, 31),
    )


def test_contract_is_invisible_to_another_org(db_session) -> None:
    bind_session_to_org(db_session, ORG_A)
    db_session.add(_contract("ISO-A"))
    db_session.flush()

    bind_session_to_org(db_session, ORG_B)
    assert (
        db_session.query(Contract).filter_by(contract_number="ISO-A").count() == 0
    )


def test_unset_org_sees_no_rows(db_session) -> None:
    """A query with no org bound (e.g. an escaped path) returns nothing, not a leak."""
    bind_session_to_org(db_session, ORG_A)
    db_session.add(_contract("ISO-FC"))
    db_session.flush()

    # Simulate a code path that never bound an org: reset the GUC to unset.
    db_session.execute(text("RESET app.current_org"))
    assert (
        db_session.query(Contract).filter_by(contract_number="ISO-FC").count() == 0
    )


def test_cannot_write_row_owned_by_another_org(db_session) -> None:
    """Bound to org A, inserting a row stamped org B is refused by the policy check."""
    bind_session_to_org(db_session, ORG_A)
    with pytest.raises(ProgrammingError):
        db_session.execute(
            text(
                "INSERT INTO contracts "
                "(contract_number, contract_name, effective_date, expiration_date, org_id) "
                "VALUES ('CROSS', 'n', '2026-01-01', '2026-12-31', :o)"
            ),
            {"o": ORG_B},
        )
        db_session.flush()


def test_insert_stamps_org_id_from_guc(db_session) -> None:
    """A row inserted without org_id is stamped from the bound org via the column default."""
    bind_session_to_org(db_session, ORG_A)
    db_session.add(_contract("STAMP"))
    db_session.flush()

    row = db_session.execute(
        text("SELECT org_id FROM contracts WHERE contract_number = 'STAMP'")
    ).one()
    assert row.org_id == ORG_A


def test_same_contract_number_allowed_across_orgs(db_session) -> None:
    """Contract numbers are unique per org, so two orgs may reuse the same number."""
    bind_session_to_org(db_session, ORG_A)
    db_session.add(_contract("SHARED"))
    db_session.flush()

    bind_session_to_org(db_session, ORG_B)
    db_session.add(_contract("SHARED"))
    db_session.flush()  # must not raise


def test_duplicate_contract_number_within_org_rejected(db_session) -> None:
    """The same number twice in one org still violates the composite unique."""
    bind_session_to_org(db_session, ORG_A)
    db_session.add(_contract("DUP1"))
    db_session.flush()

    db_session.add(_contract("DUP1"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def _api_contract(number: str) -> dict:
    return {
        "contract_number": number,
        "contract_name": "Endpoint Iso",
        "effective_date": "2026-01-01",
        "expiration_date": "2026-12-31",
    }


def test_endpoint_hides_another_orgs_contract(as_org) -> None:
    """A contract created by org A is 404 and absent from listings for org B."""
    org_a = as_org(ORG_A)
    created = org_a.post("/api/contracts/", json=_api_contract("EP-A"))
    assert created.status_code == 201, created.text
    contract_id = created.json()["id"]

    org_b = as_org(ORG_B)
    assert org_b.get(f"/api/contracts/{contract_id}").status_code == 404
    listing = org_b.get("/api/contracts/").json()
    assert all(c["id"] != contract_id for c in listing)


def test_org_guc_survives_a_real_commit(restricted_engine, monkeypatch) -> None:
    """After a genuine commit, get_tenant_db re-binds the org on the next txn.

    The rolled-back harness can't exercise a real commit, so this drives
    get_tenant_db against real commits: without the after_begin re-bind, the
    second insert would stamp a NULL org (GUC reset) and violate NOT NULL.
    """
    from sqlalchemy.orm import sessionmaker

    import app.core.tenancy as tenancy
    from app.core.auth import CurrentUser

    org = "org_realcommit_probe"
    monkeypatch.setattr(
        tenancy, "SessionLocal", sessionmaker(bind=restricted_engine, autoflush=False)
    )
    gen = tenancy.get_tenant_db(CurrentUser(user_id="u", org_id=org))
    db = next(gen)
    try:
        db.add(_contract("RC-1"))
        db.commit()  # real commit ends the transaction and the SET LOCAL GUC
        db.add(_contract("RC-2"))
        db.commit()  # a new transaction; the listener must have re-bound the org
        rows = db.execute(
            text(
                "SELECT org_id FROM contracts WHERE contract_number IN ('RC-1', 'RC-2')"
            )
        ).all()
        assert len(rows) == 2
        assert all(r.org_id == org for r in rows)
    finally:
        db.execute(text("DELETE FROM contracts WHERE contract_number IN ('RC-1', 'RC-2')"))
        db.commit()
        try:
            next(gen)
        except StopIteration:
            pass
