"""Baseline migration — creates the initial schema as defined by the ORM models.

This revision represents the state of the database at the time Alembic was
introduced.  The production database already has these tables; use
``alembic stamp 0001_baseline`` to register this revision without re-running
the DDL.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade — create all four tables in dependency order
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. parties
    #    Source: app/models/party.py  class Party
    # ------------------------------------------------------------------
    op.create_table(
        "parties",
        sa.Column("id", sa.Integer(), nullable=False),
        # Basic information
        sa.Column("name", sa.String(length=255), nullable=False),
        # Contact information
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address_line1", sa.String(length=255), nullable=True),
        sa.Column("address_line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        # Business details
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column("license_number", sa.String(length=100), nullable=True),
        # Additional information
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        # Metadata
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_number"),
    )
    op.create_index(op.f("ix_parties_id"), "parties", ["id"], unique=False)
    op.create_index(op.f("ix_parties_name"), "parties", ["name"], unique=False)
    op.create_index(op.f("ix_parties_email"), "parties", ["email"], unique=False)

    # ------------------------------------------------------------------
    # 2. contracts
    #    Source: app/models/contract.py  class Contract
    #    Must exist before contract_parties (FK target).
    # ------------------------------------------------------------------
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        # Contract identification
        sa.Column("contract_number", sa.String(length=100), nullable=False),
        sa.Column("contract_name", sa.String(length=255), nullable=False),
        sa.Column("contract_type", sa.String(length=50), nullable=True),
        sa.Column("contract_sub_type", sa.String(length=100), nullable=True),
        sa.Column("contract_nature", sa.String(length=50), nullable=True),
        # Contract dates
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("inception_date", sa.Date(), nullable=True),
        # Financial terms
        sa.Column("premium_description", sa.String(length=255), nullable=True),
        sa.Column("premium_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("limit_description", sa.String(length=255), nullable=True),
        sa.Column("limit_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("retention_description", sa.String(length=255), nullable=True),
        sa.Column("retention_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("commission_description", sa.String(length=255), nullable=True),
        sa.Column("commission_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        # Coverage details
        sa.Column("line_of_business", sa.String(length=100), nullable=True),
        sa.Column("coverage_territory", sa.String(length=255), nullable=True),
        sa.Column("coverage_description", sa.Text(), nullable=True),
        # Contract terms
        sa.Column("terms_and_conditions", sa.Text(), nullable=True),
        sa.Column("special_provisions", sa.Text(), nullable=True),
        # Document management
        sa.Column("source_document_path", sa.String(length=500), nullable=True),
        sa.Column("source_document_name", sa.String(length=255), nullable=True),
        # Status and workflow
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("review_status", sa.String(length=50), nullable=True),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        # Extraction metadata
        sa.Column("extraction_confidence", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("extraction_job_id", sa.String(length=100), nullable=True),
        sa.Column("is_manually_created", sa.Boolean(), nullable=True),
        # Additional information
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        # Metadata
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_number"),
    )
    op.create_index(op.f("ix_contracts_id"), "contracts", ["id"], unique=False)
    op.create_index(
        op.f("ix_contracts_contract_number"),
        "contracts",
        ["contract_number"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 3. contract_parties  (association table — depends on contracts + parties)
    #    Source: app/models/contract.py  contract_parties Table()
    # ------------------------------------------------------------------
    op.create_table(
        "contract_parties",
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("party_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("contract_id", "party_id"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
    )

    # ------------------------------------------------------------------
    # 4. extraction_jobs
    #    Source: app/models/extraction_job.py  class ExtractionJob
    #    No FK dependencies — can be created at any point.
    # ------------------------------------------------------------------
    op.create_table(
        "extraction_jobs",
        sa.Column("job_id", sa.String(length=100), nullable=False),
        # status has a Python-side default="processing", NOT a server_default
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("landingai_job_id", sa.String(length=100), nullable=True),
        sa.Column("raw_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parsed_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        op.f("ix_extraction_jobs_job_id"),
        "extraction_jobs",
        ["job_id"],
        unique=False,
    )


# ---------------------------------------------------------------------------
# downgrade — drop in reverse dependency order
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop association table before the tables it references
    op.drop_table("contract_parties")
    # Then the primary tables (order between contracts/parties/extraction_jobs
    # doesn't matter once contract_parties is gone)
    op.drop_index(op.f("ix_extraction_jobs_job_id"), table_name="extraction_jobs")
    op.drop_table("extraction_jobs")
    op.drop_index(op.f("ix_contracts_contract_number"), table_name="contracts")
    op.drop_index(op.f("ix_contracts_id"), table_name="contracts")
    op.drop_table("contracts")
    op.drop_index(op.f("ix_parties_email"), table_name="parties")
    op.drop_index(op.f("ix_parties_name"), table_name="parties")
    op.drop_index(op.f("ix_parties_id"), table_name="parties")
    op.drop_table("parties")
