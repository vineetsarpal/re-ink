"""
Read-only orphan organization report (issue #62).

The fake WorkOS client implements only the list/get seams the report may use;
accessing any mutating method raises, and every test also asserts that the
recorded call log contains list_/get_ calls only. Intents are seeded on the
real Postgres test database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.provisioning_intent import ProvisioningIntent
from app.services.orphan_org_report import orphan_org_report

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def org(org_id, name=None):
    return SimpleNamespace(id=org_id, name=name or org_id.removeprefix("org_"))


def membership(user_id, organization_id, mid=None):
    return SimpleNamespace(user_id=user_id, organization_id=organization_id,
                           id=mid or ("m_%s_%s" % (user_id, organization_id)))


class _Page:
    def __init__(self, data, after):
        self.data = data
        self.after = after


class _UserManagement:
    """Only the get_user seam exists; delete/update would raise AttributeError."""

    def __init__(self, owner):
        self._owner = owner

    def __getattr__(self, name):
        raise AttributeError(f"Read-only fake has no user_management.{name}")

    def get_user(self, user_id):
        self._owner.calls.append("user_management.get_user")
        user = self._owner._users[user_id]
        return SimpleNamespace(id=user.id, email=user.email)


class _ListResource:
    """Exposes only list_* methods; anything else fails the test loudly."""

    def __init__(self, owner, label, pager):
        self._owner, self._label, self._pager = owner, label, pager

    def __getattr__(self, name):
        if not name.startswith("list_"):
            raise AttributeError(
                f"Read-only fake has no mutating method {self._label}.{name}"
            )

        def method(**kwargs):
            self._owner.calls.append(f"{self._label}.{name}")
            return self._pager(kwargs)

        return method


class FakeWorkOS:
    """Cursor-paginated fake over the WorkOS seams the report reads."""

    def __init__(self, orgs=(), memberships=(), users=(), page_size=2):
        self._page_size = page_size
        self._orgs = list(orgs)
        self._memberships = list(memberships)
        self._users = {user.id: user for user in users}
        self.calls = []
        self.organizations = _ListResource(self, "organizations", self._page_orgs)
        self.organization_membership = _ListResource(
            self, "organization_membership", self._page_memberships
        )
        self.user_management = _UserManagement(self)

    def _page_orgs(self, params):
        return self._page(self._orgs, params)

    def _page_memberships(self, params):
        rows = [m for m in self._memberships
                if m.organization_id == params.get("organization_id")]
        return self._page(rows, params)

    def _page(self, rows, params):
        start = 0
        after = params.get("after")
        if after is not None:
            start = next(i for i, row in enumerate(rows) if row.id == after) + 1
        window = rows[start:start + self._page_size]
        has_more = start + self._page_size < len(rows)
        return _Page(window, window[-1].id if window and has_more else None)


def assert_read_only(fake):
    assert fake.calls, "the report should call the WorkOS fake"
    assert all(name.split(".", 1)[1].startswith(("list_", "get_")) for name in fake.calls)


def seed_intent(db, user_id, state, *, updated_at, org_id=None):
    intent = ProvisioningIntent(
        user_id=user_id, intent_id=str(uuid4()), state=state, org_id=org_id
    )
    intent.created_at = updated_at - timedelta(minutes=5)
    intent.updated_at = updated_at
    db.add(intent)
    db.flush()  # the report session runs with autoflush disabled
    return intent


def test_reports_all_three_categories(db_session):
    fake = FakeWorkOS(
        orgs=[org("org_a"), org("org_b"), org("org_c"), org("org_d")],
        memberships=[
            membership("user_1", "org_a"),
            membership("user_1", "org_b"),
            membership("user_2", "org_c"),
        ],
        users=[SimpleNamespace(id="user_1", email="alice@acme.com")],
    )
    seed_intent(db_session, "user_pending", "pending", updated_at=NOW - timedelta(hours=2))
    seed_intent(db_session, "user_stuck", "org_created", org_id="org_d",
                updated_at=NOW - timedelta(hours=3))
    seed_intent(db_session, "user_fresh", "pending", updated_at=NOW - timedelta(minutes=30))
    seed_intent(db_session, "user_done", "completed", org_id="org_a",
                updated_at=NOW - timedelta(hours=5))

    report = orphan_org_report(fake, db_session, now=NOW)

    assert [(u.user_id, u.email, u.organization_ids)
            for u in report.multi_org_users] == [("user_1", "alice@acme.com", ["org_a", "org_b"])]
    assert [o.organization_id for o in report.empty_orgs] == ["org_d"]
    seeded = {"user_pending", "user_stuck", "user_fresh", "user_done"}
    reported = [i.user_id for i in report.stale_intents if i.user_id in seeded]
    assert reported == ["user_stuck", "user_pending"]
    assert all(i.state in ("pending", "org_created") for i in report.stale_intents)
    assert_read_only(fake)


def test_clean_setup_reports_nothing(db_session):
    fake = FakeWorkOS(
        orgs=[org("org_a")],
        memberships=[membership("user_1", "org_a")],
        users=[],
    )
    seed_intent(db_session, "user_1", "completed", org_id="org_a", updated_at=NOW - timedelta(hours=5))

    report = orphan_org_report(fake, db_session, now=NOW)

    assert report.multi_org_users == []
    assert report.empty_orgs == []
    assert [i for i in report.stale_intents if i.user_id == "user_1"] == []
    assert_read_only(fake)


def test_paginates_every_workos_list_call(db_session):
    orgs = [org(f"org_{i}") for i in range(5)]
    fake = FakeWorkOS(
        orgs=orgs,
        memberships=[
            membership("user_1", "org_0"),
            membership("user_1", "org_1"),
            membership("user_2", "org_2"),
            membership("user_3", "org_2"),
            membership("user_4", "org_2"),
        ],
        users=[SimpleNamespace(id="user_1", email="alice@acme.com")],
        page_size=2,
    )

    report = orphan_org_report(fake, db_session, now=NOW)

    assert [(u.user_id, u.organization_ids)
            for u in report.multi_org_users] == [("user_1", ["org_0", "org_1"])]
    assert [o.organization_id for o in report.empty_orgs] == ["org_3", "org_4"]
    org_pages = [name for name in fake.calls if name == "organizations.list_organizations"]
    membership_pages = [name for name in fake.calls
                        if name == "organization_membership.list_organization_memberships"]
    assert len(org_pages) == 3  # 5 orgs at 2 per page
    assert len(membership_pages) == 6  # one call per org, two for org_2's three members
    assert_read_only(fake)


def test_stale_threshold_filters_state_and_age(db_session):
    fake = FakeWorkOS()
    seed_intent(db_session, "user_boundary", "pending", updated_at=NOW - timedelta(hours=1))
    seed_intent(db_session, "user_older", "pending", updated_at=NOW - timedelta(hours=1, seconds=1))
    seed_intent(db_session, "user_done", "completed", org_id="org_a",
                updated_at=NOW - timedelta(days=30))
    seeded = {"user_boundary", "user_older", "user_done"}

    report = orphan_org_report(fake, db_session, now=NOW)

    reported = [i.user_id for i in report.stale_intents if i.user_id in seeded]
    assert reported == ["user_older"]  # exactly at the threshold is not stale

    # A shorter threshold picks up every non-completed intent; completed ones never appear.
    shorter = orphan_org_report(fake, db_session, now=NOW, stale_after=timedelta(minutes=20))
    reported = [i.user_id for i in shorter.stale_intents if i.user_id in seeded]
    assert reported == ["user_older", "user_boundary"]


def test_rejects_naive_now(db_session):
    fake = FakeWorkOS()
    with pytest.raises(ValueError):
        orphan_org_report(fake, db_session, now=datetime(2026, 11, 11, 12, 0))
