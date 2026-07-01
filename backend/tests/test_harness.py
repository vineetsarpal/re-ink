"""
Meta-tests for the Postgres test harness itself.

These lock in the properties that every other test relies on: the shared
``db_session`` fixture talks to a real, migrated Postgres database; writes are
isolated per test; and the session connects as a restricted (non-superuser,
non-BYPASSRLS) role so the tenancy RLS tests added later cannot be silently
bypassed.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.models.contract import Contract


def test_db_session_persists_and_reads_back(db_session) -> None:
    """The fixture yields a working, migrated Postgres session."""
    contract = Contract(
        contract_number="TRACER-1",
        contract_name="Tracer Bullet",
        effective_date=date(2026, 1, 1),
        expiration_date=date(2026, 12, 31),
    )
    db_session.add(contract)
    db_session.flush()

    got = db_session.query(Contract).filter_by(contract_number="TRACER-1").one()
    assert got.contract_name == "Tracer Bullet"


def _make_contract(number: str) -> Contract:
    return Contract(
        contract_number=number,
        contract_name="Isolation Probe",
        effective_date=date(2026, 1, 1),
        expiration_date=date(2026, 12, 31),
    )


def test_isolation_writer(db_session) -> None:
    """Writing a marker row that the sibling test must never observe."""
    assert db_session.query(Contract).filter_by(contract_number="ISO-1").count() == 0
    db_session.add(_make_contract("ISO-1"))
    db_session.flush()


def test_db_session_runs_as_restricted_role(db_session) -> None:
    """The session's role is non-superuser and cannot bypass RLS.

    Without this, the tenancy RLS policies added in a later slice could be
    silently bypassed by a superuser test connection — a false green.
    """
    row = db_session.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname = current_user"
        )
    ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


def test_isolation_reader(db_session) -> None:
    """The marker row from the sibling test was rolled back, so it is absent."""
    assert db_session.query(Contract).filter_by(contract_number="ISO-1").count() == 0
    db_session.add(_make_contract("ISO-1"))
    db_session.flush()
