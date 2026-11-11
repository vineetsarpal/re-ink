"""Accounting records retained independently of uploaded documents."""
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Integer, LargeBinary, String
from app.db.database import Base


class GlobalQuota(Base):
    __tablename__ = "extraction_quota_global"
    id = Column(Integer, primary_key=True)
    month = Column(Date, nullable=False)
    trial_successes = Column(Integer, nullable=False)
    trial_pending = Column(Integer, nullable=False)
    trial_starts = Column(Integer, nullable=False, server_default="0")
    __table_args__ = (CheckConstraint("id = 1 AND trial_successes >= 0 AND trial_pending >= 0"),)


class OrganizationQuota(Base):
    __tablename__ = "extraction_quota_org"
    org_id = Column(String(255), primary_key=True)
    month = Column(Date, nullable=False)
    monthly_successes = Column(Integer, nullable=False)
    monthly_attempts = Column(Integer, nullable=False)
    pending = Column(Integer, nullable=False)
    free_successes = Column(Integer, nullable=False)
    free_pending = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("monthly_successes >= 0 AND monthly_attempts >= 0 AND pending >= 0 AND free_successes >= 0 AND free_pending >= 0"),)


class QuotaReservation(Base):
    __tablename__ = "extraction_quota_reservations"
    org_id = Column(String(255), primary_key=True)
    attempt_id = Column(String(128), primary_key=True)
    funding = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    credential_snapshot = Column(LargeBinary)
    provider_started = Column(Boolean, nullable=False, server_default="false")
    __table_args__ = (CheckConstraint("funding IN ('trial', 'customer')"), CheckConstraint("status IN ('pending', 'succeeded', 'failed')"))


class ExtractionRate(Base):
    __tablename__ = "extraction_rate_org"
    org_id = Column(String(255), primary_key=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("attempts >= 0"),)
